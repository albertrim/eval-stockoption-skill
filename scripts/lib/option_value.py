"""스톡옵션 — 행사 가능 수량, 세후가치, 현재가치."""
from __future__ import annotations

import datetime as dt

from . import tax
from .valuate import SCEN


def _add_months(d: dt.date, months: int) -> dt.date:
    y, m = divmod(d.month - 1 + months, 12)
    year = d.year + y
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    day = min(d.day, [31, 29 if leap else 28, 31, 30, 31, 30,
                      31, 31, 30, 31, 30, 31][m])
    return dt.date(year, m + 1, day)


def vested_ratio(grant_date: str, schedule: list[dict], at: dt.date) -> float:
    """부여일 기준 일정에서 at 시점의 누적 행사 가능 비율(0~1)."""
    g = dt.date.fromisoformat(grant_date)
    best = 0.0
    for step in sorted(schedule, key=lambda s: s["after_months"]):
        if _add_months(g, int(step["after_months"])) <= at:
            best = max(best, float(step["cumulative_pct"]))
    return min(1.0, max(0.0, best))


def evaluate(*, quantity: int, strike_krw: float, grant_date: str,
             vest_schedule: list[dict], expiry_date: str | None,
             salary_krw: float | None, company_result: dict,
             is_venture: bool = True, major_shareholder: bool = False) -> dict:
    today = dt.date.today()
    pred = company_result["prediction"]
    val = company_result["valuation"]
    ipo = dt.date.fromisoformat(pred["expected_ipo_date"] + "-15")
    lockup = tax.lockup_months(major_shareholder=major_shareholder,
                               tech_track="기술성장" in (pred.get("track") or ""))
    sellable = _add_months(ipo, lockup)

    vest_today = vested_ratio(grant_date, vest_schedule, today)
    vest_ipo = vested_ratio(grant_date, vest_schedule, ipo)
    qty_today = int(round(quantity * vest_today))
    qty_ipo = int(round(quantity * vest_ipo))
    # 상장 6개월 뒤에 판다면 그 사이에 더 행사 가능해진 물량도 팔 수 있다.
    # 상장일 기준 수량을 그대로 쓰면 그만큼 빠진 값이 나온다.
    six = _add_months(ipo, 6)
    vest_6m = vested_ratio(grant_date, vest_schedule, six)
    qty_6m = int(round(quantity * vest_6m))

    warnings: list[str] = []
    expired = False
    if expiry_date:
        exp = dt.date.fromisoformat(expiry_date)
        if exp < ipo:
            expired = True
            warnings.append(
                f"행사 기간이 {exp:%Y-%m}에 끝나는데 상장 예상은 {pred['expected_ipo_date']}입니다. "
                "지금 일정대로면 상장 전에 권리가 사라집니다."
            )
        elif (exp - ipo).days < 365:
            warnings.append(f"상장 예상({pred['expected_ipo_date']})과 만료({exp:%Y-%m}) 사이가 1년이 안 됩니다.")
    own_pre = (qty_ipo / val["shares_at_ipo"]) if val.get("shares_at_ipo") else None
    if not expired and lockup == 0 and (own_pre is None or own_pre < 0.01):
        warnings.append(
            "지분이 작아 코스닥 의무보유(보호예수) 대상이 아닙니다. 상장 직후 매도 가능으로 계산했습니다."
        )
    if not expired and 0 < vest_ipo < 1.0:
        warnings.append(f"상장 예상 시점에 행사 가능한 물량은 {vest_ipo:.0%}입니다.")

    r, r_label = tax.discount_rate()
    years = max(0.0, (sellable - today).days / 365.25)
    stt_rate_note = "코스닥 증권거래세"
    ret6 = val.get("median_ret_6m")

    exp_date = dt.date.fromisoformat(expiry_date) if expiry_date else None
    # 만료가 6개월 안에 오면 그 뒤 가득분은 못 쓴다
    qty6_max = qty_ipo if (exp_date and exp_date < six) else qty_6m
    spread = val.get("ret_6m_spread") or {}

    rows: dict[str, dict] = {}
    for name in SCEN:
        price = val["price_per_share"].get(name)
        qty = 0 if expired else qty_ipo
        qty6 = 0 if expired else qty6_max
        if price is None or qty == 0:
            rows[name] = {"price_per_share": price, "quantity": qty, "gross_krw": 0.0,
                          "exercise_cost_krw": 0.0, "income_tax_krw": 0.0, "tax_free_krw": 0.0,
                          "transfer_tax_krw": 0.0, "after_tax_krw": 0.0,
                          "present_value_krw": 0.0, "after_tax_6m_krw": None,
                          "after_tax_6m_low_krw": None, "after_tax_6m_high_krw": None}
            continue
        cost = strike_krw * qty                       # 행사할 때 내 돈이 나간다
        gain = max(0.0, price - strike_krw) * qty     # 근로소득으로 과세되는 행사이익
        t = tax.exercise_tax(gain, salary_krw or 0.0, venture=is_venture)
        proceeds = price * qty
        stt = tax.transfer_tax(proceeds) if gain > 0 else 0.0
        after = max(0.0, proceeds - cost - t["tax"] - stt)

        # 상장 직후에 못 팔거나 안 팔았을 때 — 소득세는 공모가 기준으로 이미 확정된다.
        # 6개월 뒤 수익률은 한쪽으로 쏠려 있지 않아 하위 25%~상위 25%를 함께 낸다.
        def _after6(ret: float | None, *, price=price, qty6=qty6) -> float | None:
            # 공모가 기준 주당가가 행사가 아래면 애초에 행사하지 않는다. 그 경우 6개월 값도 없다.
            if ret is None or qty6 == 0 or price <= strike_krw:
                return None
            g6 = max(0.0, price - strike_krw) * qty6
            t6 = tax.exercise_tax(g6, salary_krw or 0.0, venture=is_venture)
            proceeds6 = max(0.0, price * (1 + ret) * qty6)
            return proceeds6 - strike_krw * qty6 - t6["tax"] - tax.transfer_tax(proceeds6)

        after6 = _after6(ret6)
        rows[name] = {
            "price_per_share": price,
            "quantity": qty,
            "exercise_cost_krw": cost,
            "gross_krw": gain,
            "income_tax_krw": t["tax"],
            "tax_free_krw": t["exempt"],
            "taxable_krw": t["taxable"],
            "transfer_tax_krw": stt,
            "proceeds_krw": proceeds,
            "after_tax_krw": after,
            "after_tax_6m_krw": after6,
            "after_tax_6m_low_krw": _after6(spread.get("p25")),
            "after_tax_6m_high_krw": _after6(spread.get("p75")),
            "quantity_6m": qty6,
            "present_value_krw": after / ((1 + r) ** years) if years > 0 else after,
        }

    base_ref = val["price_per_share"].get("기준")
    if not expired and base_ref and strike_krw >= base_ref:
        best = val["price_per_share"].get("낙관")
        if best and strike_krw >= best:
            warnings.append(
                f"행사가 {strike_krw:,.0f}원이 낙관 시나리오 주당가 {best:,.0f}원보다도 높습니다. "
                "세 시나리오 모두 0원입니다."
            )
        else:
            warnings.append(
                f"행사가 {strike_krw:,.0f}원이 기준 시나리오 주당가 {base_ref:,.0f}원보다 높습니다. "
                "낙관 시나리오에서만 값이 생깁니다."
            )
    if not expired and qty_ipo == 0:
        warnings.append(
            "상장 예상 시점에 행사할 수 있는 물량이 아직 0주입니다. "
            "행사 가능 일정이 그 이후에 시작합니다."
        )

    shares_at_ipo = val.get("shares_at_ipo")
    strike_ratio = None
    base_price = val["price_per_share"].get("기준")
    if base_price:
        strike_ratio = strike_krw / base_price
    return {
        "quantity": quantity, "strike_krw": strike_krw,
        "vested_today_pct": vest_today, "vested_at_ipo_pct": vest_ipo,
        "quantity_today": qty_today, "quantity_at_ipo": qty_ipo,
        "expired_before_ipo": expired, "expiry_date": expiry_date,
        "lockup_months": lockup, "sellable_date": sellable.strftime("%Y-%m"),
        "discount_rate": r, "discount_label": r_label, "discount_years": round(years, 2),
        # 지분율은 금액과 같은 수량 기준이어야 한다. 상장 시점 행사 가능분으로 센다.
        "ownership_pct": (qty_ipo / shares_at_ipo) if shares_at_ipo else None,
        "ownership_pct_if_all_vested": (quantity / shares_at_ipo) if shares_at_ipo else None,
        "strike_to_price_ratio": strike_ratio,
        "scenarios": rows,
        "warnings": warnings,
        "is_venture": is_venture,
        "major_shareholder": major_shareholder,
        "salary_krw": salary_krw,
        "median_ret_6m": val.get("median_ret_6m"),
        "ret_6m_spread": val.get("ret_6m_spread"),
        "vested_6m_pct": vest_6m, "quantity_6m": qty6_max,
    }
