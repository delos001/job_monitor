"""
diagnose_workday_urls.py
------------------------
Probes different URL path structures for vhr-hosted Workday tenants.
The previous diagnostic confirmed the body format isn't the issue — the URL is.

Run with:  python diagnose_workday_urls.py
"""

import requests
import json

HEADERS = {
    "Content-Type": "application/json",
    "Accept":       "application/json",
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

BODY = {"limit": 20, "offset": 0}

# Known good job URL patterns (from actual postings):
#   Jazz:   https://vhr-jazz.wd1.myworkdayjobs.com/JazzPharmaceuticals/job/...
#   Otsuka: https://vhr-otsuka.wd1.myworkdayjobs.com/en-US/External/details/...

TARGETS = {
    "Jazz": {
        "host": "vhr-jazz.wd1.myworkdayjobs.com",
        "urls": [
            # Standard CXS path variants — different tenant slug in the path
            "https://vhr-jazz.wd1.myworkdayjobs.com/wday/cxs/vhr-jazz/JazzPharmaceuticals/jobs",
            "https://vhr-jazz.wd1.myworkdayjobs.com/wday/cxs/jazz/JazzPharmaceuticals/jobs",
            "https://vhr-jazz.wd1.myworkdayjobs.com/wday/cxs/JazzPharmaceuticals/JazzPharmaceuticals/jobs",
            # With locale prefix
            "https://vhr-jazz.wd1.myworkdayjobs.com/wday/cxs/vhr-jazz/en-US/JazzPharmaceuticals/jobs",
            # Drop the site name segment
            "https://vhr-jazz.wd1.myworkdayjobs.com/wday/cxs/vhr-jazz/jobs",
            # Different wd numbers
            "https://vhr-jazz.wd3.myworkdayjobs.com/wday/cxs/vhr-jazz/JazzPharmaceuticals/jobs",
            "https://vhr-jazz.wd5.myworkdayjobs.com/wday/cxs/vhr-jazz/JazzPharmaceuticals/jobs",
            # vhr shared tenant path
            "https://vhr-jazz.wd1.myworkdayjobs.com/wday/cxs/vhr/JazzPharmaceuticals/jobs",
        ]
    },
    "Otsuka": {
        "host": "vhr-otsuka.wd1.myworkdayjobs.com",
        "urls": [
            # Standard CXS path variants
            "https://vhr-otsuka.wd1.myworkdayjobs.com/wday/cxs/vhr-otsuka/External/jobs",
            "https://vhr-otsuka.wd1.myworkdayjobs.com/wday/cxs/otsuka/External/jobs",
            # Otsuka job URL had en-US prefix — try that in the API path
            "https://vhr-otsuka.wd1.myworkdayjobs.com/wday/cxs/vhr-otsuka/en-US/External/jobs",
            "https://vhr-otsuka.wd1.myworkdayjobs.com/wday/cxs/en-US/External/jobs",
            # Drop the site name segment
            "https://vhr-otsuka.wd1.myworkdayjobs.com/wday/cxs/vhr-otsuka/jobs",
            # Different wd numbers
            "https://vhr-otsuka.wd3.myworkdayjobs.com/wday/cxs/vhr-otsuka/External/jobs",
            "https://vhr-otsuka.wd5.myworkdayjobs.com/wday/cxs/vhr-otsuka/External/jobs",
            # vhr shared tenant path
            "https://vhr-otsuka.wd1.myworkdayjobs.com/wday/cxs/vhr/External/jobs",
        ]
    },
}

def probe(company, info):
    print(f"\n{'='*65}")
    print(f"  {company}")
    print(f"{'='*65}")
    for url in info["urls"]:
        try:
            r = requests.post(url, json=BODY, headers=HEADERS, timeout=10)
            status = r.status_code
            snippet = ""
            if status == 200:
                data = r.json()
                total = data.get("total", "?")
                snippet = f"  ← total={total}  ✓ WORKING"
            print(f"  [{status}]  {url}{snippet}")
            if status == 200:
                print(f"\n  CORRECT API URL: {url}\n")
                return url
        except Exception as e:
            print(f"  [ERR]  {url}  → {e}")
    print(f"\n  ✗ No working URL found for {company}.")
    return None

if __name__ == "__main__":
    for company, info in TARGETS.items():
        probe(company, info)
    print("\nDone. Paste output back to Claude.\n")
