"""FinanceDataReader — 상장일·소속부·주식수·주가 경로, 코스닥 지수."""
from __future__ import annotations

import datetime as dt
import functools

import FinanceDataReader as fdr
import pandas as pd

OFFSETS = {"1m": 30, "3m": 91, "6m": 182, "12m": 365}


@functools.lru_cache(maxsize=1)
def desc() -> pd.DataFrame:
    df = fdr.StockListing("KRX-DESC")
    df["ListingDate"] = pd.to_datetime(df["ListingDate"], errors="coerce")
    return df.set_index("Code")


@functools.lru_cache(maxsize=1)
def kosdaq() -> pd.DataFrame:
    return fdr.StockListing("KOSDAQ").set_index("Code")


def profile(code: str) -> dict:
    out: dict = {}
    d, k = desc(), kosdaq()
    if code in d.index:
        row = d.loc[code]
        row = row.iloc[0] if isinstance(row, pd.DataFrame) else row
        out |= {
            "listing_date_krx": None if pd.isna(row.ListingDate) else row.ListingDate.date().isoformat(),
            "market_krx": row.Market, "dept_krx": row.Sector, "industry_krx": row.Industry,
        }
    if code in k.index:
        row = k.loc[code]
        row = row.iloc[0] if isinstance(row, pd.DataFrame) else row
        out |= {"shares_now_krx": int(row.Stocks), "marcap_now": int(row.Marcap),
                "close_now": float(row.Close)}
    return out


def prices(code: str, listing_date: str) -> dict:
    start = dt.date.fromisoformat(listing_date)
    try:
        df = fdr.DataReader(code, start.isoformat())
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    first, last = df.iloc[0], df.iloc[-1]
    out = {
        "day1_open": float(first.Open), "day1_close": float(first.Close),
        "latest_date": df.index[-1].date().isoformat(), "latest_close": float(last.Close),
    }
    for label, days in OFFSETS.items():
        cut = pd.Timestamp(start + dt.timedelta(days=days))
        sub = df[df.index <= cut]
        out[f"close_{label}"] = float(sub.iloc[-1].Close) if len(sub) and cut <= df.index[-1] else None
    return out


def kosdaq_index_cagr(years: int) -> float | None:
    """코스닥 지수 최근 N년 연환산 수익률."""
    end = dt.date.today()
    start = end - dt.timedelta(days=365 * years + 5)
    try:
        df = fdr.DataReader("KQ11", start.isoformat())
    except Exception:
        return None
    if df is None or len(df) < 100:
        return None
    first, last = float(df.iloc[0].Close), float(df.iloc[-1].Close)
    span = (df.index[-1] - df.index[0]).days / 365.25
    if first <= 0 or span < 1:
        return None
    return (last / first) ** (1 / span) - 1
