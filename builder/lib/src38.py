"""38커뮤니케이션 — 신규상장 목록/상세, 예비심사 청구 이력.

https는 SSL 핸드셰이크가 실패한다(2026-09 확인). http만 쓴다. 인코딩 euc-kr.
"""
from __future__ import annotations

import datetime as dt
import re

from .common import fetch, leaf_tables, num, pairs, soup

BASE = "http://www.38.co.kr/html/fund/"
IPO = "http://www.38.co.kr/html/ipo/ipo.htm"
DATE_RE = re.compile(r"^\d{4}/\d{2}/\d{2}$")


def _get(url: str, ns: str, key: str, refresh: bool = False) -> str:
    return fetch(url, encoding="euc-kr", ns=ns, key=key, gap=0.4, refresh=refresh)


def _rows(html: str, header_word: str) -> list[list[str]]:
    tabs = [t for t in leaf_tables(soup(html)) if header_word in t.get_text()]
    if not tabs:
        return []
    t = max(tabs, key=lambda x: len(x.select("tr")))
    return [[c.get_text(strip=True) for c in tr.select("td")] for tr in t.select("tr")]


def _links(html: str, header_word: str) -> dict[str, str]:
    tabs = [t for t in leaf_tables(soup(html)) if header_word in t.get_text()]
    if not tabs:
        return {}
    t = max(tabs, key=lambda x: len(x.select("tr")))
    return {a.get_text(strip=True): a["href"] for a in t.select("a[href*='no=']")}


def list_new_listings(since: dt.date, *, refresh_first: int = 2) -> list[dict]:
    """신규상장 목록. since 이후 상장분만. 최신 페이지 몇 장은 캐시를 새로 받는다."""
    out: list[dict] = []
    for page in range(1, 60):
        url = f"{BASE}index.htm?o=nw" + (f"&page={page}" if page > 1 else "")
        html = _get(url, "38list", f"nw_{page}", refresh=page <= refresh_first)
        rows = _rows(html, "기업명")
        links = _links(html, "기업명")
        got = False
        stop = False
        for r in rows:
            if len(r) < 9 or not DATE_RE.match(r[1] or ""):
                continue
            got = True
            d = dt.date.fromisoformat(r[1].replace("/", "-"))
            if d < since:
                stop = True
                continue
            href = links.get(r[0], "")
            m = re.search(r"no=(\d+)", href)
            if not m:
                continue
            out.append({
                "name_38": r[0], "listing_date": d.isoformat(), "no": m.group(1),
                "ipo_price_list": num(r[4]), "day1_open_38": num(r[6]), "day1_close_38": num(r[8]),
            })
        if stop or not got:
            break
    return out


