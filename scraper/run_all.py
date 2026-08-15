"""
Daily entry point (run by GitHub Actions).

Fetches:
  - BoE Bank Rate + average fixed rates (full history)
  - Each lender's FULL rate matrix for today: every (ltv_band, product_type,
    fix_years) combination the scraper could find, not just one target cell.

Data shape (data/rates.json):
{
  "boe": { "bank_rate": [{date, value}, ...], ... },
  "lenders": {
    "Nationwide": [
      {
        "date": "2026-08-15",
        "status": "ok",
        "note": "",
        "rates": [
          {"ltv_band": 90, "product_type": "fixed", "fix_years": 2, "rate_pct": 4.85},
          {"ltv_band": 90, "product_type": "fixed", "fix_years": 5, "rate_pct": 4.60},
          ...
        ]
      },
      ...
    ]
  }
}
"""
from __future__ import annotations
import json
import datetime as dt
from pathlib import Path

from . import boe
from .lenders import SCRAPERS

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "rates.json"
BOE_HISTORY_START = dt.date(2022, 1, 1)


def load_existing() -> dict:
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text())
    return {"boe": {}, "lenders": {}}


def update_boe(data: dict) -> None:
    try:
        series_data = boe.fetch_all(BOE_HISTORY_START)
    except Exception as exc:  # noqa: BLE001
        print(f"[boe] fetch failed, keeping previous data: {exc}")
        return

    data["boe"] = {
        key: [{"date": o.date.isoformat(), "value": o.value} for o in obs]
        for key, obs in series_data.items()
    }
    print(f"[boe] updated: {[(k, len(v)) for k, v in data['boe'].items()]}")


def update_lenders(data: dict) -> None:
    today = dt.date.today().isoformat()
    data.setdefault("lenders", {})

    for lender_name, scrape_fn in SCRAPERS.items():
        try:
            result = scrape_fn()
        except Exception as exc:  # noqa: BLE001 - never let one bad lender kill the run
            print(f"[{lender_name}] unhandled exception: {exc}")
            continue

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
    data = load_existing()
    update_boe(data)
    update_lenders(data)
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(data, indent=2))
    print(f"Wrote {DATA_PATH}")


if __name__ == "__main__":
    main()
