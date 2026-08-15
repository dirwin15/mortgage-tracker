"""
The repo scrapes MoneySuperMarket (an aggregator) once and splits the results back
out per known lender - this replaced an earlier approach of scraping each bank's own
calculator directly with Playwright, which failed for every lender (calculator flows
turned out too varied to drive generically). One aggregator page load covers all of
them, is more efficient, and isn't limited to a fixed shortlist of banks the way
per-bank scrapers were.
"""
from __future__ import annotations
import datetime as dt
import re

from .common import LenderScrapeResult, RateRow, USER_AGENT, error_result

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - installed in CI via requirements.txt
    sync_playwright = None


def _nearest_ltv_band(value: int) -> int:
    from .common import LTV_BANDS
    return min(LTV_BANDS, key=lambda band: abs(band - value))


# The banks we care about, matched case-insensitively against the text right before
# a rate figure. This list is what lets us attribute an aggregator's rows back to a
# real lender instead of lumping everything under "MoneySuperMarket".
KNOWN_LENDERS = [
    "Nationwide", "Barclays", "Santander", "Halifax", "HSBC", "NatWest", "Lloyds",
]
_LENDER_RE = re.compile(
    r"\b(" + "|".join(re.escape(name) for name in KNOWN_LENDERS) + r")\b", re.I
)


def _closest_ltv_hint(text: str, pos: int, window: int = 150) -> int:
    """Find the LTV% mention closest (by distance) to `pos`, not just the first one in
    a wide window - a wide window can pick up a neighbouring card's LTV by mistake."""
    start = max(0, pos - window)
    end = pos + window
    snippet = text[start:end]
    matches = list(re.finditer(
        r"(?P<ltv>60|70|75|80|85|90|95)\s*%\s*(?:LTV|loan to value)", snippet, re.I,
    ))
    if not matches:
        return 90  # sensible default if no LTV mentioned nearby
    closest = min(matches, key=lambda m: abs((start + m.start()) - pos))
    return int(closest.group("ltv"))


_RATE_LINE_RE = re.compile(
    r"(?P<fix>2|3|5|10)\s*(?:-?\s*year|yr|years)\s*(?:fixed|fix).*?"
    r"(?P<rate>\d{1,2}(?:\.\d{1,2})?)\s*%(?!\s*(?:LTV|loan.to.value))",
    re.I,
)


def extract_moneysupermarket_rows(raw_text: str) -> list[RateRow]:
    """Parse the visible deal cards from MoneySuperMarket's rate page.

    Real cards look like:
      Halifax  Rated 4.8 stars  Representative example  Monthly cost from £2,450
      2 year fixed at 90% LTV  Initial rate 4.46%  No product fee  Get this rate

    i.e. there's often a good amount of filler (ratings, "representative example",
    monthly cost) between the bank name and the actual rate line - a fixed-size
    lookback window either misses real matches (too tight) or bleeds into the
    previous card (too loose). Instead, segment the whole page by lender-name
    boundaries: find every occurrence of a known lender name, and treat the text
    between one occurrence and the next as that lender's card. Every rate line
    inside a card is attributed to that card's lender - simple, and correct
    regardless of how much filler text a real card contains.
    """
    text = re.sub(r"\s+", " ", raw_text or "")
    rows: list[RateRow] = []
    seen: set[tuple[str, int | None, str, int | None]] = set()

    lender_positions = sorted(
        (m.start(), m.group(1)) for m in _LENDER_RE.finditer(text)
    )
    if not lender_positions:
        return rows

    # Real cards end with a call-to-action like "Get this rate" - use the first such
    # marker after a lender's name as an extra card boundary, in addition to the next
    # known lender's name. This stops an unrecognised bank's card (e.g. a smaller
    # building society we don't track) from bleeding into the previous known lender's
    # card when it's the last known lender on the page.
    card_end_markers = list(re.finditer(
        r"\b(?:get this rate|see this deal|view deal|apply now|see details|more details)\b",
        text, re.I,
    ))

    unattributed = 0
    for i, (start_pos, raw_name) in enumerate(lender_positions):
        lender = next((n for n in KNOWN_LENDERS if n.lower() == raw_name.lower()), raw_name)
        next_lender_pos = lender_positions[i + 1][0] if i + 1 < len(lender_positions) else len(text)
        next_marker = next((m.end() for m in card_end_markers if m.start() > start_pos), len(text))
        end_pos = min(next_lender_pos, next_marker)
        card_text = text[start_pos:end_pos]

        for match in _RATE_LINE_RE.finditer(card_text):
            fix_years = int(match.group("fix"))
            rate = float(match.group("rate"))
            if not 1.0 <= rate <= 15.0:
                continue

            ltv_hint = _closest_ltv_hint(card_text, match.start())
            key = (lender, ltv_hint, "fixed", fix_years)
            if key in seen:
                continue
            seen.add(key)
            rows.append(RateRow(
                lender=lender,
                ltv_band=_nearest_ltv_band(ltv_hint),
                product_type="fixed",
                fix_years=fix_years,
                rate_pct=rate,
            ))

    if unattributed:
        print(f"[MoneySuperMarket] skipped {unattributed} rate(s) with no recognisable lender name nearby")

    return rows


