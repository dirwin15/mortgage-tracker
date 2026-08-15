"""
One-off validation script: does patchright (a stealth-patched Playwright fork)
get past MoneySuperMarket's Cloudflare bot management when run headed-under-Xvfb,
from a real GitHub Actions runner?

This does NOT write to data/rates.json and is not part of the daily scrape - it
only prints diagnostics and exits non-zero on failure, so the workflow run's
pass/fail is visible at a glance in the Actions UI.

Confirmed locally (Windows, real display): patchright + headed Chromium gets a
real 200 with real product data from MSM's rates-table enquiry endpoint, where
vanilla Playwright (headless AND headed), bare `requests`, and even Playwright
with a valid session/XSRF token all get a Cloudflare 403 challenge page instead.

patchright + headless=True also failed locally - Cloudflare detects headless-
specific signals beyond the CDP leaks patchright patches. The documented fix
(patchright's own issue tracker, corroborated elsewhere) is headless=False under
Xvfb, a virtual display that keeps Chromium's normal non-headless rendering path
without needing a real monitor. This script tests exactly that combination, from
a real GitHub Actions runner - the one thing that can't be verified locally,
since Actions' IP ranges are a separate signal Cloudflare may act on independent
of browser fingerprint.
"""
from __future__ import annotations
import re
import sys

from patchright.sync_api import sync_playwright

URL = (
    "https://www.moneysupermarket.com/mortgages/rates-table/first-time-buyer"
    "?propertyValue=500000&depositAmount=50000&requiredTerm=30"
    "&repaymentMethod=Repayment&region=England&sortResultsBy=MonthlyCost"
    "&journeyType=FirstTimeBuyer&userSegment=Browse"
)

KNOWN_LENDERS = ["Nationwide", "Barclays", "Santander", "Halifax", "HSBC", "NatWest", "Lloyds"]


def main() -> int:
    captured = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on(
            "response",
            lambda r: captured.append(r) if "rates-table/api/v1/enquiry" in r.url else None,
        )

        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)
        try:
            btn = page.get_by_role("button", name=re.compile("Accept all", re.I))
            if btn.count() > 0:
                btn.first.click(timeout=10_000)
        except Exception:
            pass
        page.wait_for_timeout(6000)

        print(f"navigator.webdriver: {page.evaluate('navigator.webdriver')}")
        print(f"enquiry responses captured: {len(captured)}")

        ok = False
        if captured:
            resp = captured[0]
            print(f"enquiry status: {resp.status}")
            if resp.status == 200:
                try:
                    data = resp.json()
                    result = data.get("result", {})
                    products = result.get("products", [])
                    lenders_seen = sorted({p.get("lender", {}).get("name", "?") for p in products})
                    tracked_seen = [l for l in lenders_seen if l in KNOWN_LENDERS]
                    print(f"pagesAvailable: {result.get('pagesAvailable')}")
                    print(f"totalProductsFiltered: {result.get('totalProductsFiltered')}")
                    print(f"products on this page: {len(products)}")
                    print(f"distinct lenders on this page: {lenders_seen}")
                    print(f"tracked lenders present on this page: {tracked_seen}")
                    ok = len(products) > 0
                except Exception as e:
                    print(f"failed to parse response JSON: {e}")
        else:
            body_text = page.locator("body").inner_text()
            print("no enquiry response captured. body text sample:")
            print(body_text[:500])

        browser.close()

    print()
    print("RESULT:", "PASS - got real product data past Cloudflare" if ok else "FAIL - blocked or no data")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
