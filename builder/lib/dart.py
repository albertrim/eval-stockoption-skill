"""DART 전자공시 — 기업개황(설립일), 증권신고서 본문 파싱.

재무 API(fnlttSinglAcnt)는 상장 직전·심사 중 기업에 데이터가 없어 쓰지 않는다(0단계 확인).
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import os
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from .common import CACHE

API = "https://opendart.fss.or.kr/api"


def _load_key() -> str:
    key = os.environ.get("DART_API_KEY", "").strip()
    if key:
        return key
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("DART_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


KEY = _load_key()


def enabled() -> bool:
    return bool(KEY)


def _cached_json(name: str, url: str, params: dict, ttl_days: int = 7) -> dict:
    path = CACHE / "dart" / f"{name}.json"
    if path.exists() and (time.time() - path.stat().st_mtime) < ttl_days * 86400:
        return json.loads(path.read_text())
    r = requests.get(url, params={**params, "crtfc_key": KEY}, timeout=30)
    data = r.json()
    # 인증 실패·일시 오류를 캐시하면 이후 실행이 조용히 빈 결과를 쓴다. 000(정상)과
    # 013(데이터 없음)만 캐시한다.
    if data.get("status") in {"000", "013"}:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False))
    elif data.get("status") not in {None}:
        raise RuntimeError(f"DART {url}: status={data.get('status')} {data.get('message')}")
    return data


def corp_index() -> dict[str, list[tuple[str, str]]]:
    """정규화한 회사명 → [(corp_code, stock_code)]. 동명이인 대비 리스트."""
    path = CACHE / "dart" / "corpCode.xml"
    if not path.exists():
        r = requests.get(f"{API}/corpCode.xml", params={"crtfc_key": KEY}, timeout=120)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(z.read(z.namelist()[0]))
    root = ET.fromstring(path.read_bytes())
    idx: dict[str, list[tuple[str, str]]] = {}
    for c in root.iter("list"):
        name = norm_name(c.findtext("corp_name") or "")
        idx.setdefault(name, []).append(
            ((c.findtext("corp_code") or "").strip(), (c.findtext("stock_code") or "").strip())
        )
    return idx


def norm_name(s: str) -> str:
    s = re.sub(r"\(구[.,][^)]*\)|\(유가\)|\(코스닥\)|\(Reg\.S\)", "", s)
    s = s.replace("주식회사", "").replace("(주)", "").replace("㈜", "")
    return re.sub(r"\s+", "", s).lower()


def find_corp(name: str, stock_code: str | None, idx: dict) -> str | None:
    cands = idx.get(norm_name(name), [])
    if stock_code:
        for cc, sc in cands:
            if sc.strip() == stock_code:
                return cc
    return cands[0][0] if cands else None


def company(corp_code: str) -> dict:
    d = _cached_json(f"co_{corp_code}", f"{API}/company.json", {"corp_code": corp_code}, ttl_days=365)
    est = (d.get("est_dt") or "").strip()
    return {
        "founded_date": f"{est[:4]}-{est[4:6]}-{est[6:8]}" if len(est) == 8 else None,
        "induty_code": d.get("induty_code"),
    }


def securities_filing(corp_code: str, bgn: str, end: str) -> str | None:
    """증권신고서(지분증권) 접수번호. [발행조건확정] 우선, 없으면 최신."""
    d = _cached_json(f"list_{corp_code}_{bgn}_{end}", f"{API}/list.json",
                     {"corp_code": corp_code, "bgn_de": bgn, "end_de": end,
                      "page_count": 100, "pblntf_ty": "C"}, ttl_days=30)
    items = [x for x in d.get("list", []) if "증권신고서" in x.get("report_nm", "")
             and "지분증권" in x.get("report_nm", "")]
    if not items:
        return None
    fixed = [x for x in items if "발행조건확정" in x["report_nm"]]
    return (fixed or items)[0]["rcept_no"]


def document_text(rcept_no: str, max_chars: int = 900_000) -> str:
    """공시 원문 → 태그 제거한 한 줄 텍스트."""
    path = CACHE / "dart_doc" / f"{rcept_no}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    r = requests.get(f"{API}/document.xml", params={"crtfc_key": KEY, "rcept_no": rcept_no}, timeout=180)
    raw = b""
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        raw = b"".join(z.read(n) for n in z.namelist())
    except zipfile.BadZipFile:
        raw = r.content
    text = ""
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;|&#\d+;", " ", text)
    text = re.sub(r"\s+", " ", text)[:max_chars]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


# ── 신고서 본문 파싱 ────────────────────────────────────────────────
_SHARES = [
    re.compile(r"상장예정주식수\s*\(?보통주\)?\s*([\d,]{5,})\s*주"),
    re.compile(r"상장\s*예정\s*주식\s*수[^\d]{0,30}([\d,]{5,})\s*주"),
    re.compile(r"공모\s*후\s*발행\s*주식\s*(?:총)?수[^\d]{0,40}([\d,]{5,})\s*주"),
]
_MULT = re.compile(r"유사\s*(?:기업|회사)\s*(PER|PBR|PSR|EV/EBITDA)\s*([\d,]+\.?\d*)\s*(?:배)?")
_DISC = re.compile(r"할인율\s*(?:\(%\))?[^\d\-]{0,40}(\d{1,2}\.?\d*)\s*%\s*[~∼-]\s*(\d{1,2}\.?\d*)\s*%")
_OPT_OUT = re.compile(r"미행사\s*주식매수선택권[^\d]{0,40}([\d,]{3,})\s*주")
_OPT_ROW = re.compile(
    r"(\d{2}\.\d{2}\.\d{2})\s+.{0,60}?보통주\s+"
    r"\d{2}\.\d{2}\.\d{2}\s*~\s*\d{2}\.\d{2}\.\d{2}\s+"
    r"([\d,]+)\s+([\d,]+|-)\s+([\d,]+|-)\s+([\d,]+|-)\s+([\d,]{2,})"
)


def _int(s: str) -> int | None:
    s = s.replace(",", "").strip()
    return int(s) if s.isdigit() else None


def parse_filing(text: str) -> dict:
    """증권신고서 본문에서 주식수·공모가 산정·스톡옵션 현황을 뽑는다. 못 찾으면 None."""
    out: dict = {"shares_at_ipo": None, "applied_multiple": None, "valuation_method": None,
                 "discount_low": None, "discount_high": None,
                 "options_outstanding": None, "option_strike_krw": None,
                 "option_grant_date": None}
    for rx in _SHARES:
        m = rx.search(text)
        if m:
            v = int(m.group(1).replace(",", ""))
            if 100_000 <= v <= 5_000_000_000:
                out["shares_at_ipo"] = v
                break
    m = _MULT.search(text)
    if m:
        out["valuation_method"] = m.group(1)
        out["applied_multiple"] = float(m.group(2).replace(",", ""))
    m = _DISC.search(text)
    if m:
        lo, hi = sorted((float(m.group(1)), float(m.group(2))))
        if 0 < lo < hi < 90:
            out["discount_low"], out["discount_high"] = lo / 100, hi / 100
    m = _OPT_OUT.search(text)
    if m:
        v = _int(m.group(1))
        if v and v >= 100:
            out["options_outstanding"] = v
    rows = []
    for m in _OPT_ROW.finditer(text):
        strike = _int(m.group(6))
        granted = _int(m.group(2))
        if strike and granted and 50 <= strike <= 2_000_000:
            rows.append((m.group(1), granted, strike))
    if rows:
        # 가장 최근 부여 회차의 행사가격 — "요즘 직원이 받는 행사가".
        # 행사기간 컬럼(미래 날짜)이 부여일 자리에 잡히는 경우가 있어 미래분은 버린다.
        today = _dt.date.today()
        dated = []
        for d, _q, strike in rows:
            try:
                g = _dt.date(2000 + int(d[:2]), int(d[3:5]), int(d[6:8]))
            except ValueError:
                continue
            if _dt.date(1998, 1, 1) <= g <= today:
                dated.append((g, strike))
        if dated:
            g, strike = max(dated)
            out["option_grant_date"] = g.isoformat()
            out["option_strike_krw"] = strike
    return out


def filing_facts(corp_code: str, bgn: str, end: str) -> dict:
    """[발행조건확정]과 최초 증권신고서를 함께 읽어 필드별로 채운다.

    [발행조건확정]은 정정분만 담아 짧은 경우가 많다(짧은 건 72K자). 최초 신고서에
    주식수·스톡옵션 표가 들어 있으므로 둘을 합쳐야 결측이 준다.
    """
    rcepts = securities_filing_all(corp_code, bgn, end)
    merged: dict = {}
    used: list[str] = []
    for rn in rcepts[:2]:
        got = parse_filing(document_text(rn))
        if any(v is not None for v in got.values()):
            used.append(rn)
        for k, v in got.items():
            if merged.get(k) is None and v is not None:
                merged[k] = v
    merged["filing_rcept_no"] = used[0] if used else None
    merged["filing_source_urls"] = [
        f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rn}" for rn in used
    ]
    return merged


def securities_filing_all(corp_code: str, bgn: str, end: str) -> list[str]:
    """증권신고서 접수번호 — [발행조건확정] 먼저, 그다음 최초 제출본."""
    d = _cached_json(f"list_{corp_code}_{bgn}_{end}", f"{API}/list.json",
                     {"corp_code": corp_code, "bgn_de": bgn, "end_de": end,
                      "page_count": 100, "pblntf_ty": "C"}, ttl_days=30)
    items = [x for x in d.get("list", []) if "증권신고서" in x.get("report_nm", "")
             and "지분증권" in x.get("report_nm", "")]
    if not items:
        return []
    items.sort(key=lambda x: x["rcept_dt"])
    fixed = [x["rcept_no"] for x in items if "발행조건확정" in x["report_nm"]]
    plain = [x["rcept_no"] for x in items if "정정" not in x["report_nm"]]
    order = fixed[-1:] + plain[:1] + [x["rcept_no"] for x in items]
    seen, out = set(), []
    for rn in order:
        if rn not in seen:
            seen.add(rn)
            out.append(rn)
    return out