def scrape_moneysupermarket() -> dict[str, LenderScrapeResult]:
    """
    Unlike the other scrapers, this returns a DICT of per-lender results (one aggregator
    fetch, split back out by lender) rather than a single LenderScrapeResult - that keeps
    each bank's line on the chart correctly attributed instead of merging them.
    """
    url = "https://www.moneysupermarket.com/mortgages/"
    fetched_at = dt.date.today().isoformat()

    if sync_playwright is None:
        err = error_result("MoneySuperMarket", url, "Playwright is not installed.")
        return {name: err for name in KNOWN_LENDERS}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1600, "height": 1200},
                user_agent=USER_AGENT,
            )
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_timeout(4_000)

            for label in [
                "Accept all",
                "Allow all",
                "Accept all cookies",
                "Allow all cookies",
                "Accept cookies",
            ]:
                try:
                    button = page.get_by_role("button", name=re.compile(label, re.I))
                    if button.count() > 0:
                        button.first.click(timeout=20_000)
                        break
                except Exception:
                    pass

                try:
                    link = page.get_by_text(re.compile(label, re.I))
                    if link.count() > 0:
                        link.first.click(timeout=20_000)
                        break
                except Exception:
                    pass

            page.wait_for_timeout(3_000)

            # Many deal cards are lazy-loaded as you scroll (infinite-scroll pattern) -
            # a single page load without scrolling was only surfacing 1-2 of the 7 banks
            # we care about. Scroll down in steps to trigger loading of more cards.
            previous_height = 0
            for _ in range(8):
                page.mouse.wheel(0, 1800)
                page.wait_for_timeout(1200)
                current_height = page.evaluate("document.body.scrollHeight")
                if current_height == previous_height:
                    break
                previous_height = current_height

            body_text = page.locator("body").inner_text()
            rows = extract_moneysupermarket_rows(body_text)
            browser.close()

            results: dict[str, LenderScrapeResult] = {}
            rows_by_lender: dict[str, list[RateRow]] = {}
            for row in rows:
                rows_by_lender.setdefault(row.lender, []).append(row)

            for lender in KNOWN_LENDERS:
                lender_rows = rows_by_lender.get(lender, [])
                if lender_rows:
                    results[lender] = LenderScrapeResult(
                        lender=lender,
                        fetched_at=fetched_at,
                        source_url=url,
                        status="ok",
                        rows=lender_rows,
                        note="Parsed from MoneySuperMarket's aggregated rate cards.",
                    )
                else:
                    results[lender] = LenderScrapeResult(
                        lender=lender,
                        fetched_at=fetched_at,
                        source_url=url,
                        status="not_found",
                        rows=[],
                        note=f"{lender} not found among parsed MoneySuperMarket deal cards on this run.",
                    )
            return results

    except Exception as exc:  # noqa: BLE001
        err = error_result("MoneySuperMarket", url, f"MoneySuperMarket Playwright scrape failed: {exc}")
        return {name: err for name in KNOWN_LENDERS}


def scrape_all_lenders() -> dict[str, LenderScrapeResult]:
    """Single entry point run_all.py calls: one aggregator fetch, results keyed by lender."""
    return scrape_moneysupermarket()
