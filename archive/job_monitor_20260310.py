"""
================================================================================
job_monitor.py
================================================================================
PURPOSE:
    Monitors career pages for director-level clinical development roles across
    a defined list of target companies. Queries ATS job feeds (Workday,
    Greenhouse, Lever) using targeted search clusters, filters results through
    a three-dimensional match framework, scores each match, and outputs a CSV
    ranked by match strength.

HOW TO RUN:
    python job_monitor.py

OUTPUT:
    results/new_jobs_YYYY-MM-DD.csv   — new roles not seen in prior runs
    seen_jobs.json                    — tracks all previously surfaced job IDs
                                        (do not delete this file)

CONFIGURATION:
    All filter keywords, search terms, and scoring weights are in filters.json.
    The company list and ATS connection details are in companies.json.
    Edit those files to tune behavior — this script should rarely need changes.

THREE-DIMENSIONAL FILTER:
    D1 — Title:       Role title contains a seniority signal + a clinical/R&D
                      domain pair. Some broad pairs require an additional
                      amplifier word to avoid false positives.
    D2 — Keywords:    Search cluster strings sent to Workday's searchText API.
                      Drives what the ATS returns before local filtering.
    D3 — Department:  Secondary match path. Surfaces roles with non-standard
                      titles that live in a clearly relevant department/team.

SCORING (0-20):
    Seniority level (0-5) + Title precision (0-7) + Cluster density (0-4)
    + Department alignment (0-2) + Company tier bonus (0-1)
    Roles are sorted highest score first in the output CSV.

KNOWN LIMITATIONS:
    - Scoring is based on job title and department only, not the full job
      description. A well-titled role in a weak dept scores higher than
      a generic title with a description full of target keywords. This is
      a known gap to address in a future iteration.
    - Workday tenant URLs in companies.json are best-guess patterns. Some
      may need correction after a live test run. See README.md for how to
      find the correct URL for a failing company.
    - Companies using SAP SuccessFactors, Taleo, iCIMS, or custom career
      pages are flagged for manual review. A separate scraper script is
      planned for these (see README.md).
================================================================================
"""

import requests   # HTTP library for making API calls to ATS systems
import json       # JSON parsing for config files and API responses
import csv        # Writing output results to CSV format
import os         # File and directory operations
import time       # Adding pauses between API requests
from datetime import datetime, date   # Timestamps for output filenames and logging


# ================================================================================
# RUNTIME CONFIGURATION
# These values control script behavior. Adjust REQUEST_TIMEOUT if you experience
# frequent timeouts on slow network connections. PAUSE_BETWEEN prevents hammering
# ATS servers with rapid-fire requests.
# ================================================================================

SEEN_FILE       = "seen_jobs.json"  # Persists job IDs across runs to suppress duplicates
OUTPUT_DIR      = "results"         # Folder where output CSVs are written
REQUEST_TIMEOUT = 12                # Seconds before a single HTTP request gives up
PAUSE_BETWEEN   = 0.5               # Seconds to wait between ATS requests per company

