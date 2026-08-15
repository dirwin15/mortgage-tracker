from __future__ import annotations

import re
from typing import Any, Iterable

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - dependency installed at runtime in CI
    sync_playwright = None

from .common import LTV_BANDS, RateRow, LenderScrapeResult, USER_AGENT, error_result


def _matches_label(text: str) -> bool:
    tn = (text or "").strip().lower()
    return any(k in tn for k in [
        "property", "price", "value", "deposit", "term", "years",
        "salary", "income", "borrowing", "loan", "amount",
    ])


def _find_numeric_input(page: Any, label_hint: str, value: int | float) -> bool:
    selectors = [
        f"input[placeholder*='{label_hint}']",
        f"input[aria-label*='{label_hint}']",
        f"input[name*='{label_hint}']",
        "input[type='number']",
        "input[type='text']",
        "input:not([type])",
    ]

    seen = set()
    for selector in selectors:
        if selector in seen:
            continue
        seen.add(selector)
        try:
            locators = page.locator(selector)
            count = locators.count()
            for i in range(count):
                loc = locators.nth(i)
                if loc.is_visible():
                    try:
                        loc.fill(str(value))
                        return True
                    except Exception:
                        continue
        except Exception:
            continue

    for label in page.locator("label").all():
        try:
            text = label.inner_text()
        except Exception:
            continue
        if _matches_label(text) and "deposit" in text.lower():
            try:
                label.click()
            except Exception:
                pass
            try:
                field = label.locator("xpath=following::input[1]")
                if field.count() > 0 and field.first.is_visible():
                    field.first.fill(str(value))
                    return True
            except Exception:
                continue

    return False


def _infer_fix_years(text: str) -> int | None:
    matches = re.findall(r"(\d{1,2})\s*(?:-?\s*year|yr|years)", text, flags=re.I)
    if not matches:
        return None
    try:
        return int(matches[0])
    except ValueError:
        return None


def _parse_result_rates(text: str, *, prefer_fix_years: int | None = None) -> list[float]:
    candidates: list[float] = []
    for match in re.finditer(r"(\d{1,2}(?:\.\d{1,2})?)\s*%", text):
        value = float(match.group(1))
        if 1.0 <= value <= 15.0:
            candidates.append(value)

    if not candidates:
        return []

    deduped: list[float] = []
    seen: set[float] = set()
    for value in candidates:
        if round(value, 4) not in seen:
            seen.add(round(value, 4))
            deduped.append(value)

    if prefer_fix_years is not None:
        # Keep the most likely fixed-rate values near the requested term by preferring values
        # bundled with that term in the text, and otherwise fall back to the first consistent rate.
        fixed_term_text = re.findall(rf"{prefer_fix_years}\s*(?:-?\s*year|yr|years).*?(\d{{1,2}}(?:\.\d{{1,2}})?)\s*%", text, flags=re.I)
        if fixed_term_text:
            values = [float(v) for v in fixed_term_text]
            if values:
                return values

    return deduped


def _click_any(page: Any, phrases: Iterable[str]) -> bool:
    for phrase in phrases:
        try:
            button = page.get_by_role("button", name=re.compile(phrase, re.I))
            if button.count() > 0:
                button.first.click(timeout=30_000)
                return True
        except Exception:
            pass

        try:
            link = page.get_by_text(re.compile(phrase, re.I))
            if link.count() > 0:
                link.first.click(timeout=30_000)
                return True
        except Exception:
            pass

    return False


def scrape_via_playwright(
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
    """
    Generic browser-based helper for lenders whose rate data is only available after
    a calculator or comparison flow. Returns the same RateRow / LenderScrapeResult
    format expected by the rest of the repo.
    """
    if sync_playwright is None:
        raise RuntimeError(
            "playwright is required for calculator-based lender scrapes; install it via pip install playwright and run 'playwright install chromium'"
        )

    rows: list[RateRow] = []
    note = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1200}, user_agent=USER_AGENT)
        page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(3_000)

        bool_filled = False
        for selector_name, value in {
            "property": property_value,
            "price": property_value,
            "value": property_value,
            "deposit": int(property_value * (deposit_percent / 100)),
            "amount": property_value,
            "term": term_years,
            "years": term_years,
        }.items():
            if _find_numeric_input(page, selector_name, value):
                bool_filled = True

        if not bool_filled:
            # The site may render a different variant; try generic numeric inputs next.
            try:
                inputs = page.locator("input[type='number'], input[type='text'], input:not([type])")
                for index in range(min(inputs.count(), 6)):
                    candidate = inputs.nth(index)
                    if candidate.is_visible():
                        try:
                            candidate.fill(str(property_value if index == 0 else term_years))
                        except Exception:
                            pass
            except Exception:
                pass

        _click_any(page, ["calculate", "compare", "show rates", "find my rate", "see rates", "continue", "submit"])
        page.wait_for_timeout(5_000)

        body_text = page.locator("body").inner_text()
        rate_values = _parse_result_rates(body_text, prefer_fix_years=fix_years)

        if not rate_values:
            note = "Playwright opened the calculator successfully but no rate % could be extracted from the page text."
            browser.close()
            return LenderScrapeResult(
                lender=lender,
                fetched_at=None,
                source_url=url,
                status="not_found",
                rows=[],
                note=note,
            )

        # Keep the result set compatible with the rest of the repo: one row per rate value,
        # with the product metadata inferred from the page text if possible.
        for rate in rate_values:
            product = product_type
            term = fix_years if product_type == "fixed" else None
            if "tracker" in body_text.lower() and product_type == "fixed":
                product = "tracker"
                term = None
            if "tracker" not in body_text.lower() and "variable" in body_text.lower():
                product = "variable"
                term = None
            inferred_fix_years = _infer_fix_years(body_text)
            if inferred_fix_years is not None and product == "fixed":
                term = inferred_fix_years

            if ltv_band not in LTV_BANDS:
                ltv_band = min(LTV_BANDS, key=lambda b: abs(b - ltv_band))

            rows.append(RateRow(
                ltv_band=ltv_band,
                product_type=product,
                fix_years=term,
                rate_pct=float(rate),
            ))

        browser.close()

        if rows:
            note = "Rate extracted via Playwright calculator flow."
            return LenderScrapeResult(
                lender=lender,
                fetched_at=None,
                source_url=url,
                status="ok",
                rows=rows,
                note=note,
            )

        return error_result(lender, url, note or "Playwright flow completed but no parseable rates were found.")
