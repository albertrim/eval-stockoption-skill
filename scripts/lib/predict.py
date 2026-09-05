"""상장 가능성과 예상 시점 — 38 예비심사 청구 이력 실측치 기반."""
from __future__ import annotations

import datetime as dt

from . import dataset

STAGE_LABEL = {
    0: "준비 단계 (주관사 미선정)",
    1: "상장 주관사 선정",
    2: "기술평가 통과",
    3: "거래소 예비심사 청구",
    4: "예비심사 승인",
    5: "공모 진행 (증권신고서 제출)",
}

# 청구 전 단계는 실측 데이터가 없다. 청구 시 상장 확률에 곱하는 추정 계수.
# 근거는 references/methodology.md — 데이터가 아니라 가정이며 결과에 "추정"으로 표시한다.
PRE_FILING_FACTOR = {0: 0.15, 1: 0.35, 2: 0.55}
# 청구까지 걸리는 것으로 가정하는 개월 수 (같은 이유로 가정값)
PRE_FILING_MONTHS = {0: 30, 1: 18, 2: 9}

FLOOR, CEIL = 0.03, 0.92


def _rates(profitable: bool) -> tuple[dict, str]:
    """승인율·상장률을 어느 표본에서 가져올지.

    흑자 여부로 가른다. 최근 5년 청구 455건을 leave-one-out으로 채점하면
    흑자 분리(Brier 0.2077)만 분리 없음(0.2105)보다 낫다. 업종별 분리는
    0.2129로 오히려 나쁘고, 업종×흑자는 0.2138로 가장 나쁘다 — 셀 절반이
    30건 미만이라 노이즈를 확률로 내보내게 된다. 그래서 업종은 쓰지 않는다.
    """
    br = dataset.base_rates()
    key = "profitable" if profitable else "loss"
    bp = (br.get("by_profit") or {}).get(key)
    if bp and bp.get("approval_rate") is not None:
        return bp, f"최근 5년 {'흑자' if profitable else '적자'} 청구 기업"
    return br["overall"]["5y"], "코스닥 전체 최근 5년"


def _months(br: dict, key: str, default: float) -> tuple[float, bool]:
    """실측 소요 개월. 없으면 기본값을 쓰고 그 사실을 함께 돌려준다."""
    v = (br.get(key) or {}).get("median")
    return (float(v), False) if v else (default, True)


