"""코스닥 진입 요건 — 예상 시가총액이 형식요건 최소선에 닿는지 본다.

수치 출처는 references/kosdaq_listing_rules.md (한국거래소 「2026 코스닥 상장심사 이해와 실무」).
입력이 매출·영업이익뿐이라 판정은 시총 최소선 하나로 좁힌다. 자기자본을 안 받으므로
자기자본으로 갈음되는 요건은 "확인 못 함"으로 남긴다.
"""
from __future__ import annotations

EOK = 100_000_000

# 트랙별로 시가총액이 등장하는 요건 중 가장 낮은 문턱
MIN_CAP = {
    "일반": 90 * EOK,        # 이익 20억[벤처 10억] + 시총 90억
    "기술성장": 90 * EOK,     # 자기자본 10억 또는 기준시총 90억으로 갈음
    "이익미실현": 300 * EOK,  # 시총 300억 + 매출 100억[벤처 50억] 이 가장 낮은 안
}
# 이익미실현 트랙에서 시총 300억 안을 쓰려면 필요한 매출
UNPROFIT_MIN_REVENUE = 50 * EOK


def check(market_cap_krw: float | None, revenue_krw: float | None, profitable: bool) -> dict:
    """예상 시총이 형식요건 최소선에 닿는지. 닿지 않으면 이유를 돌려준다."""
    if not market_cap_krw:
        return {"verdict": "확인 못 함", "notes": ["예상 시가총액을 계산하지 못했습니다."]}

    notes: list[str] = []
    if profitable:
        floor, label = MIN_CAP["일반"], "일반기업(수익성) 트랙 최저선 시총 90억원"
    else:
        floor, label = MIN_CAP["기술성장"], "기술성장 트랙 최저선 기준시총 90억원"

    if market_cap_krw < floor:
        return {
            "verdict": "미달",
            "floor_krw": floor,
            "notes": [
                f"예상 시총이 {label}에 못 미칩니다. 지금 규모로는 코스닥 형식요건 어느 안에도 "
                "닿지 않습니다.",
                "상장 가능성 숫자는 '청구한 회사들이 상장한 비율'이라, 아직 청구할 수 없는 "
                "회사에는 그대로 적용되지 않습니다.",
            ],
        }

    if not profitable:
        if market_cap_krw < MIN_CAP["이익미실현"]:
            notes.append(
                "이익미실현(시장평가·성장성) 트랙은 최저 안이 시총 300억원 + 매출 50억원"
                "(벤처)입니다. 예상 시총이 그에 못 미쳐 기술성장 트랙(전문평가기관 등급)이 "
                "사실상 유일한 길입니다."
            )
        elif revenue_krw is not None and revenue_krw < UNPROFIT_MIN_REVENUE:
            notes.append(
                "이익미실현 트랙의 시총 300억원 안은 매출 50억원(벤처)을 함께 요구합니다. "
                "매출이 그에 못 미치면 시총 500억~1,000억원 안으로 가야 합니다."
            )
    notes.append("자기자본·기준시가총액 요건은 입력받지 않아 확인하지 않았습니다.")
    return {"verdict": "가능성 있음", "floor_krw": floor, "notes": notes}