def detail(no: str, *, refresh: bool = False) -> dict:
    """신규상장 상세 — 공모 조건, 청구 시점 재무, 종목코드."""
    html = _get(f"{BASE}?o=v&no={no}&l=", "38detail", no, refresh=refresh)
    bs = soup(html)
    tabs = leaf_tables(bs)

    def table_with(*words: str) -> dict[str, str]:
        for t in tabs:
            txt = t.get_text()
            if all(w in txt for w in words):
                return pairs(t)
        return {}

    co = table_with("종목명", "종목코드")
    ipo = table_with("총공모주식수", "액면가")
    inst = table_with("기관경쟁률")
    offer = ipo.get("상장공모", "")
    m_new = re.search(r"신주모집\s*:\s*([\d,]+)", offer)
    m_old = re.search(r"구주매출\s*:\s*([\d,]+)", offer)
    band = re.findall(r"[\d,]+", ipo.get("희망공모가액", ""))

    ratios: dict[str, dict[str, float | None]] = {}
    for t in tabs:
        if "EPS (주당순이익)" in t.get_text():
            rows = [[c.get_text(" ", strip=True) for c in tr.select("th,td")] for tr in t.select("tr")]
            years = [y.split(".")[0] for y in rows[0][1:]]
            for r in rows[1:]:
                label = r[0].split(" ")[0]
                ratios[label] = {y: num(v) for y, v in zip(years, r[1:])}
            break

    return {
        "no": no,
        "code": (co.get("종목코드") or "").strip() or None,
        "name_38": co.get("종목명"),
        "market_38": co.get("시장구분"),
        "industry_38": co.get("업종"),
        "status_38": co.get("진행상황"),
        "rev_at_filing_mkrw": num(co.get("매출액")),
        "ni_at_filing_mkrw": num(co.get("순이익")),
        "capital_mkrw": num(co.get("자본금")),
        "offer_shares": num(ipo.get("총공모주식수")),
        "par_value": num(ipo.get("액면가")),
        "new_shares": num(m_new.group(1)) if m_new else None,
        "old_shares": num(m_old.group(1)) if m_old else 0.0,
        "band_low": num(band[0]) if band else None,
        "band_high": num(band[1]) if len(band) > 1 else None,
        "ipo_price": num(ipo.get("확정공모가")),
        "offer_amount_mkrw": num(ipo.get("공모금액")),
        "underwriter": (ipo.get("주간사") or "").split("주식수")[0].strip() or None,
        "retail_sub_ratio": num(ipo.get("청약경쟁률")),
        "inst_demand_ratio": num(inst.get("기관경쟁률")),
        "lockup_commit_pct": num(inst.get("의무보유확약")),
        "ratios_38": ratios,
        "source_url": f"{BASE}?o=v&no={no}",
    }


STATUS = {"": "심사중", "승인": "승인", "철회": "철회", "상장": "상장"}


def list_filings(max_pages: int = 90, *, refresh_first: int = 3) -> list[dict]:
    """예비심사 청구 이력 전체(1999~). key=0은 상태 컬럼을 포함한 통합 목록."""
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        url = f"{IPO}?o=&key=0" + (f"&page={page}" if page > 1 else "")
        html = _get(url, "38ipo", f"list_{page}", refresh=page <= refresh_first)
        rows = _rows(html, "기업명")
        links = _links(html, "기업명")
        got = False
        for r in rows:
            if len(r) < 8 or not DATE_RE.match(r[0] or ""):
                continue
            got = True
            href = links.get(r[1], "")
            m = re.search(r"no=(\d+)", href)
            out.append({
                "filed_date": r[0].replace("/", "-"),
                "name_38": r[1],
                "status": STATUS.get(r[2].strip(), r[2].strip()),
                "capital_mkrw": num(r[3]),
                "revenue_mkrw": num(r[4]),
                "net_income_mkrw": num(r[5]),
                "underwriter": r[6] or None,
                "industry_38": r[7] or None,
                "no": m.group(1) if m else None,
            })
        if not got:
            break
    return out


def filing_detail(no: str, *, refresh: bool = False) -> dict:
    """청구종목 상세 — 설립일자, 시장구분, 승인일, 종목코드."""
    html = _get(f"{IPO}?o=v&key=2&no={no}", "38ipodetail", no, refresh=refresh)
    d = {}
    for t in leaf_tables(soup(html)):
        p = pairs(t)
        if "설립일자" in p and "청구일" in p:
            d = p
            break
    est = (d.get("설립일자") or "").replace("/", "-")
    return {
        "no": no,
        "name_38": d.get("기업명"),
        "code": (d.get("기업코드") or "").strip() or None,
        "filed_date_detail": ((d.get("청구일") or "").replace("/", "-") or None),
        "founded_date": est if re.match(r"\d{4}-\d{2}-\d{2}", est) else None,
        "market_38": d.get("시장구분"),
        "approved_date": ((d.get("승인일") or "").replace("/", "-") or None),
        "company_class": d.get("기업구분"),
        "main_product": d.get("주요제품"),
        "industry_38": d.get("업종"),
    }