def estimate(*, sector_tag: str, stage: int, stage_date: str | None,
             revenue: float | None, profitable: bool, founded_year: int | None,
             revenue_prev: float | None = None) -> dict:
    br = dataset.base_rates()
    rates, rate_basis = _rates(profitable)
    approval = rates.get("approval_rate")
    listing = rates.get("listing_rate_given_approval")
    if approval is None or listing is None:
        raise ValueError("base_rates.json 에 승인율·상장률이 없습니다. 데이터를 다시 받으세요.")

    reasons: list[str] = []
    estimated = False
    if stage >= 5:
        prob = min(CEIL, listing + (1 - listing) * 0.5)
        reasons.append(f"증권신고서 제출 단계. 승인 후 상장 완료율 {listing:.0%}보다 높게 봄")
    elif stage == 4:
        prob = listing
        reasons.append(f"예비심사 승인 완료. 승인 후 상장 완료율 {listing:.0%} ({rate_basis})")
    elif stage == 3:
        prob = approval * listing
        reasons.append(f"청구 → 승인 {approval:.0%} × 승인 → 상장 {listing:.0%} ({rate_basis})")
    else:
        factor = PRE_FILING_FACTOR[stage]
        prob = approval * listing * factor
        estimated = True
        reasons.append(
            f"청구 시 상장 확률 {approval * listing:.0%}에 {STAGE_LABEL[stage]} 계수 "
            f"{factor:.0%}를 곱한 값입니다. **이 계수 {factor:.0%}에는 근거 데이터가 없습니다.** "
            "예비심사 청구 전 단계는 공개 통계가 없어, 주관사를 선정하고도 청구까지 못 가는 "
            "회사를 감안한 가정값을 씁니다. 이 숫자의 불확실성은 대부분 여기서 옵니다."
        )

    # 소요 기간
    filed_to_listed, ftl_default = _months(br, "filed_to_listed_months", 8.0)
    filed_to_approved, fta_default = _months(br, "filed_to_approved_months", 5.0)
    if ftl_default or fta_default:
        reasons.append("소요 기간 실측치가 없어 기본값으로 계산했습니다.")
    today = dt.date.today()
    anchor = today
    if stage in (3, 4) and stage_date:
        try:
            anchor = dt.date.fromisoformat(stage_date if len(stage_date) > 7 else stage_date + "-01")
        except ValueError:
            anchor = today
    elapsed = (today - anchor).days / 30.44 if anchor != today else 0.0
    if stage >= 5:
        remain = 1.5
    elif stage == 4:
        # 승인일로부터 얼마나 지났는지 빼야 한다. 15개월 전 승인이든 어제 승인이든
        # 같은 날짜가 나오면 사용자가 넣은 승인일이 버려진 것이다.
        remain = max(1.0, (filed_to_listed - filed_to_approved) - elapsed)
    elif stage == 3:
        remain = max(1.5, filed_to_listed - elapsed)
    else:
        remain = PRE_FILING_MONTHS[stage] + filed_to_listed
    anchor = today
    expected = anchor + dt.timedelta(days=int(remain * 30.44))
    if expected < today:
        expected = today + dt.timedelta(days=45)

    # 트랙 — 입력이 매출·영업이익뿐이므로 이익 요건 충족 여부만 본다
    if profitable:
        track = "일반 (수익성·매출액 기준)"
        track_note = "영업 흑자 → 일반기업 수익성·매출액 기준 검토 대상"
    else:
        share = (br.get("track_share", {}).get(sector_tag) or {}).get("tech_track_share")
        track = "기술성장 또는 이익미실현"
        track_note = ("영업 적자 → 기술성장기업(혁신기술·사업모델) 또는 "
                      "이익미실현(시장평가·성장성) 트랙 전제")
        if share is not None:
            track_note += f". 이 업종 최근 상장사의 {share:.0%}가 기술성장기업부"
    reasons.append(track_note)
    reasons.append("자기자본·기준시가총액 요건은 입력받지 않아 확인하지 않음 (공모 전에는 시총 산출 불가)")

    # 심사가 중앙값보다 훨씬 길어진 건은 상장으로 끝나는 비율이 낮다. 감쇠 계수는 가정이며
    # 그 사실을 결과에 적는다(methodology.md).
    stalled = False
    if stage in (3, 4) and elapsed > filed_to_listed * 2:
        decay = max(0.2, min(1.0, filed_to_listed / elapsed))
        prob *= decay
        stalled = True
        reasons.append(
            f"청구·승인 후 {elapsed:.0f}개월이 지났습니다. 최근 5년 청구 → 상장 중앙값은 "
            f"{filed_to_listed:.0f}개월입니다. 이만큼 길어진 건은 철회로 끝나는 경우가 많아 "
            f"확률에 {decay:.0%}를 곱했습니다(가정)."
        )
    if revenue_prev is not None and revenue is not None and revenue_prev > 0:
        growth = revenue / revenue_prev - 1
        reasons.append(f"매출 성장률 {growth:+.0%}. 상장 가능성 계산에는 쓰지 않았고 "
                       "비교기업을 볼 때 참고만 합니다.")
    if founded_year:
        age = today.year - founded_year
        med = (br.get("founded_to_filed_years", {}).get("by_sector", {}).get(sector_tag)
               or {}).get("median") or br.get("founded_to_filed_years", {}).get("overall")
        if med:
            reasons.append(f"설립 {age}년차. 이 업종은 설립 후 중앙값 {med:.0f}년에 예비심사를 청구")

    prob = max(FLOOR, min(CEIL, prob))
    if estimated:
        # 근거 없는 계수를 곱한 값에 1% 단위를 붙이면 없는 정밀도를 파는 것이다.
        prob = max(FLOOR, round(prob * 20) / 20)
    return {
        "probability": round(prob, 3),
        "probability_is_estimate": estimated or stalled,
        "stalled": stalled,
        "expected_ipo_date": expected.strftime("%Y-%m"),
        "expected_ipo_label": f"{expected.year}년 {'상반기' if expected.month <= 6 else '하반기'}",
        "months_to_ipo": round((expected - today).days / 30.44, 1),
        "stage": stage, "stage_label": STAGE_LABEL[stage],
        "track": track, "rate_basis": rate_basis,
        "approval_rate": approval, "listing_rate_given_approval": listing,
        "sample_n": rates.get("n"),
        "reasons": reasons,
    }


def peers_in_review(sector_tag: str, revenue: float | None, limit: int = 3) -> list[dict]:
    """같은 업종·비슷한 규모로 지금 심사 중인 회사."""
    today = dt.date.today().isoformat()
    rows = [r for r in dataset.pipeline().get("in_review", [])
            if r.get("sector_tag") == sector_tag
            and (r.get("filed_date") or "") <= today]      # 원본에 미래 날짜가 섞여 있다
    if revenue is not None:
        rows.sort(key=lambda r: abs((r.get("revenue_krw") or 0) - revenue))
    else:
        rows.sort(key=lambda r: r.get("filed_date", ""), reverse=True)
    return [{"name": r["name_38"], "revenue_krw": r.get("revenue_krw"),
             "net_income_krw": r.get("net_income_krw"), "filed_date": r.get("filed_date"),
             "status": r.get("status")} for r in rows[:limit]]
