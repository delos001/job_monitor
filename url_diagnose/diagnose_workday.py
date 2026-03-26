"""
diagnose_workday.py
-------------------
Probes Jazz and Otsuka Workday endpoints with progressively stripped-down
request bodies to find the minimal format they accept.

Run with:  python diagnose_workday.py
"""

import requests
import json

HEADERS_FULL = {
    "Content-Type": "application/json",
    "Accept":       "application/json",
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

HEADERS_MINIMAL = {
    "Content-Type": "application/json",
    "Accept":       "application/json",
}

ENDPOINTS = {
    "Jazz":   "https://vhr-jazz.wd1.myworkdayjobs.com/wday/cxs/vhr-jazz/JazzPharmaceuticals/jobs",
    "Otsuka": "https://vhr-otsuka.wd1.myworkdayjobs.com/wday/cxs/vhr-otsuka/External/jobs",
}

CANDIDATES = [
    ("Empty body",                   {}),
    ("limit+offset only",            {"limit": 20, "offset": 0}),
    ("limit+offset+empty facets",    {"limit": 20, "offset": 0, "appliedFacets": {}}),
    ("limit+offset+empty searchText",{"limit": 20, "offset": 0, "searchText": ""}),
    ("limit+offset+facets+search",   {"limit": 20, "offset": 0, "appliedFacets": {}, "searchText": ""}),
    ("All fields null searchText",   {"limit": 20, "offset": 0, "appliedFacets": {}, "searchText": None}),
]

def probe(name, url):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"  {url}")
    print(f"{'='*60}")

    for label, body in CANDIDATES:
        for hdr_label, headers in [("full UA headers", HEADERS_FULL), ("minimal headers", HEADERS_MINIMAL)]:
            try:
                r = requests.post(url, json=body, headers=headers, timeout=10)
                status = r.status_code
                snippet = ""
                if status == 200:
                    data = r.json()
                    total = data.get("total", "?")
                    snippet = f"  ← total={total}"
                print(f"  [{status}]  {label:45s}  ({hdr_label}){snippet}")
                if status == 200:
                    print(f"\n  ✓ WORKING COMBINATION FOUND:")
                    print(f"    Headers : {hdr_label}")
                    print(f"    Body    : {json.dumps(body)}")
                    return body, headers
            except Exception as e:
                print(f"  [ERR]  {label:45s}  ({hdr_label})  → {e}")

    print(f"\n  ✗ No working combination found for {name}.")
    print(f"    Consider checking if the URL itself is wrong.")
    return None, None


if __name__ == "__main__":
    for name, url in ENDPOINTS.items():
        probe(name, url)
    print("\nDone. Paste the output back to Claude to get the targeted fix.\n")