# Standard headers sent with every HTTP request.
# User-Agent mimics a browser to avoid being blocked by ATS bot filters.
HEADERS = {
    "Content-Type": "application/json",
    "Accept":       "application/json",
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


# ================================================================================
# CONFIG LOADERS
# Both config files are loaded fresh on each run, so edits take effect immediately
# without restarting anything.
# ================================================================================

def load_filters(path="filters.json"):
    """
    Load all three filter dimensions and scoring weights from filters.json.
    This file contains: D1 title rules, D2 search clusters, D3 department
    signals, and the full scoring configuration. Edit that file — not this
    script — to change search behavior.
    """
    with open(path) as f:
        return json.load(f)


def load_companies(path="companies.json"):
    """
    Load the target company list from companies.json.
    Each entry specifies the company name, tier, ATS type, and the API URL
    or board token needed to query that company's job feed.
    """
    with open(path) as f:
        return json.load(f)


# ================================================================================
# DIMENSION 1 — TITLE FILTER
# Primary match path. Checks whether a job title contains the right combination
# of seniority signal and clinical/R&D domain context.
# ================================================================================

def matches_title_d1(title: str, d1: dict) -> bool:
    """
    Returns True if the job title passes the D1 title filter.

    Rules (all must be satisfied):
      1. Title contains at least one seniority signal (director, vp, head of, etc.)
      2. Title does NOT contain any hard exclusion term (medical director, finance, etc.)
      3. Title contains at least one domain pair (clinical data, r&d platform, etc.)
         If the domain pair is flagged as "broad", an additional amplifier word
         must also be present to prevent false positives.

    All comparisons are case-insensitive.

    Args:
        title: The raw job title string from the ATS.
        d1:    The dimension1_title block from filters.json.

    Returns:
        True if the title passes all three rules, False otherwise.
    """
    t = title.lower()

    # Filter out comment/readme strings from config lists before matching.
    # domain_pairs and seniority may contain section headers ("--- X ---") or
    # readme notes ("_readme: ...") for human readability — skip those here.
    seniority_terms = [s for s in d1["seniority"]
                       if not s.startswith("_") and not s.startswith("---")]
    domain_pairs    = [p for p in d1["domain_pairs"]
                       if not p.startswith("_") and not p.startswith("---")]

    # Rule 1: Must have a seniority signal
    if not any(s in t for s in seniority_terms):
        return False

    # Rule 2: Must not contain any excluded term
    if any(e in t for e in d1["exclude_title"]):
        return False

    # Strip internal readme keys before processing broad_terms dict
    broad = {k: v for k, v in d1["broad_terms"].items() if not k.startswith("_")}

    # Rule 3: Must contain at least one domain pair
    # Broad pairs additionally require an amplifier word in the title
    for pair in domain_pairs:
        if pair in t:
            if pair in broad:
                # Broad pair — only counts if an amplifier is also present
                if any(amp in t for amp in broad[pair]):
                    return True
            else:
                # Specific pair — match is sufficient on its own
                return True

    return False


# ================================================================================
# DIMENSION 3 — DEPARTMENT FILTER
# Secondary match path used when D1 title match fails. Catches roles with generic
# titles (e.g., "Senior Director, Operations") that live inside a clearly relevant
# department or team (e.g., "Clinical Data Management").
# Note: D2 (search clusters) operates at the ATS query level — see fetch_workday().
# ================================================================================

def matches_department_d3(dept: str, d3_signals: list) -> bool:
    """
    Returns True if the department/team name contains a known relevant function label.

    This is a loose match — any substring match on a signal term qualifies.
    It is always used in conjunction with a seniority check in is_relevant()
    to prevent surfacing junior roles in relevant departments.

    Args:
        dept:       Department or team name string from the ATS.
        d3_signals: List of department signal strings from filters.json.

    Returns:
        True if any signal term appears in the department name, False otherwise.
    """
    if not dept:
        return False
    return any(sig in dept.lower() for sig in d3_signals)


def is_relevant(job: dict, d1: dict, d3_signals: list) -> bool:
    """
    Master relevance gate. A job passes if it matches via D1 OR D3 (with seniority).
    Hard exclusions from D1 always apply regardless of which path is used.

    Match paths:
      D1-title: Title contains seniority + domain pair (± amplifier)
      D3-dept:  Title contains seniority + department matches a known function label

    The match_path value is set by the caller after this function returns True,
    so downstream scoring and output labeling know which path was used.

    Args:
        job:        Normalized job dict (must have 'title' and 'department' keys).
        d1:         Dimension 1 config block from filters.json.
        d3_signals: Dimension 3 department signal list from filters.json.

    Returns:
        True if the job is relevant, False otherwise.
    """
    title = job.get("title", "")
    dept  = job.get("department", "")
    t     = title.lower()

    # Hard exclusions always apply — checked before either match path
    if any(e in t for e in d1["exclude_title"]):
        return False

    # Filter comment strings from seniority list before matching
    seniority_terms = [s for s in d1["seniority"]
                       if not s.startswith("_") and not s.startswith("---")]

    # Primary path: title match
    if matches_title_d1(title, d1):
        return True

    # Secondary path: department match + seniority signal in title
    if matches_department_d3(dept, d3_signals) and any(s in t for s in seniority_terms):
        return True

    return False


# ================================================================================
# SCORING
# Each matched job receives a numeric score (0-20) and a plain-language label.
# The score reflects how well the role aligns across five dimensions.
# Output CSV is sorted by score descending so strongest matches appear first.
#
# Score components (see filters.json scoring section for weight values):
#   A — Seniority:            How senior is the role? (0-5)
#   B — Title precision:      How closely does the title match a target archetype? (0-7)
#   C — Cluster density:      How many D2 search clusters returned this job? (0-4)
#                             Higher count = more keyword overlap with your vocabulary
#   D — Department alignment: Does the department name match a D3 signal? (0-2)
#   E — Tier bonus:           Small bonus for T1/T2 companies (0-1)
# ================================================================================

def score_job(job: dict, cluster_hits: int, scoring: dict) -> dict:
    """
    Scores a matched job and attaches score metadata to the job dict.

    Args:
        job:          Normalized job dict. Must have 'title', 'department',
                      'tier', 'match_path', and '_dept_match' keys set by caller.
        cluster_hits: Number of D2 search clusters that returned this job.
                      Populated by fetch_workday(). Defaults to 1 for
                      Greenhouse/Lever (which use a single broad pull).
        scoring:      The scoring block from filters.json.

    Returns:
        The job dict with 'score', 'match_label', and 'score_detail' added.
        score_detail is a pipe-separated string showing each component's
        contribution — useful for debugging and tuning the scoring model.
    """
    title  = job.get("title", "").lower()
    tier   = job.get("tier", "T3")
    score  = 0
    detail = []

    # ── A: Seniority (0-5) ────────────────────────────────────────────────────
    # Levels are evaluated top-to-bottom; first match wins.
    # Highest scores must come first in the levels list to prevent "director"
    # matching before "senior director". Structure in filters.json:
    #   seniority_levels.levels = [{"score": N, "aliases": [...]}, ...]
    sen = 0
    for level in scoring["seniority_levels"]["levels"]:
        if any(alias in title for alias in level["aliases"]):
            sen = level["score"]
            break
    score += sen
    detail.append(f"Seniority={sen}")

    # ── B: Title precision (0-7) ──────────────────────────────────────────────
    # High-precision pairs are near-exact matches to target archetypes.
    # Medium pairs match the archetype but with more generic language.
    # D3-only roles get a low score since the title itself wasn't informative.
    tp_cfg = scoring["title_precision"]
    if any(p in title for p in tp_cfg["high_precision_pairs"]):
        tp = tp_cfg["high_score"]
    elif any(p in title for p in tp_cfg["medium_precision_pairs"]):
        tp = tp_cfg["medium_score"]
    elif job.get("match_path") == "D3-dept":
        tp = tp_cfg["d3_only_score"]
    else:
        tp = 0
    score += tp
    detail.append(f"Title={tp}")

    # ── C: Cluster density (0-4) ──────────────────────────────────────────────
    # Counts how many of the 16 D2 search clusters returned this specific job.
    # A role appearing in 5+ clusters has deep keyword overlap with your profile.
    # Only meaningful for Workday results — Greenhouse/Lever get a flat score of 1.
    cd = min(cluster_hits, scoring["cluster_density"]["max_score"])
    score += cd
    detail.append(f"Clusters={cd}")

    # ── D: Department alignment (0-2) ─────────────────────────────────────────
    # Bonus if the department name independently confirms functional relevance.
    # "_dept_match" flag is set by the caller in the main loop.
    da = scoring["department_alignment"]["score"] if job.get("_dept_match") else 0
    score += da
    detail.append(f"Dept={da}")

    # ── E: Tier bonus (0-1) ───────────────────────────────────────────────────
    # Small bonus for T1/T2 companies. Kept deliberately small so company tier
    # doesn't override a weak fit signal at a large company.
    tb = scoring["tier_bonus"].get(tier, 0)
    score += tb
    detail.append(f"Tier={tb}")

    # ── Label ─────────────────────────────────────────────────────────────────
    # Thresholds are defined in filters.json and can be adjusted without code changes.
    thresh = scoring["label_thresholds"]
    labels = thresh["labels"]
    if score >= thresh["strong_min"]:       label = labels["strong"]
    elif score >= thresh["good_min"]:       label = labels["good"]
    elif score >= thresh["possible_min"]:   label = labels["possible"]
    else:                                   label = labels["weak"]

    job["score"]        = score
    job["match_label"]  = label
    job["score_detail"] = " | ".join(detail)
    return job


# ================================================================================
# ATS FETCHERS
# One function per ATS platform. Each returns a tuple of:
#   (list_of_raw_job_dicts, dict_of_job_id_to_cluster_hit_count)
#
# The cluster_hits dict is only populated by fetch_workday() since that's the
# only ATS where we run multiple targeted queries. Greenhouse and Lever return
# an empty dict — cluster_hits defaults to 1 for those jobs in the scoring step.
#
# fetch_manual() handles companies with no public API (SAP, Taleo, iCIMS, Direct).
# It logs the career page URL for manual review and returns empty results.
# A separate scraper script is planned for these companies.
# ================================================================================

def fetch_workday(company: dict, clusters: list) -> tuple:
    """
    Queries a Workday CXS API endpoint using each D2 search cluster as a
    separate search string. Deduplicates results by job ID and tracks how
    many clusters each job appeared in (cluster density for scoring).

    Workday's searchText parameter performs a full-text search across job title
    and description on Workday's side, so cluster queries pre-filter results
    before they reach our local filter. This is the D2 dimension in action.

    Pagination is handled automatically — loops until all pages are retrieved.
    A short pause between cluster queries prevents rate limiting.

    Args:
        company:  Company config dict from companies.json.
        clusters: List of D2 search cluster strings from filters.json.

    Returns:
        Tuple of (list of raw job dicts, dict of job_id -> cluster hit count).
    """
    url              = company["api_url"]
    job_cluster_hits = {}   # job_id -> number of clusters that returned this job
    all_raw          = {}   # job_id -> raw job dict (deduplication store)

    def _query(search_text: str, limit: int = 20) -> list:
        """
        Executes a single paginated Workday API query and returns all results.
        Handles pagination by incrementing offset until all pages are retrieved.
        """
        offset = 0
        batch  = []
        while True:
            body = {
                "appliedFacets": {},    # No facet filters — we filter locally
                "limit":         limit,
                "offset":        offset,
            }
            if search_text:            # omit searchText entirely when empty (some instances reject it)
                body["searchText"] = search_text
            try:
                r = requests.post(url, json=body, headers=HEADERS, timeout=REQUEST_TIMEOUT)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                # Log warning and stop paginating this cluster — don't crash the run
                print(f"    [WARN] {company['name']} ({search_text[:35]}...): {e}")
                break

            postings = data.get("jobPostings", [])
            batch.extend(postings)
            offset += limit

            # Stop when we've retrieved all available results
            if offset >= data.get("total", 0) or not postings:
                break

        return batch

    # Some Workday instances reject searchText in the POST body (returns 422).
    # For those companies, no_search_text=true is set in companies.json.
    # We pull all jobs in a single query and rely on local D1/D3 filtering.
    if company.get("no_search_text"):
        for raw in _query(""):
            jid = raw.get("bulletFields", [""])[0] or raw.get("title", "")
            if jid:
                all_raw[jid] = raw
                job_cluster_hits[jid] = 1   # no cluster density signal available
    else:
        # Run each search cluster and accumulate results
        for cluster in clusters:
            for raw in _query(cluster):
                # Workday job IDs are typically in bulletFields[0]
                jid = raw.get("bulletFields", [""])[0] or raw.get("title", "")
                if jid:
                    all_raw[jid] = raw                                         # deduplicate
                    job_cluster_hits[jid] = job_cluster_hits.get(jid, 0) + 1  # count hits

            time.sleep(PAUSE_BETWEEN)   # be polite between cluster queries

    return list(all_raw.values()), job_cluster_hits


def fetch_greenhouse(company: dict, clusters: list) -> tuple:
    """
    Queries the Greenhouse Jobs Board public API for all open positions.
    Returns the full job list — filtering happens locally via D1/D3.

    Greenhouse's API requires a board token (not a full URL). The token is
    typically visible in the URL when viewing jobs on the company's career page:
    https://boards.greenhouse.io/BOARD_TOKEN/jobs/12345

    The `content=true` parameter includes job description HTML in the response,
    which could support description-based scoring in a future iteration.

    Args:
        company:  Company config dict. Must have 'board_token' key.
        clusters: Not used — Greenhouse returns all jobs in one call.

    Returns:
        Tuple of (list of raw job dicts, empty dict).
    """
    token = company["board_token"]
    url   = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json().get("jobs", []), {}
    except Exception as e:
        print(f"    [WARN] {company['name']}: {e}")
        return [], {}


def fetch_lever(company: dict, clusters: list) -> tuple:
    """
    Queries the Lever Postings public API for all open positions.
    Returns the full job list — filtering happens locally via D1/D3.

    Lever's board token is the company slug visible in their career page URL:
    https://jobs.lever.co/BOARD_TOKEN/job-id

    Args:
        company:  Company config dict. Must have 'board_token' key.
        clusters: Not used — Lever returns all jobs in one call.

    Returns:
        Tuple of (list of raw job dicts, empty dict).
    """
    token = company["board_token"]
    url   = f"https://api.lever.co/v0/postings/{token}?mode=json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json(), {}
    except Exception as e:
        print(f"    [WARN] {company['name']}: {e}")
        return [], {}


def fetch_manual(company: dict, clusters: list) -> tuple:
    """
    Placeholder for companies without a public ATS API (SAP SuccessFactors,
    Oracle Taleo, iCIMS, and custom career pages).

    Logs the career page URL to the console for manual review. A separate
    scraper script is planned to automate these — see README.md.

    Args:
        company:  Company config dict. Should have 'career_url' key.
        clusters: Not used.

    Returns:
        Tuple of (empty list, empty dict) — no automated results.
    """
    print(f"    [MANUAL] Check manually: {company.get('career_url', '(no URL listed)')}")
    return [], {}


# Route each ATS type to its fetcher function.
# Companies with unsupported ATS types fall back to fetch_manual().
FETCHERS = {
    "workday":    fetch_workday,
    "greenhouse": fetch_greenhouse,
    "lever":      fetch_lever,
    "icims":      fetch_manual,
    "direct":     fetch_manual,
    "sap":        fetch_manual,
    "taleo":      fetch_manual,
}


# ================================================================================
# NORMALIZERS
# Each ATS returns job data in a different structure. Normalizers convert raw
# ATS-specific dicts into a consistent internal format used for filtering,
# scoring, and output.
#
# Internal format keys:
#   id         — Unique job identifier within this ATS
#   title      — Job title as posted
#   department — Team or department name (not always available)
#   location   — Location string as posted (used for remote filtering)
#   posted     — Date posted (ISO format where available)
#   url        — Direct link to the job posting
#   company    — Company name from companies.json
#   ats        — ATS platform name (for output reference)
#   tier       — Company tier from companies.json (T1-T4)
# ================================================================================

def normalize_workday(raw: dict, company: dict) -> dict:
    """
    Normalizes a raw Workday job posting dict.

    Notes:
    - Job ID lives in bulletFields[0] — this field name may vary across tenants.
      If it's empty, we fall back to the job title as an imperfect ID.
    - The apply URL is assembled from the company's career_url base and the
      job's externalPath. This may need adjustment if Workday URLs don't match.
    - Department is not returned in Workday's CXS list API — would require
      a second per-job fetch to retrieve. Left empty for now.
    """
    ext  = raw.get("externalPath", "")
    base = company.get("career_url", "").rstrip("/")
    return {
        "id":         raw.get("bulletFields", [""])[0] or raw.get("title", ""),
        "title":      raw.get("title", ""),
        "department": "",   # Not available in Workday list API response
        "location":   raw.get("locationsText", ""),
        "posted":     raw.get("postedOnDate", ""),
        "url":        f"{base}{ext}" if ext else base,
        "company":    company["name"],
        "ats":        "Workday",
        "tier":       company.get("tier", ""),
    }


def normalize_greenhouse(raw: dict, company: dict) -> dict:
    """
    Normalizes a raw Greenhouse job posting dict.

    Notes:
    - Greenhouse returns a departments array — we use the first entry's name.
    - Job ID is an integer in Greenhouse — converted to string for consistency.
    - updated_at is used as posted date (closest available proxy for post date).
    """
    depts = raw.get("departments", [{}])
    return {
        "id":         str(raw.get("id", "")),
        "title":      raw.get("title", ""),
        "department": depts[0].get("name", "") if depts else "",
        "location":   raw.get("location", {}).get("name", ""),
        "posted":     raw.get("updated_at", "")[:10],   # truncate to YYYY-MM-DD
        "url":        raw.get("absolute_url", ""),
        "company":    company["name"],
        "ats":        "Greenhouse",
        "tier":       company.get("tier", ""),
    }


def normalize_lever(raw: dict, company: dict) -> dict:
    """
    Normalizes a raw Lever job posting dict.

    Notes:
    - Lever stores department and location inside a nested 'categories' object.
    - createdAt is a Unix timestamp in milliseconds — converted to ISO date.
    """
    cats = raw.get("categories", {})
    return {
        "id":         raw.get("id", ""),
        "title":      raw.get("text", ""),
        "department": cats.get("department", ""),
        "location":   cats.get("location", ""),
        "posted":     str(date.fromtimestamp(raw["createdAt"] / 1000))
                      if raw.get("createdAt") else "",
        "url":        raw.get("hostedUrl", ""),
        "company":    company["name"],
        "ats":        "Lever",
        "tier":       company.get("tier", ""),
    }


# Route each ATS type to its normalizer function.
# ATS types without a normalizer (icims, sap, taleo, direct) return no raw data,
# so no normalizer is needed for them.
NORMALIZERS = {
    "workday":    normalize_workday,
    "greenhouse": normalize_greenhouse,
    "lever":      normalize_lever,
}


# ================================================================================
# SEEN-JOBS TRACKER
# Persists a set of job UIDs across runs so previously surfaced jobs are not
# shown again. UID format: "CompanyName::JobID"
#
# Important: Deleting seen_jobs.json will cause all currently open matching
# roles to surface again on the next run as if they were new.
# ================================================================================

def load_seen() -> set:
    """Load previously seen job UIDs from disk. Returns empty set on first run."""
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    """Persist the updated set of seen job UIDs to disk after each run."""
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f, indent=2)


