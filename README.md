# Job Monitor

A Python script that queries ATS job feeds (Workday, Greenhouse, Lever) across a configurable list of target companies, filters results through a three-dimensional relevance framework, scores each match, and outputs a ranked CSV of new roles. Only roles not seen in previous runs are surfaced, so repeated runs produce only genuinely new postings.

The included configuration targets director-level roles in clinical data, R&D digital transformation, analytics, and platform engineering at pharma, biotech, and CRO companies. Everything about the search — the company list, the keyword filters, and the scoring weights — is controlled by two JSON files. No changes to the Python script are needed to adapt it to a different target profile.

---

## Table of contents

1. [How it works](#how-it-works)
2. [Files overview](#files-overview)
3. [Setup](#setup)
4. [Customizing for your search](#customizing-for-your-search)
   - [Building companies.json](#building-companiesjson)
   - [Building filters.json](#building-filtersjson)
5. [Running the monitor](#running-the-monitor)
6. [Output](#output)
7. [Handling results](#handling-results)
8. [Troubleshooting Workday URLs](#troubleshooting-workday-urls)
9. [Companies that require manual checking](#companies-that-require-manual-checking)
10. [Adding companies](#adding-companies)

---

## How it works

Each run applies three dimensions of filtering before scoring results.

**Dimension 1 — Title filter (D1).** A role must have a seniority signal in the title (e.g., Director, Senior Director, Head of) AND at least one domain pair from your target list (e.g., "clinical data strategy", "digital transformation"). Some domain pairs are flagged as broad and require an additional amplifier word to pass — for example, "clinical operations" alone would produce too many false positives, so it only passes if the title also contains a word like "excellence", "technology", or "transformation". Hard exclusion terms (e.g., "regulatory", "finance", "medical director") block a role regardless of other signals.

**Dimension 2 — Search clusters (D2).** For Workday companies, each cluster string in `filters.json` is submitted as a separate full-text search query to the Workday API before local filtering runs. This controls which roles are returned by the ATS in the first place. Running each cluster as an independent query also produces a cluster density count per role — a role appearing in five clusters has deeper keyword overlap with your target profile than a role appearing in one.

**Dimension 3 — Department filter (D3).** A secondary match path for roles with generic titles that live inside a clearly relevant department. A "Senior Director, Operations" would normally fail D1, but if its department is tagged "Clinical Data Management" it passes via D3. A seniority signal in the title is still required for D3 matches.

**Scoring (0–20).** Matched roles receive a composite score:

| Component | Max | Source |
|---|---|---|
| Seniority level | 5 | Title: Senior Director=5, Director/Head=4, Executive Director=3, Associate Director=2 |
| Title precision | 7 | How closely the title maps to a defined target archetype |
| Cluster density | 4 | How many D2 search clusters returned this role (Workday only) |
| Department alignment | 2 | Whether the department matches a D3 signal |
| Company tier bonus | 1 | T1 and T2 companies receive a small bonus |

Roles are labeled **Strong** (≥15), **Good** (≥11), **Possible** (≥7), or **Weak** (<7) and sorted highest score first in the CSV output. All thresholds are configurable in `filters.json`.

---

## Files overview

```
job_monitor.py      — Main script. No edits needed for normal use.
companies.json      — Target company list: name, tier, ATS type, API URL or board token.
filters.json        — All filter logic and scoring weights. Edit this to tune search behavior.
seen_jobs.json      — Auto-generated. Tracks all job IDs surfaced across runs.
results/            — Auto-generated. Output CSVs written here after each run.
```

---

## Setup

### 1. Install Python 3.8 or later

Check your current version:
```bash
python --version
```
Download if needed: https://www.python.org/downloads/

### 2. Install the one dependency

```bash
pip install requests
```

### 3. Place these files in a folder

```
JobMonitor/
  job_monitor.py
  companies.json
  filters.json
```

The `results/` directory and `seen_jobs.json` are created automatically on the first run.

---

## Customizing for your search

The two JSON files define your search entirely. Before running, you should verify that `companies.json` contains the companies you want to monitor and that `filters.json` reflects your target role profile. The sections below explain each file and include prompt templates you can use with an LLM to generate starting content.

---

### Building companies.json

`companies.json` is an array of company objects. Each object specifies how to reach that company's ATS. The structure varies by ATS type.

**Object fields:**

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Display name used in output |
| `tier` | Yes | Priority grouping: T1 (large established), T2 (mid-size / growth), T3 (CRO / service), T4 (tech / platform) |
| `ats` | Yes | ATS type: `workday`, `greenhouse`, `lever`, `direct`, `sap`, `taleo`, `icims` |
| `api_url` | Workday only | CXS API endpoint URL |
| `board_token` | Greenhouse / Lever only | Board identifier from the company's career page URL |
| `career_url` | Yes | Human-readable career page URL (used for manual checks and as a URL base) |
| `notes` | Optional | Reason a company is flagged for manual check |
| `no_search_text` | Optional (Workday) | Set to `true` if the Workday tenant rejects `searchText` in the POST body and returns 422 errors |

**Tier definitions used in the included file:**

- T1 — Large established pharma/biotech (AstraZeneca, Pfizer, Roche, etc.)
- T2 — Mid-size or high-growth biotech (Regeneron, Moderna, Vertex, etc.)
- T3 — CRO and clinical service organizations (IQVIA, Parexel, ICON, etc.)
- T4 — Clinical technology and data platforms (Veeva, Medidata, Databricks, etc.)

Tier only affects scoring by a 1-point bonus for T1 and T2. It does not affect whether a role is surfaced.

#### Prompt to generate a company list

Use this prompt with an LLM to generate an initial `companies.json` array for your target industry. The output will require verification — ATS types and especially Workday URLs often need to be confirmed against live postings before they will work. See [Troubleshooting Workday URLs](#troubleshooting-workday-urls) for how to do that verification.

```
I'm building a job monitoring script that queries ATS job feeds. I need to populate 
a companies.json file with a list of target companies.

My target industry: [e.g., pharmaceutical, biotech, CRO, clinical technology]
My target function: [e.g., director-level roles in clinical data and digital transformation]
Approximate number of companies: [e.g., 50–75]

For each company, return a JSON object with these fields:
  - "name": company display name
  - "tier": priority grouping — use T1 for the largest companies in this space, 
    T2 for mid-size, T3 for service/CRO organizations, T4 for technology platforms
  - "ats": which ATS they use — options are "workday", "greenhouse", "lever", 
    "sap" (SAP SuccessFactors), "taleo", "icims", or "direct" (custom/unknown)
  - "api_url": for Workday companies, the CXS endpoint in the format:
    https://[tenant].wd[version].myworkdayjobs.com/wday/cxs/[tenant]/[sitename]/jobs
  - "board_token": for Greenhouse companies, the token from 
    https://boards.greenhouse.io/[token]/jobs/
    For Lever companies, the slug from https://jobs.lever.co/[slug]/
  - "career_url": the company's main career page URL
  - "notes": if the ATS is "direct", "sap", "taleo", or "icims", add a brief note 
    explaining why (e.g., "SAP SuccessFactors — check manually")

Return a valid JSON array. Flag any Workday api_url values you are uncertain about — 
Workday tenant slugs and site names vary and often need to be verified against a live 
job posting URL from that company.

Company list: [paste your company list here, or ask it to generate one]
```

**Important:** Workday API URLs generated by an LLM are best guesses and will frequently be wrong. Every Workday entry should be tested on a live run, and any company returning a 404 or 422 error needs its URL corrected manually. See [Troubleshooting Workday URLs](#troubleshooting-workday-urls) for the verification process. A company that cannot be fixed should have its `"ats"` changed to `"direct"` and be added to the manual check list.

---

### Building filters.json

`filters.json` controls all filter logic. No changes to `job_monitor.py` are needed — edit this file to change what gets surfaced and how it is scored. The file has four sections.

---

#### Dimension 1 — Title filter (`dimension1_title`)

The most important section. Controls which role titles pass. Contains four sub-fields:

- **`seniority`** — List of title strings that count as a seniority signal. Any match passes the gate. Order does not affect filtering (order only matters in the `scoring.seniority_levels` block).
- **`domain_pairs`** — List of functional keyword phrases. A title must contain at least one to pass. Grouped by theme with section comments for readability. A title containing a phrase in `broad_terms` requires an additional amplifier word (see below).
- **`broad_terms`** — A dict of domain pairs that are too generic on their own. Each key is a domain pair, and its value is a list of amplifier words. Both the pair and at least one amplifier must appear in the title. Example: "clinical operations" only passes if the title also contains "excellence", "technology", "transformation", etc.
- **`exclude_title`** — Terms that disqualify a role regardless of other matches. Used to block adjacent functions like regulatory, commercial, finance, and HR that share seniority and domain vocabulary with your target roles.

##### Prompt for domain pairs and broad terms

Tailor this to your specific target function.

```
I'm configuring a job search filter that matches director-level roles by job title.
I need two lists:

1. DOMAIN PAIRS: multi-word phrases that, combined with a seniority word, indicate 
   a relevant role. These should be specific enough to be meaningful but common 
   enough to appear in actual job titles.
   
   My target role areas: [describe your function — e.g., clinical data management, 
   R&D digital transformation, data science, analytics, process excellence, 
   technology strategy in biopharma]

2. BROAD TERMS: a subset of the domain pairs that are too generic on their own and 
   need a qualifying word (amplifier) to avoid false positives. For each broad term, 
   provide a list of amplifier words that make it specific enough to include.
   
   Example format:
   "clinical operations": ["data", "digital", "technology", "transformation", "excellence"]

Return the domain pairs as a flat JSON array of lowercase strings.
Return the broad terms as a JSON object where each key is a broad pair and each value 
is an array of amplifier strings.

Also return a list of EXCLUDE TERMS — job title substrings that should disqualify 
a role even if it matches on seniority and domain. Include functions adjacent to 
my target area that I want to filter out: [list your exclusions — e.g., regulatory, 
commercial, sales, finance, HR, biostatistics, medical director].
```

##### Prompt for seniority terms

The seniority list in the included `filters.json` is broadly applicable, but you may need to add or remove levels depending on your target seniority band.

```
I'm building a title filter for a job search. I need a list of all word patterns 
that signal a specific seniority level, accounting for abbreviations and variations.

Target seniority levels: [e.g., Associate Director through Senior Director]

For each level, give me all common variants and abbreviations (e.g., "sr director", 
"sr dir", "senior director" would all be variants of the same level).

Return as a flat JSON array of lowercase strings. Include all variants — the filter 
checks whether any string in the list appears as a substring in the job title.
```

---

#### Dimension 2 — Search clusters (`dimension2_search_clusters`)

A list of keyword strings sent to Workday's `searchText` API parameter. Each cluster is a separate API call, so the number of clusters directly affects run time. The current default is 8 clusters, producing an estimated run time of 8–10 minutes across 35 Workday companies.

Workday matches the individual words in a cluster string across job title and description — it is not an exact phrase search. Clusters should be written as space-separated keyword combinations, not quoted phrases.

Each job that passes through local filtering also receives a cluster density score based on how many clusters returned it. A role appearing in multiple clusters has more vocabulary overlap with your target profile and scores higher.

##### Prompt for search clusters

```
I'm configuring full-text search queries for Workday's job search API. The API 
takes a "searchText" string and matches the individual words across job titles 
and descriptions — it is not an exact phrase match.

I want to surface director-level roles in the following areas:
[describe your target function — e.g., clinical data strategy, R&D digital 
transformation, data platform architecture, process excellence, AI/ML integration 
in clinical development]

Generate 6–12 search cluster strings. Each string should be a group of 3–6 
space-separated keywords that together describe a specific sub-area of my target 
function. Avoid redundant overlap between clusters — each should cover meaningfully 
distinct vocabulary.

Return as a JSON array of strings.

The goal is breadth of coverage across my target areas, not depth in any one area. 
Fewer, well-differentiated clusters are better than many overlapping ones.
```

Note: reducing cluster count cuts run time proportionally. Going from 16 to 8 clusters cuts run time approximately in half with modest coverage loss if clusters are selected to minimize overlap.

---

#### Dimension 3 — Department signals (`dimension3_departments`)

A list of department or team name substrings. A role with a generic title that would otherwise fail D1 can still pass if its department matches one of these signals. The Workday CXS list API does not return department information — this dimension is only effective for Greenhouse and Lever results, where department is included in the job feed.

##### Prompt for department signals

```
I'm building a secondary filter that catches relevant roles based on their 
department or team name rather than their job title. This is needed because 
some companies use generic titles like "Senior Director, Operations" for 
roles that actually sit inside a relevant function.

My target function areas: [describe your function]
Industry: [e.g., pharma, biotech, CRO]

Generate a list of department and team name substrings that would indicate 
a role inside my target function. Include variations in naming conventions 
(e.g., "data & analytics", "data and analytics").

Prioritize specificity — these should be department names that are clearly 
inside my target function and unlikely to appear in irrelevant departments. 
Avoid terms so broad they would match across the whole company.

Return as a JSON array of lowercase strings.
```

---

#### Scoring (`scoring`)

Controls how matched roles are ranked. All weights are configurable without code changes.

- **`seniority_levels`** — Maps seniority aliases to numeric scores. Evaluated top-to-bottom; first match wins. Compound forms (e.g., "associate director", "executive director") must appear before the bare word "director" in the levels list to prevent the substring from matching at the wrong score.
- **`title_precision`** — Two tiers of precision: `high_precision_pairs` (exact archetype match, 7 points) and `medium_precision_pairs` (partial archetype match, 4 points). D3-only matches receive a flat 2 points since the title itself was not informative.
- **`cluster_density`** — Points capped at `max_score` (default 4). A role appearing in all 8 clusters receives the same 4 points as one appearing in 4 clusters — the cap prevents cluster density from dominating the score.
- **`department_alignment`** — Flat 2-point bonus for department signal match.
- **`tier_bonus`** — 1-point bonus for T1 and T2 companies. Intentionally small so tier does not override a weak fit signal.
- **`label_thresholds`** — Score cutoffs for Strong / Good / Possible / Weak labels. Adjust these if you find the labels are not calibrated to your results in practice.

---

## Running the monitor

```bash
cd JobMonitor
python job_monitor.py
```

The script prints a progress line for each company and a summary table of new roles at the end.

**Expected run time: approximately 8–10 minutes** for the default configuration (35 Workday companies × 8 search clusters, with 0.5-second pauses between requests).

---

## Output

Results are written to `results/new_jobs_YYYY-MM-DD.csv`, sorted by score descending.

| Column | Description |
|---|---|
| `score` | Match score 0–20 |
| `match_label` | Strong / Good / Possible / Weak |
| `tier` | T1/T2/T3/T4 |
| `company` | Company name |
| `title` | Job title as posted |
| `department` | Department/team name. Available for Greenhouse and Lever; empty for Workday. |
| `location` | Location as posted |
| `posted` | Date posted where available |
| `match_path` | `D1-title` (matched via title) or `D3-dept` (matched via department) |
| `score_detail` | Pipe-separated breakdown: `Seniority=N | Title=N | Clusters=N | Dept=N | Tier=N` |
| `url` | Direct link to the job posting |
| `ats` | ATS platform the role came from |

---

## Handling results

**First run.** The first run surfaces all currently open matching roles — potentially 30–100+ depending on market conditions. This is expected. It gives you a baseline of what is currently posted. On subsequent runs, only newly posted roles appear.

**False positives.** No action needed. `seen_jobs.json` records every job ID that has been processed, whether it passed the filter or not. A role that surfaced but was not relevant will not appear again.

**Resetting.** Delete `seen_jobs.json` and re-run. All matching roles will surface again as if for the first time.

**seen_jobs.json format.** The file maps job UIDs to job titles for human readability:
```json
{
  "AstraZeneca::R-12345": "Director, Clinical Data Strategy",
  "Pfizer::P-98765": "Senior Director, R&D Digital Transformation"
}
```
UID format is `CompanyName::JobID`. Do not delete this file between normal runs.

If you have a `seen_jobs.json` from an earlier version of the script that stored UIDs as a plain list rather than a dict, it will be automatically migrated to the current format on the next run. Titles for migrated entries will be blank.

---

## Troubleshooting Workday URLs

Workday API URLs are the most common failure point. The `api_url` in `companies.json` must match the company's actual Workday tenant configuration exactly. Small differences in tenant slug, site name, or version number cause 404 or 422 errors.

**Structure of a valid Workday CXS API URL:**
```
https://[tenant].[wd-version].myworkdayjobs.com/wday/cxs/[tenant]/[sitename]/jobs
```

Example: `https://pfizer.wd1.myworkdayjobs.com/wday/cxs/pfizer/PfizerCareers/jobs`

| Segment | What it is | How to find it |
|---|---|---|
| `[tenant]` | Company's Workday tenant slug | From any live job posting URL for that company |
| `[wd-version]` | Workday version number (wd1, wd3, wd5, wd12, wd501) | From any live job posting URL |
| `[sitename]` | Career site name within the tenant | From the path segment in a live job posting URL |

**To find the correct URL for a failing company:**

1. Go to the company's careers page in a browser
2. Click on any open job posting
3. The posting URL will follow this pattern: `https://[tenant].wd[N].myworkdayjobs.com/[sitename]/job/...`
4. Extract the tenant, version number, and sitename
5. Update `companies.json`:
   ```json
   "api_url": "https://[tenant].wd[N].myworkdayjobs.com/wday/cxs/[tenant]/[sitename]/jobs"
   ```

**404 errors** indicate a wrong tenant slug, wrong version number, or wrong sitename.

**422 errors** indicate one of two things:
- The URL segments are wrong (same fix as 404)
- The Workday tenant rejects the `searchText` field in the POST body. In this case, add `"no_search_text": true` to the company's entry in `companies.json`. The script will then pull all jobs in a single query and rely on local filtering only.
- The tenant is hosted by a third-party provider (e.g., `vhr-`) and blocks unauthenticated API access entirely. In that case, URL corrections will not resolve the 422. Change `"ats"` to `"direct"` and check the company manually.

---

## Companies that require manual checking

These companies use ATS platforms without a public API (SAP SuccessFactors, Taleo, iCIMS), have custom career pages, or have Workday tenants that block API access. The script will print their career page URLs to the console and skip them. Check them directly on the same cadence as the script runs.

| Company | ATS | Career Page |
|---|---|---|
| AbbVie | Workday (API blocked) | https://careers.abbvie.com |
| Boehringer Ingelheim | SAP SuccessFactors | https://www.boehringer-ingelheim.com/careers |
| Bayer (Pharma Div.) | SAP SuccessFactors | https://career.bayer.com |
| Astellas Pharma | Avature | https://astellas.avature.net/en_GB/careers |
| BioNTech | Custom | https://jobs.biontech.com |
| Alnylam Pharmaceuticals | iCIMS | https://opportunities.alnylam.com |
| Incyte Corporation | Direct | https://careers.incyte.com/jobs |
| Ionis Pharmaceuticals | Direct | https://ionis.com/careers/ |
| UCB | SAP SuccessFactors | https://www.ucb.com/careers |
| Jazz Pharmaceuticals | Workday (API blocked) | https://careers.jazzpharma.com |
| Otsuka Pharmaceutical | Workday (API blocked) | https://www.otsuka.us/careers |
| Eisai | Taleo | https://us.eisai.com/careers |
| Teva Pharmaceuticals | Direct | https://careers.teva/ |
| Alkermes | Direct | https://careers.alkermes.com/ |
| Nuvation Bio | Direct | https://nuvationbio.com/careers/ |
| Medpace | iCIMS | https://www.medpace.com/careers |
| Ergomed | Direct | https://ergomed.com/careers |
| Covance (Labcorp) | Taleo | https://careers.labcorp.com |
| Medidata (Dassault) | Direct | https://www.3ds.com/careers/jobs |
| Oracle Health Sciences | Taleo | https://www.oracle.com/careers |
| Certara | iCIMS | https://careers.certara.com |
| Cytel | Direct | https://www.cytel.com/careers |

Bookmarking these 22 URLs in a dedicated browser folder makes the manual sweep easier to complete on a consistent cadence.

---

## Adding companies

Add a new object to `companies.json`. Examples for each supported ATS type:

**Workday:**
```json
{
  "name": "Company Name",
  "tier": "T2",
  "ats": "workday",
  "api_url": "https://TENANT.wd1.myworkdayjobs.com/wday/cxs/TENANT/SITENAME/jobs",
  "career_url": "https://careers.company.com"
}
```
Verify the `api_url` against a live job posting before relying on it. See [Troubleshooting Workday URLs](#troubleshooting-workday-urls).

**Greenhouse:**
```json
{
  "name": "Company Name",
  "tier": "T2",
  "ats": "greenhouse",
  "board_token": "companytoken",
  "career_url": "https://careers.company.com"
}
```
Find the board token in the URL when clicking Apply on a job: `https://boards.greenhouse.io/BOARD_TOKEN/jobs/12345`

**Lever:**
```json
{
  "name": "Company Name",
  "tier": "T2",
  "ats": "lever",
  "board_token": "companyslug",
  "career_url": "https://jobs.lever.co/companyslug"
}
```
The board token is the company slug in the Lever career page URL: `https://jobs.lever.co/BOARD_TOKEN/`

**Manual check only (SAP SuccessFactors, Taleo, iCIMS, or blocked Workday):**
```json
{
  "name": "Company Name",
  "tier": "T2",
  "ats": "direct",
  "career_url": "https://careers.company.com",
  "notes": "Reason — e.g., SAP SuccessFactors, check manually"
}
```

---

## Known limitations

- Scoring is based on job title and department only, not the full job description. A role with a well-matched title but a weak description scores identically to one with a well-matched title and a strong description. Full description scoring is a known future improvement.
- Workday's CXS list API does not return department information, so D3 department matching and the department alignment score are only available for Greenhouse and Lever results.
- Workday tenant URLs in `companies.json` were verified at build time. Companies occasionally restructure their Workday instances, which can cause previously working URLs to break. If a company that was working starts returning errors, re-verify its URL against a current live posting.
