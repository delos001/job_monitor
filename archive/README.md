# Job Monitor — Setup & Usage Guide

## What this does
Queries ATS job feeds (Workday, Greenhouse, Lever) across your 71-company target list.
Surfaces only **new** director-level roles in clinical data, digital transformation, analytics,
and platform engineering. Skips roles already seen in previous runs. Outputs a CSV you can
review and import into your tracker.

---

## Setup (one-time, ~2 minutes)

### 1. Install Python 3.8+
Check if you have it: `python --version`
Download if needed: https://www.python.org/downloads/

### 2. Install the one dependency
```bash
pip install requests
```

### 3. Put these files in a folder (e.g., `JobMonitor/`)
```
JobMonitor/
  job_monitor.py
  companies.json
```

---

## Running the monitor

```bash
cd JobMonitor
python job_monitor.py
```

### What happens:
1. Queries each company's ATS feed
2. Filters for director-level roles in your target areas
3. Skips anything you've already seen (tracked in `seen_jobs.json`)
4. Writes new roles to `results/new_jobs_YYYY-MM-DD.csv`
5. Prints a summary to the console

---

## Output columns (CSV)
| Column | Description |
|---|---|
| company | Company name |
| tier | T1/T2/T3/T4 from target list |
| title | Job title |
| location | Location as listed in the posting |
| posted | Date posted (where available) |
| url | Direct link to the job posting |
| ats | Which ATS system it came from |

---

## How often to run
- **Priority 5 companies** (Roche, Merck, Pfizer, Veeva, Medidata, etc.): Weekly
- **All others**: Every 2 weeks
- A simple approach: run it every Monday morning

---

## Handling results

### First run
The first run will surface ALL currently open roles matching your filters — could be 30-100+.
That's expected and useful: gives you a baseline of what's currently open.
After that, only new postings appear.

### False positives
If a role surfaces that clearly isn't relevant, you don't need to do anything special —
the seen_jobs.json will prevent it from appearing again.

### If you want to re-scan everything (reset)
Delete `seen_jobs.json` and re-run. All roles will surface again as if for the first time.

---

## Fixing broken Workday URLs (most common issue)

Workday tenant names sometimes differ from what's in companies.json.
If you see an error like `404` or `connection refused` for a company:

1. Go to the company's career page in your browser
2. Click on any job posting — note the URL pattern
3. It will look like: `https://COMPANY.wd3.myworkdayjobs.com/SITENAME/job/...`
4. Update `companies.json` with the correct tenant and site name:
   - `"api_url": "https://COMPANY.wd3.myworkdayjobs.com/wday/cxs/COMPANY/SITENAME/jobs"`

---

## Companies that need manual checking (no public API)

These appear in companies.json but the script will skip them with a message:

| Company | ATS | Manual URL |
|---|---|---|
| Boehringer Ingelheim | SAP SuccessFactors | https://www.boehringer-ingelheim.com/careers |
| Bayer (Pharma Div.) | SAP SuccessFactors | https://career.bayer.com |
| UCB | SAP SuccessFactors | https://www.ucb.com/careers |
| Oracle Health Sciences | Taleo | https://www.oracle.com/careers |
| Eisai | Taleo | https://us.eisai.com/careers |
| Covance (Labcorp) | Taleo | https://careers.labcorp.com |
| Medpace | iCIMS | https://www.medpace.com/careers |
| Ergomed | Direct | https://ergomed.com/careers |
| Cytel | Direct | https://www.cytel.com/careers |

**Recommendation**: Bookmark these 9 URLs in a browser folder called "Manual Checks"
and scan them on the same schedule as the script.

---

## Adding a new company

Add a block to `companies.json`:

**For Workday:**
```json
{
  "name": "Company Name",
  "tier": "T2",
  "ats": "workday",
  "api_url": "https://TENANT.wd1.myworkdayjobs.com/wday/cxs/TENANT/SITENAME/jobs",
  "career_url": "https://careers.company.com"
}
```

**For Greenhouse:**
```json
{
  "name": "Company Name",
  "tier": "T2",
  "ats": "greenhouse",
  "board_token": "companytoken",
  "career_url": "https://careers.company.com"
}
```
Find the board token in the URL when you click "Apply" on their career page:
`https://boards.greenhouse.io/BOARD_TOKEN/jobs/12345`

---

## Adjusting the keyword filters

Edit `job_monitor.py` near the top:

- **`INCLUDE_TITLE`** — seniority signals required in job title
- **`SCOPE_TERMS`** — at least one must appear in title (controls relevance)
- **`EXCLUDE_TITLE`** — any match here drops the role

If you're getting too many false positives, tighten `SCOPE_TERMS`.
If you're missing relevant roles, loosen `INCLUDE_TITLE` or add terms to `SCOPE_TERMS`.
