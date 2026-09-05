"""공모 시총·주당가 3시나리오."""
from __future__ import annotations

from . import comps as comps_mod
from . import dataset

SCEN = ("보수", "기준", "낙관")
QKEY = {"보수": "low", "기준": "mid", "낙관": "high"}
METRIC_LABEL = {"per": "PER", "psr": "PSR", "abs": "공모시총"}


# 최근 코스닥 공모가는 거의 전부 이 구간 안에 들어온다(데이터셋 p05~p95).
PRICE_LOW, PRICE_HIGH = 3_000, 60_000


MAX_ROUND_MULTIPLE = 10.0


def _fan_collapsed(caps: dict) -> bool:
    """세 시나리오가 사실상 한 값으로 뭉쳤는지. 라벨이 무의미해지면 그렇다고 적는다."""
    lo, mid, hi = (caps.get(k) for k in SCEN)
    if not (lo and mid and hi):
        return False
    return (mid / lo) < 1.3 or (hi / mid) < 1.3


# 매출 없이 상장하는 것이 업계 표준인 업종. 여기서는 파이프라인·기술로 값이 매겨지므로
# 공모시총 분포를 그대로 쓰는 것이 실제 평가 방식과 맞는다.
PRE_REVENUE_OK = {"bio_health"}


def _scale_check(sector_tag: str, founded_year: int | None, revenue: float | None,
                 last_round_krw: float | None, cap: float | None) -> str | None:
    """공모시총 분포를 그대로 쓰는 경로에서, 그 분포에 낄 규모가 맞는지 본다.

    이 경로는 회사 숫자를 안 쓴다. 크기를 알려주는 값이 하나도 없으면 매출 3억짜리
    회사가 코스닥 상장사 중앙값 1,686억원을 그대로 받는다. 그래서 규모를 확인할
    근거가 있을 때만 값을 낸다.
    """
    if cap is None:
        return None
    if last_round_krw:
        if cap > last_round_krw * MAX_ROUND_MULTIPLE:
            return (f"최근 투자 밸류에이션({last_round_krw / 1e8:,.0f}억원)의 "
                    f"{MAX_ROUND_MULTIPLE:.0f}배가 넘는 시총이 나왔습니다. 회사 실적이 "
                    "계산에 들어가지 않는 방식이라 이 숫자는 믿을 수 없습니다.")
        return None
    if sector_tag in PRE_REVENUE_OK:
        return None      # 임상 단계 바이오는 매출 없이 상장하는 것이 정상이다
    return ("매출이 30억원에 못 미치는데 최근 투자 밸류에이션도 없어, 회사 규모를 가늠할 "
            "근거가 없습니다. 이 방식은 상장사 공모시총 분포를 그대로 옮기는 것이라 "
            "규모 확인 없이는 숫자를 내지 않습니다. 최근 라운드 밸류에이션과 주당 가격을 "
            "넣으면 다시 계산합니다.")


def _split_hint(price: float | None) -> dict | None:
    """주당가가 실제 공모가 범위 밖이면 액면분할·병합 배수를 제안한다."""
    if not price or PRICE_LOW <= price <= PRICE_HIGH:
        return None
    target = 20_000
    ratio = price / target
    if ratio > 1:
        factor = min(1000, max(2, round(ratio)))
        return {"direction": "split", "factor": factor,
                "price_after": price / factor,
                "message": f"주당 {price:,.0f}원은 최근 코스닥 공모가 범위(3천~6만원) 위입니다. "
                           f"상장 전에 1주를 {factor:,}주로 액면분할하면 주당 "
                           f"{price / factor:,.0f}원, 보유 수량은 {factor:,}배가 됩니다."}
    factor = min(1000, max(2, round(1 / ratio)))
    return {"direction": "merge", "factor": factor,
            "price_after": price * factor,
            "message": f"주당 {price:,.0f}원은 최근 코스닥 공모가 범위(3천~6만원) 아래입니다. "
                       f"{factor:,}주를 1주로 병합하면 주당 {price * factor:,.0f}원이 됩니다."}


DEFAULT_NEW_SHARE_RATIO = 0.20


def _median_new_share_ratio(pool: list[dict]) -> tuple[float, bool]:
    """비교기업의 신주비율 중앙값. 못 구하면 기본값을 쓰고 그 사실을 함께 돌려준다."""
    v = comps_mod.median_of(pool, "new_share_ratio")
    if v and 0 < v < 1.5:
        return v, False
    return DEFAULT_NEW_SHARE_RATIO, True


