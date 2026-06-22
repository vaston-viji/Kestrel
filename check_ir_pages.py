import httpx
import re
import warnings

warnings.filterwarnings("ignore")

USER_AGENT = "Kestrel/1.0 (Australian Defence Brief; contact viji.john@quantrim.com)"

COMPANIES = [
    {
        "name": "Austal (ASB)",
        "urls": [
            "https://www.austal.com/investor-centre",
            "https://www.austal.com/investors",
            "https://www.austal.com/asb",
        ],
    },
    {
        "name": "DroneShield (DRO)",
        "urls": [
            "https://www.droneshield.com/investor-relations",
            "https://www.droneshield.com/asx-announcements",
            "https://www.droneshield.com/investors",
        ],
    },
    {
        "name": "EOS (EOS)",
        "urls": [
            "https://eos-aus.com/asx-announcements",
            "https://eos-aus.com/investor-relations",
            "https://eos-aus.com/investors",
        ],
    },
    {
        "name": "Codan (CDA)",
        "urls": [
            "https://www.codan.com.au/investor-centre",
            "https://www.codan.com.au/investors",
            "https://www.codancomms.com/investor-centre",
        ],
    },
    {
        "name": "HighCom (HCL)",
        "urls": [
            "https://highcom.group/investor-relations",
            "https://highcom.group/investors",
            "https://www.highcom.com.au/investor-relations",
        ],
    },
    {
        "name": "Aurora Labs (A3D)",
        "urls": [
            "https://auroralabs3d.com/investor-relations",
            "https://auroralabs3d.com/investors",
            "https://www.aurora-labs.com.au/investor-relations",
        ],
    },
    {
        "name": "Quickstep (QHL)",
        "urls": [
            "https://quickstep.com.au/investor-relations",
            "https://quickstep.com.au/investors",
            "https://www.quickstep.com.au/asx-announcements",
        ],
    },
]

IR_KEYWORDS = [
    "announcement",
    "ASX",
    "pdf",
    r"\b20\d{2}\b",  # years like 2020-2029
    "investor",
    "release",
    "quarterly",
    "half year",
    "half-year",
    "annual report",
]

RSS_PATTERN = re.compile(
    r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/rss\+xml["\']',
    re.IGNORECASE,
)
# Also check alternate ordering of attributes
RSS_PATTERN2 = re.compile(
    r'<link[^>]+type=["\']application/rss\+xml["\'][^>]+rel=["\']alternate["\']',
    re.IGNORECASE,
)


def check_ir_keywords(html: str) -> list:
    found = []
    for kw in IR_KEYWORDS:
        if re.search(kw, html, re.IGNORECASE):
            # Use the display form (strip regex syntax for readability)
            display = kw.replace(r"\b", "").replace("\\b", "")
            found.append(display)
    return found


def check_rss(html: str) -> bool:
    return bool(RSS_PATTERN.search(html) or RSS_PATTERN2.search(html))


def check_url(url: str) -> dict:
    result = {
        "url": url,
        "status": None,
        "final_url": None,
        "redirected": False,
        "ir_keywords": [],
        "looks_like_ir": False,
        "rss_found": False,
        "error": None,
    }
    try:
        with httpx.Client(
            verify=False,
            follow_redirects=True,
            timeout=15,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = client.get(url)
            result["status"] = response.status_code
            result["final_url"] = str(response.url)
            result["redirected"] = str(response.url) != url

            if response.status_code == 200:
                html = response.text
                keywords_found = check_ir_keywords(html)
                result["ir_keywords"] = keywords_found
                result["looks_like_ir"] = len(keywords_found) >= 2
                result["rss_found"] = check_rss(html)
    except httpx.TimeoutException as e:
        result["error"] = f"Timeout: {e}"
    except httpx.ConnectError as e:
        result["error"] = f"Connection error: {e}"
    except httpx.RequestError as e:
        result["error"] = f"Request error: {e}"
    except Exception as e:
        result["error"] = f"Unexpected error: {e}"
    return result


def print_result(r: dict):
    url = r["url"]
    if r["error"]:
        print(f"  URL:    {url}")
        print(f"  Status: ERROR - {r['error']}")
    else:
        print(f"  URL:    {url}")
        print(f"  Status: {r['status']}")
        if r["redirected"]:
            print(f"  Final:  {r['final_url']}")
        if r["status"] == 200:
            if r["looks_like_ir"]:
                print(f"  IR/ASX page: YES (keywords: {', '.join(r['ir_keywords'])})")
            else:
                if r["ir_keywords"]:
                    print(f"  IR/ASX page: MAYBE (only found: {', '.join(r['ir_keywords'])})")
                else:
                    print(f"  IR/ASX page: NO (no relevant keywords found)")
            print(f"  RSS feed:    {'YES' if r['rss_found'] else 'NO'}")
    print()


def main():
    print("=" * 70)
    print("ASX Investor Relations / Announcements Page Checker")
    print("=" * 70)
    print()

    for company in COMPANIES:
        print(f"{'=' * 70}")
        print(f"  {company['name']}")
        print(f"{'=' * 70}")
        for url in company["urls"]:
            r = check_url(url)
            print_result(r)


if __name__ == "__main__":
    main()
