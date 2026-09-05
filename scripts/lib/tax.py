"""세금 — 벤처기업 스톡옵션 비과세 한도, 근로소득세 누진, 증권거래세.

수치는 전부 data/tax_params.json 에서 읽는다. 값이 없으면 계산을 멈추고 이유를 남긴다.
"""
from __future__ import annotations

from . import dataset


class TaxDataMissing(RuntimeError):
    pass


def _get(path: str, *, required: bool = True):
    node: object = dataset.tax_params()
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            if required:
                raise TaxDataMissing(f"tax_params.json 에 {path} 가 없습니다")
            return None
        node = node[key]
    if node is None and required:
        raise TaxDataMissing(f"tax_params.json 의 {path} 값이 비어 있습니다")
    return node


def income_tax(taxable: float) -> float:
    """근로소득 과세표준 → 소득세 + 지방소득세."""
    if taxable <= 0:
        return 0.0
    brackets = _get("income_tax_brackets")
    rate, deduction = brackets[-1]["rate"], brackets[-1]["deduction_krw"]
    for b in brackets:
        cap = b.get("upto_krw")
        if cap is None or taxable <= cap:
            rate, deduction = b["rate"], b["deduction_krw"]
            break
    national = max(0.0, taxable * rate - deduction)
    local = national * float(_get("local_income_tax_rate"))
    return national + local


def exercise_tax(gain: float, other_income: float = 0.0, *, venture: bool = True) -> dict:
    """스톡옵션 행사이익에 붙는 세금.

    행사이익은 근로소득이다. 벤처기업 특례 비과세 한도까지는 세금이 없고,
    초과분이 다른 근로소득 위에 얹혀 누진세율을 맞는다(한계세율 방식).
    """
    if gain <= 0:
        return {"taxable": 0.0, "tax": 0.0, "exempt": 0.0, "effective_rate": 0.0}
    # 연간 한도와 기업별 누적 한도 중 작은 쪽. 상장 때 한 번에 행사하는 상황을 가정하므로
    # 보통 연간 한도가 먼저 걸린다.
    if venture:
        annual = float(_get("venture_option_tax_free.annual_limit_krw"))
        cum = _get("venture_option_tax_free.cumulative_limit_krw", required=False)
        limit = min(annual, float(cum)) if cum else annual
    else:
        limit = 0.0
    exempt = min(gain, limit)
    taxable = gain - exempt
    tax = income_tax(other_income + taxable) - income_tax(other_income)
    return {"taxable": taxable, "tax": tax, "exempt": exempt,
            "effective_rate": tax / gain if gain else 0.0}


def transfer_tax(proceeds: float) -> float:
    """코스닥 장내 매도 증권거래세(농특세 포함 총률)."""
    if proceeds <= 0:
        return 0.0
    return proceeds * float(_get("securities_transaction_tax.kosdaq_rate"))


def discount_rate() -> tuple[float, str]:
    """현재가치 할인율 — 한국은행 기준금리."""
    r = _get("base_interest_rate.rate")
    label = _get("base_interest_rate.name", required=False) or "한국은행 기준금리"
    as_of = _get("base_interest_rate.as_of", required=False) or ""
    return float(r), f"{label} 연 {float(r):.2%}" + (f" ({as_of} 기준)" if as_of else "")


def lockup_months(*, major_shareholder: bool = False, tech_track: bool = False) -> int:
    """상장 후 못 파는 기간(개월).

    코스닥 의무보유는 **최대주주등**에게 걸린다. 지분이 미미한 일반 직원은 대상이 아니어서
    0개월이 정상이다. 이 사실 자체가 사용자에게 필요한 정보라 결과에 그대로 적는다.
    """
    if not major_shareholder:
        return 0
    node = _get("kosdaq_ipo_lockup", required=False) or {}
    key = "largest_shareholder_months_tech_growth" if tech_track else "largest_shareholder_months"
    return int(node.get(key) or 0)