def estimate(*, sector_tag: str, revenue: float | None, net_income: float | None,
             operating_income: float | None, profitable: bool,
             shares_outstanding: int | None, founded_year: int | None = None,
             last_round_krw: float | None = None) -> dict:
    metric = comps_mod.pick_metric(revenue, net_income, profitable)
    metric_note = None
    if metric == "psr" and comps_mod.thin_margin(revenue, net_income):
        metric_note = (
            f"이익 {net_income / 1e8:,.0f}억원은 매출 {revenue / 1e8:,.0f}억원의 "
            f"{net_income / revenue * 100:.1f}%뿐이라 PER 대신 매출 배수(PSR)로 계산했습니다. "
            "얇은 이익에 PER을 곱하면 회사 규모와 무관한 시총이 나옵니다.")
    sel = comps_mod.select(sector_tag, revenue, profitable, metric)
    pool = sel["comps"]
    if not pool:
        raise ValueError("비교할 만한 최근 상장사를 찾지 못했습니다.")
    q = comps_mod.percentiles(pool, metric)
    base = {"per": net_income, "psr": revenue, "abs": None}[metric]

    caps: dict[str, float | None] = {}
    for name in SCEN:
        mult = q[QKEY[name]]
        caps[name] = float(mult) if metric == "abs" else (float(mult) * base if base else None)

    basis_note = None
    scale_warning = None
    per_basis_note = None
    if metric == "per":
        # 순이익은 사용자가 알기 어렵고 해마다 크게 흔들려 영업이익에 곱한다. 정확도를 일부
        # 포기한 결정이라 그 사실을 결과에 적는다 (methodology.md §2).
        per_basis_note = ("PER은 영업이익에 곱했습니다. 비교기업 PER은 순이익 기준이라 "
                          "시총이 대체로 그만큼 높게 나옵니다.")
    if metric == "abs":
        scale_warning = _scale_check(sector_tag, founded_year, revenue, last_round_krw,
                                     caps.get("기준"))
        if scale_warning:
            # 시총을 내지 않았다. "분포를 그대로 썼다"는 문장도 함께 빠져야 한다.
            for k in SCEN:
                caps[k] = None
        else:
            basis_note = ("매출이 30억원에 못 미쳐 회사 실적 대신 같은 업종 상장사의 "
                          "공모시총 분포를 그대로 씁니다. 이 시총에는 우리 회사 숫자가 "
                          "들어가지 않았습니다.")

    ratio, ratio_is_default = _median_new_share_ratio(pool)
    shares_at_ipo = int(round(shares_outstanding * (1 + ratio))) if shares_outstanding else None
    per_share = {k: (v / shares_at_ipo if v and shares_at_ipo else None) for k, v in caps.items()}

    # 메인 글에 찍히는 값은 기준 주당가다. 낙관 주당가로 만든 분할 배수를 그 밑에 붙이면
    # 읽는 사람이 기준 주당가를 나눠 본다.
    split = _split_hint(per_share.get("기준"))
    ret6 = comps_mod.median_of(pool, "ret_6m")
    ret6_n = sum(1 for c in pool if c.get("ret_6m") is not None)
    ret6_spread = comps_mod.spread_of(pool, "ret_6m")
    cap6 = {k: (v * (1 + ret6) if v and ret6 is not None else None) for k, v in caps.items()}

    # 주관사 방식 — 신고서에서 뽑은 배수가 우리가 쓰는 배수와 같은 종류일 때만.
    # PER 배수를 매출에 곱하면 아무 뜻도 없는 숫자가 나온다.
    want = {"per": "PER", "psr": "PSR"}.get(metric)
    with_filing = [c for c in pool if c.get("applied_multiple") and c.get("discount_low")
                   and want and c.get("valuation_method") == want]
    underwriter = None
    if len(with_filing) >= 5 and base:
        mult = comps_mod.median_of(with_filing, "applied_multiple")
        d_lo = comps_mod.median_of(with_filing, "discount_low")
        d_hi = comps_mod.median_of(with_filing, "discount_high")
        if mult and d_lo is not None and d_hi is not None:
            value = mult * base
            underwriter = {"n": len(with_filing), "multiple": mult, "valuation_krw": value,
                           "discount_low": d_lo, "discount_high": d_hi,
                           "band_low_krw": value * (1 - d_hi), "band_high_krw": value * (1 - d_lo)}

    return {
        "metric": metric, "metric_label": METRIC_LABEL[metric], "metric_note": metric_note,
        "per_basis_note": per_basis_note,
        "multiples": {k: q[QKEY[k]] for k in SCEN}, "quartiles": q,
        "criteria": sel["criteria"], "relaxed": sel["relaxed"], "relaxed_steps": sel["relaxed_steps"],
        "sector_thin": sel.get("sector_thin"),
        "comps_scope": sel["scope"],
        "comps_n": len(pool),
        # 업종을 함께 준다. 이름만 주면 LLM이 기억으로 회사를 짐작하거나, 자동차부품 회사를
        # 물류 회사의 비교기업이라고 그냥 읽어 넘긴다.
        "comps": [{"name": c["name"], "code": c["code"], "listing_date": c["listing_date"],
                   "industry": c.get("industry_naver"), "industry_detail": c.get("industry_38"),
                   "revenue_krw": c.get("revenue_krw"), "value": c[comps_mod.FIELD[metric]],
                   "ret_6m": c.get("ret_6m")} for c in sorted(pool, key=lambda c: c["listing_date"], reverse=True)],
        "market_cap_krw": caps,
        "market_cap_6m_krw": cap6,
        "median_ret_6m": ret6, "ret_6m_n": ret6_n, "ret_6m_spread": ret6_spread,
        "fan_collapsed": _fan_collapsed(caps),
        "basis_note": basis_note,
        "scale_warning": scale_warning,
        "new_share_ratio": ratio,
        "new_share_ratio_is_default": ratio_is_default,
        "split_hint": split,
        "comps_thin": len(pool) < 8,
        "shares_at_ipo": shares_at_ipo,
        "price_per_share": per_share,
        "underwriter_method": underwriter,
        "revenue_krw": revenue, "net_income_krw": net_income,
        "operating_income_krw": operating_income,
    }
