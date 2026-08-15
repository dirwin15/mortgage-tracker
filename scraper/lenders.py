"""
One function per lender, each returning a common.LenderScrapeResult containing
EVERY (ltv_band, product_type, fix_years, rate) row the scraper could parse off
the page - not just your 90% LTV / 2yr fixed case. The frontend filters down
to what you're interested in, so the data stays reusable if your plans change.

The repo now uses a shared Playwright helper for lenders whose rate data is not
available as a static table. That keeps the output format compatible with the
rest of the app while avoiding fragile attempts to parse generic marketing pages.
"""
from __future__ import annotations
import datetime as dt
import re

from .common import LenderScrapeResult, RateRow, USER_AGENT, error_result
from .playwright_helpers import scrape_via_playwright

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - installed in CI via requirements.txt
    sync_playwright = None


def _playwright_scrape(
    lender: str,
    url: str,
    *,
    property_value: int = 500000,
    deposit_percent: int = 10,
    term_years: int = 30,
    fix_years: int = 2,
    ltv_band: int = 90,
    product_type: str = "fixed",
) -> LenderScrapeResult:
    try:
        return scrape_via_playwright(
            lender,
            url,
            property_value=property_value,
            deposit_percent=deposit_percent,
            term_years=term_years,
            fix_years=fix_years,
            ltv_band=ltv_band,
            product_type=product_type,
        )
    except Exception as exc:  # noqa: BLE001
        return error_result(lender, url, f"Playwright scrape failed: {exc}")


def _parse_nationwide_text(raw_text: str) -> list[RateRow]:
    text = re.sub(r"\s+", " ", raw_text or "")
    rows: list[RateRow] = []
    for match in re.finditer(
        r"(?i)(\d{2,3})\s*%\s*LTV.*?(?:2|3|5|10)\s*[- ]?year.*?(\d{1,2}(?:\.\d{1,2})?)\s*%",
        text,
    ):
        ltv = int(match.group(1))
        rate = float(match.group(2))
        if not 1 <= rate <= 15:
            continue
        fix_years = 2 if "2" in text[match.start():match.end()] else 3 if "3" in text[match.start():match.end()] else 5 if "5" in text[match.start():match.end()] else 10
        rows.append(RateRow(
            ltv_band=min((60, 75, 80, 85, 90, 95), key=lambda b: abs(b - ltv)),
            product_type="fixed",
            fix_years=fix_years,
            rate_pct=rate,
        ))

    if rows:
        return rows

    for match in re.finditer(
        r"(?i)(?:2|3|5|10)\s*[- ]?year.*?(\d{1,2}(?:\.\d{1,2})?)\s*%.*?(\d{2,3})\s*%\s*LTV",
        text,
    ):
        rate = float(match.group(1))
        ltv = int(match.group(2))
        years = int(match.group(0).split()[0]) if match.group(0).split()[0].isdigit() else 2
        rows.append(RateRow(
            ltv_band=min((60, 75, 80, 85, 90, 95), key=lambda b: abs(b - ltv)),
            product_type="fixed",
            fix_years=years,
            rate_pct=rate,
        ))

    return rows


def scrape_nationwide() -> LenderScrapeResult:
    if sync_playwright is None:
        return error_result("Nationwide", "https://www.nationwide.co.uk/mortgages/mortgage-rates", "Playwright is not installed.")

    urls = [
        "https://www.nationwide.co.uk/mortgages/mortgage-rates",
        "https://www.nationwide.co.uk/mortgages/mortgage-calculators",
    ]

    for url in urls:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1600, "height": 1200}, user_agent=USER_AGENT)
                page.goto(url, wait_until="domcontentloaded", timeout=120_000)
                page.wait_for_timeout(4_000)

                for label in ["Allow all cookies", "Accept all cookies", "Accept all", "Accept cookies"]:
                    try:
                        if page.get_by_text(label, exact=True).count() > 0:
                            page.get_by_text(label, exact=True).first.click(timeout=20_000)
                            break
                    except Exception:
                        pass

                text = page.locator("body").inner_text()
                rows = _parse_nationwide_text(text)
                browser.close()
                if rows:
                    return LenderScrapeResult(
                        lender="Nationwide",
                        fetched_at=dt.date.today().isoformat(),
                        source_url=url,
                        status="ok",
                        rows=rows,
                        note="Rate parsed via Playwright from Nationwide mortgage rate page.",
                    )
        except Exception as exc:  # noqa: BLE001
            continue

    return LenderScrapeResult(
        lender="Nationwide",
        fetched_at=dt.date.today().isoformat(),
        source_url="https://www.nationwide.co.uk/mortgages/mortgage-rates",
        status="not_found",
        rows=[],
        note="Nationwide Playwright flow opened the page but no mortgage rate rows were parsed.",
    )


def scrape_barclays() -> LenderScrapeResult:
    return _playwright_scrape(
        "Barclays",
        "https://www.barclays.co.uk/mortgages/mortgage-calculator/",
        property_value=500000,
        deposit_percent=10,
        term_years=30,
        fix_years=2,
        ltv_band=90,
        product_type="fixed",
    )


def scrape_santander() -> LenderScrapeResult:
    return _playwright_scrape(
        "Santander",
        "https://www.santander.co.uk/personal/mortgages/mortgage-calculators",
        property_value=500000,
        deposit_percent=10,
        term_years=30,
        fix_years=2,
        ltv_band=90,
        product_type="fixed",
    )


def scrape_halifax() -> LenderScrapeResult:
    return _playwright_scrape(
        "Halifax",
        "https://www.halifax.co.uk/mortgages/mortgage-calculator/",
        property_value=500000,
        deposit_percent=10,
        term_years=30,
        fix_years=2,
        ltv_band=90,
        product_type="fixed",
    )


def scrape_hsbc() -> LenderScrapeResult:
    return _playwright_scrape(
        "HSBC",
        "https://www.hsbc.co.uk/mortgages/mortgage-calculator/",
        property_value=500000,
        deposit_percent=10,
        term_years=30,
        fix_years=2,
        ltv_band=90,
        product_type="fixed",
    )


def scrape_natwest() -> LenderScrapeResult:
    return _playwright_scrape(
        "NatWest",
        "https://www.natwest.com/mortgages/mortgage-calculators.html",
        property_value=500000,
        deposit_percent=10,
        term_years=30,
        fix_years=2,
        ltv_band=90,
        product_type="fixed",
    )


def scrape_lloyds() -> LenderScrapeResult:
    return _playwright_scrape(
        "Lloyds",
        "https://www.lloydsbankinggroup.com/",
        property_value=500000,
        deposit_percent=10,
        term_years=30,
        fix_years=2,
        ltv_band=90,
        product_type="fixed",
    )


SCRAPERS = {
    "Nationwide": scrape_nationwide,
    "Barclays": scrape_barclays,
    "Santander": scrape_santander,
    "Halifax": scrape_halifax,
    "HSBC": scrape_hsbc,
    "NatWest": scrape_natwest,
    "Lloyds": scrape_lloyds,
}
