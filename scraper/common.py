"""
Shared types and helpers for lender scrapers.

Data model: a lender's pricing is a MATRIX, not a single number - rate depends
on LTV band, product type (fixed/tracker/variable), and (if fixed) fix length.
Each scrape attempt should try to return every (ltv_band, product_type,
fix_years, rate) row it can find on the page, not just one target cell -
that's what lets the frontend let you pick LTV/product/term after the fact
without re-scraping.

LTV_BANDS: lenders price in bands, not a continuous curve. 90 is in here
because that's your case, but the full set lets the frontend snap any
entered LTV to the nearest band and show the others too.
"""
from __future__ import annotations
import re
import datetime as dt
from dataclasses import dataclass, asdict

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

LTV_BANDS = [60, 75, 80, 85, 90, 95]
FIX_LENGTHS = [2, 3, 5, 10]
PRODUCT_TYPES = ["fixed", "tracker", "variable"]


@dataclass
class RateRow:
    lender: str                   # which bank this rate actually belongs to
    ltv_band: int | None          # nearest LTV_BANDS value, or None if unrecognised
    product_type: str             # "fixed" | "tracker" | "variable"
    fix_years: int | None         # None for tracker/variable
    rate_pct: float

    def to_dict(self):
        return asdict(self)


@dataclass
class LenderScrapeResult:
    lender: str
    fetched_at: str               # ISO date
    source_url: str
    status: str                   # "ok" | "error" | "not_found"
    rows: list[RateRow]
    note: str = ""

    def to_dict(self):
        d = asdict(self)
        return d


def fetch_html(url: str, timeout: int = 30) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _row_blocks(html: str) -> list[str]:
    """
    Split a page into candidate 'row' text blocks: table rows first, falling
    back to common card/list-item containers, falling back to the whole page
    as one block. Each block should ideally contain one product's LTV, term,
    and rate close together.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    rows = soup.find_all("tr")
    if not rows:
        rows = soup.find_all(["li", "div"], class_=re.compile(r"(rate|product|card)", re.I))
    if not rows:
        return [soup.get_text(" ", strip=True)]

    blocks = [r.get_text(" ", strip=True) for r in rows]
    return [b for b in blocks if b]


_LTV_RE = re.compile(r"(\d{2,3})\s*%\s*LTV", re.I)
_RATE_RE = re.compile(r"(\d{1,2}\.\d{1,2})\s*%")
_FIX_RE = re.compile(r"(\d{1,2})\s*[- ]?year", re.I)
_TRACKER_RE = re.compile(r"\btracker\b", re.I)
_VARIABLE_RE = re.compile(r"\bvariable\b", re.I)


def _nearest_band(ltv_raw: int) -> int | None:
    if not LTV_BANDS:
        return None
    return min(LTV_BANDS, key=lambda b: abs(b - ltv_raw))


def parse_row(text: str, lender: str) -> RateRow | None:
    """Try to pull (ltv, product_type, fix_years, rate) out of one row of text."""
    ltv_match = _LTV_RE.search(text)
    if not ltv_match:
        return None
    ltv_band = _nearest_band(int(ltv_match.group(1)))

    is_tracker = bool(_TRACKER_RE.search(text))
    is_variable = bool(_VARIABLE_RE.search(text))
    fix_match = _FIX_RE.search(text)

    if is_tracker:
        product_type, fix_years = "tracker", None
    elif is_variable and not fix_match:
        product_type, fix_years = "variable", None
    elif fix_match:
        product_type, fix_years = "fixed", int(fix_match.group(1))
    else:
        return None  # can't tell what product this row is

    # Rate: prefer a % figure that isn't the LTV% or the fix-length number itself.
    rate_candidates = [
        float(m.group(1)) for m in _RATE_RE.finditer(text)
    ]
    rate_candidates = [r for r in rate_candidates if 1.0 <= r <= 15.0]
    if not rate_candidates:
        return None

    return RateRow(lender=lender, ltv_band=ltv_band, product_type=product_type,
                    fix_years=fix_years, rate_pct=rate_candidates[0])


def extract_rate_matrix(html: str, lender: str) -> list[RateRow]:
    """Scan every row-like block on the page and collect every parseable rate row.
    Deduplicates identical (ltv, product, fix_years) keeping the first rate seen."""
    seen = {}
    for block in _row_blocks(html):
        row = parse_row(block, lender)
        if row is None:
            continue
        key = (row.ltv_band, row.product_type, row.fix_years)
        if key not in seen:
            seen[key] = row
    return list(seen.values())


def error_result(lender: str, url: str, message: str) -> LenderScrapeResult:
    return LenderScrapeResult(
        lender=lender,
        fetched_at=dt.date.today().isoformat(),
        source_url=url,
        status="error",
        rows=[],
        note=message,
    )
