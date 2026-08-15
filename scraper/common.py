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
    product_fee: float | None = None       # arrangement/product fee shown to the user, GBP
    total_fees: float | None = None        # ALL fees (arrangement + valuation/other), GBP -
                                            # used for total-payable math, may exceed product_fee
    follow_on_rate_pct: float | None = None  # lender's reversion/SVR rate after the fix ends -
                                              # needed to compute accurate whole-term totals
    fix_months: int | None = None          # ACTUAL fix duration in months - NOT fix_years*12.
                                            # MSM's fix periods run to a specific calendar end
                                            # date (e.g. a "2yr" product fixed until 31/10/2028),
                                            # which is rarely an exact 24 months - using fix_years
                                            # * 12 instead of this produced total-cost figures
                                            # consistently off by ~GBP 1,500-4,000 against MSM's
                                            # own numbers (verified against 20 live products).
    # product_fee/total_fees/follow_on_rate_pct/fix_months are flat product facts, safe to
    # store as scraped. Total payable/interest are NOT stored here, deliberately - they
    # depend on the loan amount and repayment term, which are user inputs; computing them
    # client-side (see RateTracker.jsx's twoStageTotals) with a full two-stage
    # (fix rate for fix_months, then follow-on rate for the rest) amortization keeps them
    # accurate for whatever term the user selects, matching MSM's own methodology (verified
    # against their own costs.totalCost/interest for the scraper's fixed 30yr scenario -
    # exact match to the penny once monthly payments are rounded per stage before summing,
    # the way real mortgage billing works) instead of frozen to whatever the scraper
    # happened to use (see msm_lenders.py).

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
