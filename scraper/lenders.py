"""
One function per lender, each returning a common.LenderScrapeResult containing
EVERY (ltv_band, product_type, fix_years, rate) row the scraper could parse off
the page - not just your 90% LTV / 2yr fixed case. The frontend filters down
to what you're interested in, so the data stays reusable if your plans change.

STATUS NOTES (as of planning, Aug 2026):
  - Nationwide, Barclays, Santander: static-ish rate pages, parsed via
    common.extract_rate_matrix. Verify against the live page on first run -
    if `rows` comes back empty, the page's row markup didn't match our
    <tr>/card heuristics and needs a look.
  - Halifax, HSBC, NatWest, Lloyds: rate depends on submitting inputs to an
    interactive calculator (JS-rendered) rather than one static table, so a
    plain requests.get() won't see a rate at all. Stubbed for now - build
    with Playwright once the static-table lenders are confirmed working.
"""
from __future__ import annotations
import datetime as dt

from .common import (
    LenderScrapeResult, fetch_html, extract_rate_matrix, error_result,
)


def _static_page_scrape(lender: str, url: str) -> LenderScrapeResult:
    try:
        html = fetch_html(url)
    except Exception as exc:  # noqa: BLE001
        return error_result(lender, url, f"fetch failed: {exc}")

    rows = extract_rate_matrix(html)
    if not rows:
        return LenderScrapeResult(
            lender=lender,
            fetched_at=dt.date.today().isoformat(),
            source_url=url,
            status="not_found",
            rows=[],
            note="No rate rows parsed - page structure likely changed, inspect manually.",
        )

    return LenderScrapeResult(
        lender=lender,
        fetched_at=dt.date.today().isoformat(),
        source_url=url,
        status="ok",
        rows=rows,
    )


def scrape_nationwide() -> LenderScrapeResult:
    return _static_page_scrape("Nationwide", "https://www.nationwide.co.uk/mortgages/new-mortgage-rates")


def scrape_barclays() -> LenderScrapeResult:
    return _static_page_scrape("Barclays", "https://www.barclays.co.uk/mortgages/mortgage-rates/")


def scrape_santander() -> LenderScrapeResult:
    return _static_page_scrape("Santander", "https://www.santander.co.uk/personal/mortgages/mortgage-rates")


def _calculator_driven_stub(lender: str) -> LenderScrapeResult:
    return error_result(
        lender,
        url="",
        message=(
            "Not implemented: this lender returns a personalised rate from an "
            "interactive calculator (JS-rendered), so a plain requests.get() won't "
            "see a rate table. Needs a Playwright script that loads the page, fills "
            "in property value / deposit / term for each LTV band we want, and reads "
            "back the resulting rate. Build once the static-table lenders are confirmed."
        ),
    )


def scrape_halifax() -> LenderScrapeResult:
    return _calculator_driven_stub("Halifax")


def scrape_hsbc() -> LenderScrapeResult:
    return _calculator_driven_stub("HSBC")


def scrape_natwest() -> LenderScrapeResult:
    return _calculator_driven_stub("NatWest")


def scrape_lloyds() -> LenderScrapeResult:
    return _calculator_driven_stub("Lloyds")


SCRAPERS = {
    "Nationwide": scrape_nationwide,
    "Barclays": scrape_barclays,
    "Santander": scrape_santander,
    "Halifax": scrape_halifax,
    "HSBC": scrape_hsbc,
    "NatWest": scrape_natwest,
    "Lloyds": scrape_lloyds,
}
