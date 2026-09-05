"""입력 검증 — 계산 전에 스크립트가 막는다. LLM 판단에 맡기지 않는다."""
from __future__ import annotations

import datetime as dt

SECTORS = {"it_saas", "ai_data", "bio_health", "beauty", "ecommerce_platform",
           "fintech", "content_game", "hardware_semi", "industrial", "other"}
THIS_YEAR = dt.date.today().year


def _date(v, label: str, errs: list[str]) -> dt.date | None:
    if not v:
        return None
    try:
        return dt.date.fromisoformat(str(v))
    except ValueError:
        errs.append(f"{label}은(는) YYYY-MM-DD 형식이어야 합니다: {v!r}")
        return None


def validate_company(p: dict) -> list[str]:
    e: list[str] = []
    if not (p.get("name") or "").strip():
        e.append("회사명이 비어 있습니다.")
    if p.get("sector_tag") not in SECTORS:
        e.append(f"업종 태그가 잘못됐습니다: {p.get('sector_tag')!r}. 가능한 값 {sorted(SECTORS)}")
    fy = p.get("founded_year")
    if fy is not None and not (1900 <= int(fy) <= THIS_YEAR):
        e.append(f"설립연도가 범위를 벗어납니다: {fy}")
    for key, label in (("revenue_krw", "매출"), ("revenue_prev_krw", "전년 매출")):
        v = p.get(key)
        if v is not None and v < 0:
            e.append(f"{label}은(는) 음수일 수 없습니다: {v}")
    if p.get("revenue_krw") is None:
        e.append("최근 연매출이 필요합니다. 매출이 없으면 0을 넣으세요.")
    stage = p.get("stage")
    if stage is None or not (0 <= int(stage) <= 5):
        e.append(f"상장 단계는 0~5 사이여야 합니다: {stage!r}")
    elif int(stage) >= 3 and not p.get("stage_date"):
        e.append("예비심사 청구 이후 단계는 청구일(stage_date)이 필요합니다.")
    sd = p.get("stage_date")
    if sd:
        d = _date(sd if len(str(sd)) > 7 else f"{sd}-01", "청구일", e)
        if d and d > dt.date.today():
            e.append(f"청구일이 미래입니다: {sd}")
    shares = p.get("shares_outstanding")
    if shares is not None and shares <= 0:
        e.append(f"발행주식수는 0보다 커야 합니다: {shares}")
    lr = p.get("last_round") or {}
    if not shares and not (lr.get("post_money_krw") and lr.get("price_per_share_krw")):
        e.append("발행주식수, 또는 최근 투자 라운드의 밸류에이션과 주당 가격 중 하나가 필요합니다.")
    if lr.get("price_per_share_krw") is not None and lr["price_per_share_krw"] <= 0:
        e.append("최근 라운드 주당 가격은 0보다 커야 합니다.")
    return e


def validate_option(o: dict, shares_outstanding: int | None = None) -> list[str]:
    e: list[str] = []
    q0 = o.get("quantity")
    if q0 and shares_outstanding and q0 > shares_outstanding:
        e.append(f"옵션 수량({q0:,}주)이 발행주식수({shares_outstanding:,}주)보다 많습니다. "
                 "둘 중 하나가 잘못 입력됐습니다.")
    q = o.get("quantity")
    if not q or q <= 0:
        e.append(f"수량은 0보다 커야 합니다: {q!r}")
    s = o.get("strike_krw")
    if s is None or s <= 0:
        e.append(f"행사가는 0보다 커야 합니다: {s!r}")
    g = _date(o.get("grant_date"), "부여일", e)
    if not o.get("grant_date"):
        e.append("부여일이 필요합니다.")
    if g and g > dt.date.today():
        e.append(f"부여일이 미래입니다: {o['grant_date']}")
    x = _date(o.get("expiry_date"), "행사 기간 만료일", e)
    if g and x and x <= g:
        e.append("행사 기간 만료일이 부여일보다 앞서거나 같습니다.")
    sched = o.get("vest_schedule")
    if not sched:
        e.append("행사 가능 일정이 필요합니다. 예: [{\"after_months\": 24, \"cumulative_pct\": 0.5}]")
    else:
        prev = -1.0
        for i, step in enumerate(sorted(sched, key=lambda s: s.get("after_months", 0)), 1):
            m, pctv = step.get("after_months"), step.get("cumulative_pct")
            if m is None or m < 0:
                e.append(f"행사 일정 {i}: 개월 수가 잘못됐습니다: {m!r}")
            if pctv is None or not (0 < pctv <= 1):
                e.append(f"행사 일정 {i}: 누적 비율은 0 초과 1 이하여야 합니다: {pctv!r}")
            elif pctv < prev:
                e.append(f"행사 일정 {i}: 누적 비율이 앞 단계보다 줄었습니다.")
            else:
                prev = pctv
        if prev > 0 and abs(prev - 1.0) > 1e-6:
            e.append(f"행사 일정의 마지막 누적 비율이 100%가 아닙니다: {prev:.0%}")
    sal = o.get("salary_krw")
    if sal is not None and sal < 0:
        e.append("연봉은 음수일 수 없습니다.")
    return e
