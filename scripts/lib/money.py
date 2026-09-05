"""금액·비율 표기. 결과 문자열에는 항상 단위를 붙인다."""
from __future__ import annotations

JO = 1_000_000_000_000
EOK = 100_000_000
MAN = 10_000


def krw(v: float | None, *, dash: str = "—", signed: bool = False) -> str:
    """원 단위 정수를 사람이 읽는 한국어 금액으로.

    1만 미만 → 3,000원 / 1억 미만 → 2,990만원 / 100억 미만 → 1억800만원 / 이상 → 550억원

    signed=True면 음수를 "-5,495만원"으로 그대로 보여준다. 손익처럼 마이너스가 정보인
    자리에 쓴다. 기본값은 0원으로 눌러 옵션 가치가 음수로 찍히지 않게 한다.
    """
    if v is None:
        return dash
    v = round(v)
    if v < 0:
        return ("-" + krw(-v)) if signed else "0원"
    if v < MAN:
        return f"{v:,}원"
    if v < EOK:
        man = round(v / MAN)
        if man >= 10_000:          # 9,999.9만원이 반올림으로 1억이 되는 경계
            return "1억원"
        return f"{man:,}만원"
    if v < 100 * EOK:
        eok, rest = divmod(v, EOK)
        man = round(rest / MAN)
        if man >= 10_000:          # 반올림이 1억을 넘어서면 올림 처리
            eok, man = eok + 1, 0
        return f"{eok:,}억원" if man == 0 else f"{eok:,}억{man:,}만원"
    if v < JO:
        eok = round(v / EOK)
        if eok >= 10_000:          # 9,999.5억원이 반올림으로 1조가 되는 경계
            return "1조원"
        return f"{eok:,}억원"
    jo, rest = divmod(v, JO)
    eok = round(rest / EOK)
    if eok >= 10_000:
        jo, eok = jo + 1, 0
    return f"{jo:,}조원" if eok == 0 else f"{jo:,}조{eok:,}억원"


def won(v: float | None, *, dash: str = "—") -> str:
    """주당 가격처럼 원 단위 그대로 보여줄 때."""
    return dash if v is None else f"{round(v):,}원"


def pctstr(v: float | None, digits: int = 0, *, dash: str = "—") -> str:
    return dash if v is None else f"{v * 100:.{digits}f}%"


def multiple(v: float | None, *, dash: str = "—") -> str:
    return dash if v is None else f"{v:.1f}배"
