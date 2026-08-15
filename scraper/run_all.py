"""
Daily entry point. BoE (--boe-only) runs on a GitHub-hosted runner; lenders
(--lenders-only) must run on the self-hosted runner (see
scraper/msm_automation/README.md) since MoneySuperMarket blocks GitHub-hosted
IPs regardless of browser fingerprint. With no flags, runs both - useful for
local testing, not for CI.

Fetches:
  - BoE Bank Rate + average fixed rates - FULL history, kept in full (not trimmed).
    A "tracking_start" date is stored once and never moved, so the frontend can
    toggle between full BoE history and "since I started tracking".
  - Each tracked lender's Fixed 2/3/5yr rates at 90% LTV for a first-time-buyer
    GBP 500,000 purchase (see scraper/msm_automation/msm_lenders.py for why
    that scenario is fixed rather than a full matrix).

Data shape (data/rates.json):
{
  "meta": { "tracking_start": "2026-08-15" },
  "boe": { "bank_rate": [{date, value}, ...], ... },
  "lenders": {
    "Nationwide": [
      {
        "date": "2026-08-15",
        "status": "ok",
        "note": "",
        "rates": [
          {"lender": "Nationwide", "ltv_band": 90, "product_type": "fixed", "fix_years": 2, "rate_pct": 4.85},
          ...
        ]
      },
      ...
    ]
  }
}
"""
from __future__ import annotations
import argparse
import json
import datetime as dt
from pathlib import Path

from . import boe
from .msm_automation.msm_lenders import scrape_msm_lenders

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "rates.json"
BOE_FULL_HISTORY_START = dt.date(2022, 1, 1)


def load_existing() -> dict:
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text())
    return {"meta": {}, "boe": {}, "lenders": {}}


def _ensure_tracking_start(data: dict, today: dt.date) -> str:
    """The date tracking first began - set once on the very first run and never
    moved afterwards, regardless of what lender data looks like on later runs.
    This is what the frontend's history toggle filters BoE data against."""
    meta = data.setdefault("meta", {})
    if "tracking_start" not in meta:
        meta["tracking_start"] = today.isoformat()
    return meta["tracking_start"]


def update_boe(data: dict) -> None:
    """Fetches and stores the FULL BoE history (back to 2022) - not trimmed.
    The frontend decides whether to display all of it or just the tracking window."""
    try:
        series_data = boe.fetch_all(BOE_FULL_HISTORY_START)
    except Exception as exc:  # noqa: BLE001
        print(f"[boe] fetch failed, keeping previous data: {exc}")
        return

    data["boe"] = {
        key: [{"date": o.date.isoformat(), "value": o.value} for o in obs]
        for key, obs in series_data.items()
    }
    print(f"[boe] updated (full history): {[(k, len(v)) for k, v in data['boe'].items()]}")


def update_lenders(data: dict) -> None:
    """MoneySuperMarket's rates-table API is Cloudflare-protected by IP reputation,
    not just browser fingerprint - this only works run from the self-hosted runner
    (see scraper/msm_automation/), never from a GitHub-hosted job."""
    today = dt.date.today().isoformat()
    data.setdefault("lenders", {})

    try:
        results = scrape_msm_lenders()
    except Exception as exc:  # noqa: BLE001 - one bad run shouldn't kill the file
        print(f"[lenders] MSM scrape failed entirely: {exc}")
        return

    for lender_name, result in results.items():
        history = data["lenders"].setdefault(lender_name, [])
        history = [row for row in history if row.get("date") != today]  # replace re-runs
        history.append({
            "date": today,
            "status": result.status,
            "note": result.note,
            "rates": [r.to_dict() for r in result.rows],
        })
        history.sort(key=lambda r: r["date"])
        data["lenders"][lender_name] = history

        print(f"[{lender_name}] status={result.status} rows={len(result.rows)}")


def main() -> None:
    # BoE and lenders run as separate jobs on separate runners (BoE has no reason
    # to need the self-hosted machine), each reading-modifying-writing the same
    # file and committing in turn - hence the ability to run just one half here.
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--boe-only", action="store_true")
    group.add_argument("--lenders-only", action="store_true")
    args = parser.parse_args()

    data = load_existing()
    today = dt.date.today()
    tracking_start = _ensure_tracking_start(data, today)

    if args.lenders_only:
        update_lenders(data)
    elif args.boe_only:
        update_boe(data)
    else:
        update_lenders(data)
        update_boe(data)

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(data, indent=2))
    print(f"Wrote {DATA_PATH} (tracking_start={tracking_start})")


if __name__ == "__main__":
    main()
