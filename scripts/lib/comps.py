"""비교기업 선정 — 같은 업종·비슷한 매출·같은 손익 상태의 최근 코스닥 상장사."""
from __future__ import annotations

from . import dataset

MIN_COMPS = 5
NEAR, WIDE = 3.0, 10.0   # 매출 배수 밴드

# 코스닥 상장이 드문 업종(화장품 7곳, 이커머스 4곳)은 같은 성격의 이웃 업종까지 넓힌다.
# 업종을 아예 무시하는 것보다 낫다.
GROUPS = {
    "tech": ("it_saas", "ai_data", "hardware_semi"),
    "bio": ("bio_health",),
    "consumer": ("beauty", "ecommerce_platform", "content_game"),
    "finance": ("fintech",),
    "industry": ("industrial", "other"),
}
GROUP_OF = {tag: g for g, tags in GROUPS.items() for tag in tags}
GROUP_LABEL = {"tech": "IT·하드웨어", "bio": "바이오·헬스케어", "consumer": "소비자·콘텐츠",
               "finance": "금융", "industry": "제조·산업"}


def group_peers(sector_tag: str) -> tuple[str, ...]:
    return GROUPS.get(GROUP_OF.get(sector_tag, ""), (sector_tag,))


# 매출이 이보다 작으면 매출 배수가 뜻을 잃는다. 임상 단계 바이오처럼 매출 8억에 PSR 68배를
# 곱하면 숫자가 나오긴 하지만 근거가 없다. 문턱은 백테스트로 골랐다
# (1억 → 오차 50.6%·적중 67.3%, 30억 → 49.9%·69.6%).
PSR_MIN_REVENUE = 3_000_000_000


# 이익률이 이보다 얇으면 PER은 회사 규모를 못 담는다. 매출 1,000억에 순이익 10억(1%)이면
# PER 26.8배를 곱해 시총 268억이 나온다. 흑자 전환 첫 해나 이익 추정치를 넣을 때 늘 이렇게
# 된다. 그런 경우 매출로 본다.
MIN_PER_MARGIN = 0.03


def thin_margin(revenue: float | None, net_income: float | None) -> bool:
    return bool(revenue and net_income and net_income > 0
                and net_income / revenue < MIN_PER_MARGIN)


def pick_metric(revenue: float | None, net_income: float | None, profitable: bool) -> str:
    """배수 종류를 먼저 정한다. 비교기업도 이 배수를 가진 회사만 쓴다."""
    if profitable and net_income and net_income > 0:
        if not (thin_margin(revenue, net_income) and revenue >= PSR_MIN_REVENUE):
            return "per"
    if revenue and revenue >= PSR_MIN_REVENUE:
        return "psr"
    return "abs"                                # 매출이 미미하면 공모시총 절대값으로 본다


FIELD = {"per": "ipo_per", "psr": "ipo_psr", "abs": "ipo_market_cap_krw"}


def _usable(c: dict, metric: str) -> bool:
    v = c.get(FIELD[metric])
    if v is None or v <= 0:
        return False
    if metric == "per" and v > 300:             # 이익이 0에 가까워 배수가 튄 건 제외
        return False
    if metric == "psr" and v > 100:
        return False
    return True


def _band(c: dict, revenue: float, mult: float) -> bool:
    r = c.get("revenue_krw")
    return bool(r and revenue / mult <= r <= revenue * mult)


