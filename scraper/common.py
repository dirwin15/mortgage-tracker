"""
Shared types for lender scrapers.

Data model: a lender's pricing is a MATRIX, not a single number - rate depends
on LTV band, product type (fixed/tracker/variable), and (if fixed) fix length.
Each scrape attempt should try to return every (ltv_band, product_type,
fix_years, rate) row it can find, not just one target cell - that's what lets
the frontend let you pick LTV/product/term after the fact without re-scraping.

LTV_BANDS: lenders price in bands, not a continuous curve. 90 is in here
because that's your case, but the full set lets the frontend snap any
entered LTV to the nearest band and show the others too.
"""
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass, asdict

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
    product_fee: float | None = None  # arrangement/product fee, GBP - flat, doesn't
                                       # scale with loan size, so safe to store as scraped.
                                       # Total payable/interest are NOT stored here - they
                                       # depend on the loan amount and repayment term, which
                                       # are user inputs the frontend already has; computing
                                       # them client-side (see RateTracker.jsx) keeps them
                                       # correct for whatever the user actually selects,
                                       # instead of frozen to whatever the scraper's fixed
                                       # scenario (see msm_lenders.py) happened to use.

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


def error_result(lender: str, url: str, message: str) -> LenderScrapeResult:
    return LenderScrapeResult(
        lender=lender,
        fetched_at=dt.date.today().isoformat(),
        source_url=url,
        status="error",
        rows=[],
        note=message,
    )
