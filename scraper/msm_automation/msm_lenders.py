"""
Scrapes MoneySuperMarket's real rates-table results (not the marketing landing
page) via patchright - a Playwright fork that patches the CDP-level automation
signals Cloudflare's bot management fingerprints. This only works because it's
run from scraper/msm_automation/README.md's self-hosted runner: Cloudflare
blocks the underlying enquiry API by IP reputation for GitHub-hosted runners
(confirmed: Azure IPs get an explicit "unusual requests from the network you
are using" response) regardless of how clean the browser fingerprint is, so
this module must not be invoked from a GitHub-hosted job.

Scenario is fixed by design (see project discussion, not user-adjustable at
scrape time): a first-time-buyer purchase of a GBP 500,000 property with a
GBP 50,000 deposit (90% LTV), fixed-rate products only, 2/3 year terms.
Tracker/variable, 5yr+, and other LTV bands are out of scope for this source.

termTypes values ("TwoYears"/"ThreeYears"/etc.) were read directly off the live
filter checkboxes' DOM attributes (id="enquiry__termTypes--TwoYears" etc.),
not guessed - passing them as repeated query params (matching the pattern MSM
already uses for its own affordabilityOutcomes filter) cuts pages fetched
server-side, not just rows kept after the fact.
"""
from __future__ import annotations
import datetime as dt

from patchright.sync_api import sync_playwright

from ..common import LenderScrapeResult, RateRow, error_result

PROPERTY_VALUE = 500_000
DEPOSIT_AMOUNT = 50_000  # -> 90% LTV
LTV_BAND = 90
JOURNEY_TYPE = "FirstTimeBuyer"
TRACKED_FIX_YEARS = {2, 3}
TERM_TYPES = ["TwoYears", "ThreeYears"]
PAGE_SIZE = 20

BASE_URL = "https://www.moneysupermarket.com/mortgages/rates-table/first-time-buyer"

KNOWN_LENDERS = ["Nationwide", "Barclays", "Santander", "Halifax", "HSBC", "NatWest", "Lloyds"]


def _query_url(page: int) -> str:
    term_types_qs = "&".join(f"termTypes={t}" for t in TERM_TYPES)
    return (
        f"{BASE_URL}?propertyValue={PROPERTY_VALUE}&depositAmount={DEPOSIT_AMOUNT}"
        f"&requiredTerm=30&repaymentMethod=Repayment&region=England"
        f"&sortResultsBy=MonthlyCost&productTypes=Fixed&{term_types_qs}&page={page}"
        f"&journeyType={JOURNEY_TYPE}&userSegment=Browse"
    )


def _match_known_lender(msm_lender_name: str) -> str | None:
    """MSM returns full legal names ('Nationwide Building Society', 'Lloyds Bank') -
    match against our short tracked names by substring rather than exact equality."""
    name_lower = (msm_lender_name or "").lower()
    for short_name in KNOWN_LENDERS:
        if short_name.lower() in name_lower:
            return short_name
    return None


def _products_to_rows(products: list[dict]) -> dict[str, list[RateRow]]:
    rows_by_lender: dict[str, list[RateRow]] = {}
    seen: set[tuple[str, int, float]] = set()
    for product in products:
        category = product.get("category") or {}
        if category.get("productType") != "Fixed":
            continue
        fix_years = category.get("termInYears")
        if fix_years not in TRACKED_FIX_YEARS:
            continue

        lender_name = (product.get("lender") or {}).get("name", "")
        matched = _match_known_lender(lender_name)
        if matched is None:
            continue

        interest_rates = product.get("interestRates") or []
        if not interest_rates:
            continue
        rate = interest_rates[0].get("rate")
        if rate is None:
            continue

        # MSM sometimes lists the same lender product twice via different broker
        # fulfilment routes - same rate, same term, different listing. Collapse those.
        dedupe_key = (matched, fix_years, float(rate))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        costs = product.get("costs") or {}
        rows_by_lender.setdefault(matched, []).append(RateRow(
            lender=matched,
            ltv_band=LTV_BAND,
            product_type="fixed",
            fix_years=fix_years,
            rate_pct=float(rate),
            product_fee=costs.get("productFees"),
        ))
    return rows_by_lender


def scrape_msm_lenders() -> dict[str, LenderScrapeResult]:
    """Fetches every page of MSM's first-time-buyer Fixed results for the fixed
    500k/90%LTV scenario, filters to 2/3yr fixed products from the 7 tracked
    lenders, and returns one LenderScrapeResult per lender (status 'ok' if any
    rows were found, 'not_found' if the fetch worked but that lender had none)."""
    fetched_at = dt.date.today().isoformat()
    all_products: list[dict] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})

            page_num = 1
            pages_available = 1
            while page_num <= pages_available:
                with page.expect_response(
                    lambda r: "rates-table/api/v1/enquiry" in r.url, timeout=60_000
                ) as resp_info:
                    page.goto(_query_url(page_num), wait_until="domcontentloaded", timeout=60_000)
                response = resp_info.value

                if page_num == 1:
                    try:
                        btn = page.get_by_role("button", name="Accept all")
                        if btn.count() > 0:
                            btn.first.click(timeout=10_000)
                    except Exception:
                        pass
                page.wait_for_timeout(1_000)

                if response.status != 200:
                    raise RuntimeError(f"page {page_num}: enquiry call failed (status={response.status})")

                data = response.json()
                result = data.get("result", {})
                products = result.get("products", [])
                all_products.extend(products)
                pages_available = result.get("pagesAvailable", page_num)
                print(f"[msm] page {page_num}/{pages_available}: {len(products)} products")
                page_num += 1

            browser.close()
    except Exception as exc:  # noqa: BLE001
        err = error_result("MoneySuperMarket", BASE_URL, f"MSM Playwright scrape failed: {exc}")
        return {name: err for name in KNOWN_LENDERS}

    rows_by_lender = _products_to_rows(all_products)

    results: dict[str, LenderScrapeResult] = {}
    for lender in KNOWN_LENDERS:
        lender_rows = rows_by_lender.get(lender, [])
        if lender_rows:
            results[lender] = LenderScrapeResult(
                lender=lender,
                fetched_at=fetched_at,
                source_url=BASE_URL,
                status="ok",
                rows=lender_rows,
                note="Parsed from MoneySuperMarket's rates-table API (First Time Buyer, 500k/90% LTV, Fixed 2/3yr).",
            )
        else:
            results[lender] = LenderScrapeResult(
                lender=lender,
                fetched_at=fetched_at,
                source_url=BASE_URL,
                status="not_found",
                rows=[],
                note=f"{lender} not found among MSM's Fixed 2/3yr 90% LTV First Time Buyer results on this run.",
            )
    return results