# ================================================================================
# MAIN
# Orchestrates the full run: load configs → query each company → filter →
# score → deduplicate → write output CSV → print console summary.
# ================================================================================

def run():
    print(f"\n{'='*65}")
    print(f"  Job Monitor — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*65}\n")

    # Load all configuration
    filters    = load_filters()
    companies  = load_companies()
    seen       = load_seen()

    # Unpack filter dimensions from config
    d1         = filters["dimension1_title"]
    clusters   = filters["dimension2_search_clusters"]["clusters"]
    d3_signals = filters["dimension3_departments"]["signals"]
    scoring    = filters["scoring"]

    new_jobs   = []   # Accumulates matched jobs across all companies
    skipped    = 0    # Count of jobs suppressed because they were seen before
    manual_log = []   # Career page URLs for companies that need manual review

    # ── Query each company ─────────────────────────────────────────────────────
    for company in companies:
        ats        = company.get("ats", "direct").lower()
        fetcher    = FETCHERS.get(ats, fetch_manual)
        normalizer = NORMALIZERS.get(ats)

        print(f"  Checking {company['name']:38s} [{ats.upper()}]")

        # Companies with no ATS API — log URL and move on
        if not normalizer:
            manual_log.append(company.get("career_url", ""))
            fetcher(company, clusters)
            continue

        # Fetch raw jobs from this company's ATS
        raw_jobs, cluster_hits = fetcher(company, clusters)
        company_new = 0

        for raw in raw_jobs:
            job = normalizer(raw, company)
            uid = f"{company['name']}::{job['id']}"

            # Skip jobs already surfaced in a previous run
            if uid in seen:
                skipped += 1
                continue

            # Mark as seen regardless of relevance — prevents re-processing
            # on the next run even if the job didn't pass the filter this time
            seen.add(uid)

            # Apply three-dimensional relevance filter
            if not is_relevant(job, d1, d3_signals):
                continue

            # Record which match path was used (D1 title or D3 department)
            job["match_path"]  = "D1-title" if matches_title_d1(job["title"], d1) else "D3-dept"

            # Flag department match for use in scoring (avoids re-running the check)
            job["_dept_match"] = matches_department_d3(job.get("department", ""), d3_signals)

            # Score the job — cluster_hits defaults to 1 for non-Workday ATS
            hits = cluster_hits.get(job["id"], 1)
            job  = score_job(job, hits, scoring)

            new_jobs.append(job)
            company_new += 1

        if company_new:
            print(f"    → {company_new} new role(s) found")

        time.sleep(PAUSE_BETWEEN)   # brief pause between companies

    # Persist updated seen-job list to disk
    save_seen(seen)

    # ── Write output CSV ───────────────────────────────────────────────────────
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    today    = date.today().isoformat()
    out_path = os.path.join(OUTPUT_DIR, f"new_jobs_{today}.csv")

    # Sort by score descending so strongest matches appear first
    new_jobs.sort(key=lambda x: (-x["score"], x["tier"], x["company"]))

    if new_jobs:
        # Output columns — _dept_match is internal only, excluded from CSV
        fields = ["score", "match_label", "tier", "company", "title",
                  "department", "location", "posted", "match_path",
                  "score_detail", "url", "ats"]

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(new_jobs)

        print(f"\n{'='*65}")
        print(f"  RESULTS: {len(new_jobs)} new role(s)  →  {out_path}")
        print(f"  Skipped {skipped} previously seen roles")
        print(f"{'='*65}\n")

        # Console summary — one line per match, sorted by score
        print(f"  {'Scr':>4}  {'Label':12}  {'Company':28}  Title")
        print(f"  {'---':>4}  {'-'*12}  {'-'*28}  {'-'*40}")
        for j in new_jobs:
            print(f"  {j['score']:>3}/20  {j['match_label']:12}  "
                  f"{j['company']:28}  {j['title']}")
    else:
        print(f"\n  No new relevant roles found. ({skipped} previously seen skipped)")

    # ── Manual review reminder ─────────────────────────────────────────────────
    if manual_log:
        print(f"\n  ── Manual checks needed ({len(manual_log)} companies) ──")
        for url in [u for u in manual_log if u]:
            print(f"    {url}")
        print(f"  See README.md for manual review guidance.\n")


# Entry point — only runs when script is called directly (not when imported)
if __name__ == "__main__":
    run()
