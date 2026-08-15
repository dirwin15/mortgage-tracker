"""
Fetches official Bank of England data:
  - Bank Rate (base rate)
  - Average quoted 2yr/5yr fixed mortgage rates at 75% LTV (used as a market backdrop line)

Source: BoE Interactive Statistical Database (IADB) CSV endpoint. No API key required.
Docs: https://www.bankofengland.co.uk/boeapps/database/
"""
from __future__ import annotations
import csv
import io
import datetime as dt
from dataclasses import dataclass

import requests

IADB_URL = "http://www.bankofengland.co.uk/boeapps/iadb/fromshowcolumns.asp"

# Series codes:
#   IUDBEDR = Bank Rate (daily)
#   IUMBV34/37/42/45 = 2/3/5/10yr fixed mortgage rate, 75% LTV (monthly)
SERIES = {
    "bank_rate": "IUDBEDR",
    "fixed_2yr_75ltv": "IUMBV34",
    "fixed_5yr_75ltv": "IUMBV42",
}


@dataclass
class BoeObservation:
    series: str
    date: dt.date
    value: float


def _fetch_series_csv(series_code: str, date_from: dt.date, date_to: dt.date) -> str:
    params = {
        "csv.x": "yes",
        "Datefrom": date_from.strftime("%d/%b/%Y"),
        "Dateto": date_to.strftime("%d/%b/%Y"),
        "SeriesCodes": series_code,
        "CSVF": "TN",
        "UsingCodes": "Y",
        "VPD": "Y",
        "VFD": "N",
    }
    resp = requests.get(IADB_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.text


def fetch_series(series_key: str, date_from: dt.date, date_to: dt.date | None = None) -> list[BoeObservation]:
    """Fetch one named series (see SERIES dict) and return sorted observations."""
    code = SERIES[series_key]
    date_to = date_to or dt.date.today()
    raw = _fetch_series_csv(code, date_from, date_to)

    reader = csv.reader(io.StringIO(raw))
    rows = list(reader)
    if not rows:
        return []

    # First row is header: "DATE", <series_code>
    observations = []
    for row in rows[1:]:
        if len(row) < 2 or not row[1].strip():
            continue
        try:
            date = dt.datetime.strptime(row[0].strip(), "%d %b %Y").date()
            value = float(row[1].strip())
        except ValueError:
            continue
        observations.append(BoeObservation(series=series_key, date=date, value=value))

    observations.sort(key=lambda o: o.date)
    return observations


def fetch_all(date_from: dt.date) -> dict[str, list[BoeObservation]]:
    return {key: fetch_series(key, date_from) for key in SERIES}


if __name__ == "__main__":
    data = fetch_all(dt.date.today() - dt.timedelta(days=365))
    for series_key, obs in data.items():
        latest = obs[-1] if obs else None
        print(f"{series_key}: {len(obs)} points, latest = {latest}")
