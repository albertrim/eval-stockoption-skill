"""네이버 금융 — 기업실적분석(연간 3년 + 추정), 상장주식수, 업종명."""
from __future__ import annotations

import re

from .common import eok, fetch, num, soup

URL = "https://finance.naver.com/item/main.naver?code={code}"
ROW_KEYS = {
    "매출액": "revenue", "영업이익": "operating_income", "당기순이익": "net_income",
    "EPS(원)": "eps", "BPS(원)": "bps", "ROE(지배주주)": "roe", "부채비율": "debt_ratio",
}


def financials(code: str, *, refresh: bool = False) -> dict:
    """{'years': {2024: {revenue: 원, ...}}, 'shares_now': int, 'industry_naver': str}"""
    html = fetch(URL.format(code=code), ns="naver", key=code, gap=0.3, refresh=refresh)
    bs = soup(html)
    table = next((t for t in bs.select("table") if "주요재무정보" in t.get_text()), None)
    years: dict[int, dict] = {}
    head_rows = table.select("thead tr") if table else []
    if len(head_rows) >= 2:
        heads = [th.get_text(" ", strip=True) for th in head_rows[1].select("th")]
        annual: list[tuple[int, int]] = []      # (컬럼 index, 연도)
        for i, h in enumerate(heads):
            m = re.match(r"(\d{4})\.(\d{2})", h)
            if m and "(E)" not in h and len(annual) < 4:
                annual.append((i, int(m.group(1))))
            if m and "(E)" in h:
                break
        for tr in table.select("tbody tr"):
            th = tr.select_one("th")
            if not th:
                continue
            key = ROW_KEYS.get(th.get_text(strip=True))
            if not key:
                continue
            tds = [td.get_text(strip=True) for td in tr.select("td")]
            for i, year in annual:
                if i >= len(tds):
                    continue
                v = num(tds[i])
                if v is None:
                    continue
                years.setdefault(year, {})[key] = (
                    eok(v) if key in {"revenue", "operating_income", "net_income"} else v
                )
    m = re.search(r"상장주식수[^<]*</th>\s*<td[^>]*>\s*<em[^>]*>([\d,]+)", html, re.S)
    if not m:
        el = bs.find(string=re.compile("상장주식수"))
        row = el.find_parent("tr") if el else None
        m = re.search(r"([\d,]{4,})", row.get_text(" ", strip=True)) if row else None
    ind = re.search(r"업종명\s*:\s*([^｜|<]+)", bs.get_text(" ", strip=True))
    return {
        "years": years,
        "shares_now": int(m.group(1).replace(",", "")) if m else None,
        "industry_naver": ind.group(1).strip() if ind else None,
        "source_url": URL.format(code=code),
    }