def select(sector_tag: str, revenue: float | None, profitable: bool,
           metric: str, *, include_expected: bool = True) -> dict:
    """조건을 단계적으로 풀면서 최소 5곳을 채운다. 어디까지 풀었는지 함께 돌려준다."""
    pool = [c for c in dataset.companies() if _usable(c, metric)]
    if not include_expected:
        pool = [c for c in pool if not c.get("expected_ipo")]

    peers = group_peers(sector_tag)
    group_label = GROUP_LABEL.get(GROUP_OF.get(sector_tag, ""), "전체")
    same_sector = [c for c in pool if c.get("sector_tag") == sector_tag]
    same_pnl = [c for c in same_sector if bool(c.get("profitable")) == profitable]
    grp = [c for c in pool if c.get("sector_tag") in peers]
    grp_pnl = [c for c in grp if bool(c.get("profitable")) == profitable]

    ladder: list[tuple[str, list[dict]]] = []
    if revenue:
        ladder.append((f"같은 업종·매출 {NEAR:.0f}배 이내·손익 같음",
                       [c for c in same_pnl if _band(c, revenue, NEAR)]))
        ladder.append((f"같은 업종·매출 {WIDE:.0f}배 이내·손익 같음",
                       [c for c in same_pnl if _band(c, revenue, WIDE)]))
    ladder.append(("같은 업종·손익 같음", same_pnl))
    if revenue:
        ladder.append((f"{group_label} 업종군·매출 {NEAR:.0f}배 이내·손익 같음",
                       [c for c in grp_pnl if _band(c, revenue, NEAR)]))
        ladder.append((f"{group_label} 업종군·매출 {WIDE:.0f}배 이내·손익 같음",
                       [c for c in grp_pnl if _band(c, revenue, WIDE)]))
    ladder.append((f"{group_label} 업종군·손익 같음", grp_pnl))
    ladder.append((f"{group_label} 업종군(손익 무관)", grp))
    if revenue:
        ladder.append((f"업종 무관·매출 {NEAR:.0f}배 이내·손익 같음",
                       [c for c in pool if bool(c.get("profitable")) == profitable
                        and _band(c, revenue, NEAR)]))
    ladder.append(("업종 무관·손익 같음",
                   [c for c in pool if bool(c.get("profitable")) == profitable]))

    for i, (label, sub) in enumerate(ladder):
        if len(sub) >= MIN_COMPS:
            return {"comps": sub, "criteria": label, "relaxed": i > 0,
                    "relaxed_steps": i, "metric": metric, "pool_size": len(pool),
                    "scope": _scope(sub, sector_tag, group_label)}
    label, sub = max(ladder, key=lambda x: len(x[1]))
    return {"comps": sub, "criteria": label + " (표본 부족)", "relaxed": True,
            "relaxed_steps": len(ladder), "metric": metric, "pool_size": len(pool),
            "scope": _scope(sub, sector_tag, group_label)}


def _scope(sub: list[dict], sector_tag: str, group_label: str) -> str:
    """비교기업이 실제로 어느 범위에서 왔는지. 메인 글에 이 문구를 그대로 쓴다.

    사용자 업종 이름을 그냥 붙이면 표본에 그 업종이 0곳인데도 "화장품 5곳 기준"이라고
    쓰게 된다. 실제 구성으로 판단한다.
    """
    from .dataset import SECTOR_LABEL
    tags = {c.get("sector_tag") for c in sub}
    if tags == {sector_tag}:
        return SECTOR_LABEL.get(sector_tag, sector_tag)
    if tags <= set(group_peers(sector_tag)):
        return group_label
    return "코스닥"


# 보수/기준/낙관에 쓰는 백분위. p25~p75는 실제 공모시총을 41%밖에 못 담아서
# 백테스트로 폭을 넓혔다 (p10~p90 = 67%). builder/backtest.py 참고.
LOW_Q, MID_Q, HIGH_Q = 0.10, 0.50, 0.90
# 비교기업이 몇 곳뿐이면 p10·p90이 극단값 하나에 끌려간다. 중앙값 대비 4배로 자른다.
# 백테스트상 범위 적중률은 그대로(67.3%)라 공짜로 얻는 안전장치다.
FAN_CAP = 4.0


def quantile(vals: list[float], p: float) -> float:
    vals = sorted(vals)
    if len(vals) == 1:
        return vals[0]
    i = p * (len(vals) - 1)
    lo, hi = int(i), min(int(i) + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (i - lo)


def percentiles(comps: list[dict], metric: str) -> dict:
    vals = [c[FIELD[metric]] for c in comps]
    if not vals:
        return {}
    mid = quantile(vals, MID_Q)
    low = max(quantile(vals, LOW_Q), mid / FAN_CAP)
    high = min(quantile(vals, HIGH_Q), mid * FAN_CAP)
    return {"low": low, "mid": mid, "high": high, "n": len(vals),
            "low_q": LOW_Q, "high_q": HIGH_Q, "fan_cap": FAN_CAP}


def median_of(comps: list[dict], field: str) -> float | None:
    vals = sorted(c[field] for c in comps if c.get(field) is not None)
    if not vals:
        return None
    m = len(vals) // 2
    return vals[m] if len(vals) % 2 else (vals[m - 1] + vals[m]) / 2


def spread_of(comps: list[dict], field: str) -> dict | None:
    """분포의 p25·중앙값·p75와 플러스로 끝난 비율.

    상장 후 주가는 한쪽으로 쏠려 있지 않다. 중앙값 하나만 내보내면 -16%라는
    음수 한 개가 결과의 전부가 되는데, 실제로는 4곳 중 1곳 이상이 공모가를
    크게 웃돈다. 한쪽만 보여주는 것도 틀리게 보여주는 것이다.
    """
    vals = sorted(c[field] for c in comps if c.get(field) is not None)
    if len(vals) < MIN_COMPS:
        return None
    return {"p25": quantile(vals, 0.25), "median": quantile(vals, 0.50),
            "p75": quantile(vals, 0.75), "n": len(vals),
            "positive_rate": sum(1 for v in vals if v > 0) / len(vals)}
