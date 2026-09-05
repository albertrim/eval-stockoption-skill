"""Threads 게시글 포맷 — 메인 1개(500자 이내) + 근거 답글."""
from __future__ import annotations

from . import dataset
from .money import krw, multiple, pctstr, won
from .valuate import SCEN

LIMIT = 500
TRIPLE = " / "
MID = "기준"      # 메인 글은 기준 시나리오 하나만 쓴다. 범위는 답글에 남긴다.


def _all_zero(opt: dict) -> bool:
    return all(not (s or {}).get("after_tax_krw") for s in opt["scenarios"].values())


def _zero_reason(opt: dict) -> str:
    """0원이 나온 이유. 이유 없이 0원만 보여주면 오해한다."""
    if all(v is None for v in
           ((s or {}).get("price_per_share") for s in opt["scenarios"].values())):
        return "예상 시총을 계산하지 않아 옵션 가치도 내지 못했습니다"
    if opt.get("quantity_at_ipo") == 0:
        return "상장 예상 시점에 아직 행사할 수 있는 물량이 없습니다"
    best = (opt["scenarios"].get("낙관") or {}).get("price_per_share")
    if best and opt["strike_krw"] >= best:
        return f"행사가 {won(opt['strike_krw'])}이 낙관 시나리오 주당가 {won(best)}보다 높습니다"
    return "계산 결과가 0원입니다"


def _krw_signed(v):
    return krw(v, signed=True)


def _triple(values: dict, fmt) -> str:
    return TRIPLE.join(fmt(values.get(k)) for k in SCEN)


def _mid(values: dict, fmt) -> str:
    return fmt(values.get(MID))


def main_post(result: dict) -> str:
    c = result["company"]
    pred, val = result["prediction"], result["valuation"]
    opt = result.get("option")
    lines = ["🏢 우리 회사가 코스닥 가면?"]
    prob = pctstr(pred["probability"])
    if pred["probability_is_estimate"]:
        prob += "(추정)"
    lines.append(f"· 상장 가능성 {prob} · {pred['stage_label']}")
    lines.append(f"· 예상 상장 {pred['expected_ipo_label']}")
    if val["market_cap_krw"].get(MID) is not None:
        lines.append(f"· 예상 시총 {_mid(val['market_cap_krw'], krw)}")
    else:
        lines.append("· 예상 시총 — 계산하지 않았습니다")
    if val["price_per_share"].get(MID):
        lines.append(f"· 주당 {_mid(val['price_per_share'], won)}")
    if val.get("split_hint"):
        lines.append(f"· ({val['split_hint']['factor']}:1 액면분할 가정 시 "
                     f"{won(val['split_hint']['price_after'])})"
                     if val["split_hint"]["direction"] == "split" else
                     f"· ({val['split_hint']['factor']}주 병합 가정 시 "
                     f"{won(val['split_hint']['price_after'])})")

    if opt and not opt["expired_before_ipo"] and _all_zero(opt):
        lines += ["", f"내 스톡옵션 {opt['quantity']:,}주 (행사가 {won(opt['strike_krw'])}) → 0원",
                  "· " + _zero_reason(opt)]
    elif opt and not opt["expired_before_ipo"]:
        sc = opt["scenarios"]
        after = {k: sc[k].get("after_tax_krw") for k in SCEN}
        pv = {k: sc[k].get("present_value_krw") for k in SCEN}
        held = opt["quantity"]
        usable = opt["quantity_at_ipo"]
        head = (f"내 스톡옵션 {held:,}주 (행사가 {won(opt['strike_krw'])})" if usable >= held
                else f"내 스톡옵션 {held:,}주 중 상장 시점 행사 가능 {usable:,}주 "
                     f"(행사가 {won(opt['strike_krw'])})")
        lines += ["", head,
                  f"· 세후 손에 쥐는 돈 {_mid(after, krw)}",
                  f"· 오늘 기준으로 당기면 {_mid(pv, krw)}"]
        if opt.get("ownership_pct"):
            lines.append(f"· 지분 {pctstr(opt['ownership_pct'], 2)}")
    elif opt:
        lines += ["", f"내 스톡옵션 {opt['quantity']:,}주 → 0원",
                  f"· 행사 기간이 {opt['expiry_date']}에 끝납니다",
                  f"· 상장 예상은 {pred['expected_ipo_date']}"]

    scope = val.get("comps_scope") or "코스닥"
    tail = (f"최근 코스닥 상장 {val['comps_n']}곳 기준" if scope == "코스닥"
            else f"최근 코스닥 상장 {scope} {val['comps_n']}곳 기준")
    lines += ["", f"⚠️ 재미로 보는 추정. {tail}.", "#스톡옵션 #코스닥 #IPO"]
    return "\n".join(lines)


def _comp_label(c: dict) -> str:
    """이름 옆에 업종을 붙인다. 이름만 적으면 자동차부품 회사가 물류 회사의 비교기업으로 그냥 지나간다."""
    ind = c.get("industry")
    return f"{c['name']}({ind})" if ind else c["name"]


def _comps_reply(result: dict) -> str:
    val = result["valuation"]
    names = ", ".join(_comp_label(c) for c in val["comps"][:8])
    more = f" 외 {val['comps_n'] - 8}곳" if val["comps_n"] > 8 else ""
    q = val["quartiles"]
    if val["metric"] == "abs":
        band = f"공모시총 {krw(q['low'])} / {krw(q['mid'])} / {krw(q['high'])}"
    elif val["metric"] == "per":
        band = f"PER(영업이익 기준) {multiple(q['low'])} / {multiple(q['mid'])} / {multiple(q['high'])}"
    else:
        band = (f"{val['metric_label']} {multiple(q['low'])} / {multiple(q['mid'])} / "
                f"{multiple(q['high'])}")
    r = [f"[비교기업 {val['comps_n']}곳] {names}{more}", f"기준: {val['criteria']}", band]
    if val.get("metric_note"):
        r.append(val["metric_note"])
    if val.get("per_basis_note"):
        r.append(val["per_basis_note"])
    thin = val.get("sector_thin")
    if thin:
        r.append(f"이 업종은 최근 5년 코스닥 상장이 {thin['n']}곳뿐이라 {thin['group']} 업종군에서 골랐습니다.")
    # 몇 단계나 넓혔는지는 결과를 얼마나 믿을지 가른다. "넓혔습니다" 한 줄로는 안 보인다.
    steps = val.get("relaxed_steps") or 0
    if val["relaxed"]:
        start = (f"{thin['group']} 업종군·매출 3배 이내로는" if thin
                 else "같은 업종·매출 3배 이내로는")
        msg = f"{start} 5곳을 못 채워 조건을 {steps}단계 넓혔습니다."
        if val.get("comps_scope") == "코스닥":
            msg += " 업종을 넘어 코스닥 전체에서 고른 표본이라 이 업종의 배수라고 보기 어렵습니다."
        elif "손익 무관" in (val.get("criteria") or ""):
            msg += " 흑자·적자를 가리지 않고 넣은 표본이라 배수가 한쪽으로 치우칠 수 있습니다."
        elif steps >= 3:
            msg += " 업종군까지 넘어간 표본이라 이 업종의 배수라고 보기 어렵습니다."
        r.append(msg)
    if val.get("comps_thin"):
        r.append(f"비교기업이 {val['comps_n']}곳뿐이라 보수·낙관 값은 몇 곳에 크게 좌우됩니다.")
    if val.get("fan_collapsed"):
        r.append("비교기업 배수가 좁게 몰려 있어 보수·기준·낙관 차이가 크지 않습니다.")
    u = val.get("underwriter_method")
    if u:
        r.append(f"주관사 방식으로 보면 평가액 {krw(u['valuation_krw'])} "
                 f"× 할인 {pctstr(u['discount_low'])}~{pctstr(u['discount_high'])} "
                 f"→ {krw(u['band_low_krw'])}~{krw(u['band_high_krw'])} (신고서 {u['n']}건)")
    return "\n".join(r)


def _range_reply(result: dict) -> str:
    """메인 글이 기준값 하나만 보여주므로, 폭은 여기서 반드시 알린다."""
    val, opt = result["valuation"], result.get("option")
    caps, pps = val["market_cap_krw"], val["price_per_share"]
    r = []
    if caps.get("보수") and caps.get("낙관"):
        span = f"[범위] 위 숫자는 기준 시나리오 하나입니다. 시총 {krw(caps['보수'])}~{krw(caps['낙관'])}"
        if pps.get("보수") and pps.get("낙관"):
            span += f", 주당 {won(pps['보수'])}~{won(pps['낙관'])}"
        r.append(span + "까지 벌어집니다(비교기업 배수 하위 10%~상위 90%). 최악·최선이 아닙니다.")
    if opt and not _all_zero(opt):
        a = {k: opt["scenarios"][k].get("after_tax_krw") for k in SCEN}
        if a.get("보수") and a.get("낙관"):
            r.append(f"같은 폭으로 세후 가치는 {krw(a['보수'])}~{krw(a['낙관'])}입니다.")
    r.append(f"[가정] 상장 때 신주를 {pctstr(val['new_share_ratio'])} 더 찍는다고 봤습니다"
             f"({val['shares_at_ipo']:,}주 기준)." if val.get("shares_at_ipo") else "[가정]")
    if val.get("median_ret_6m") is not None:
        # 시장 전체가 아니라 비교기업의 값이다. "최근 상장사는"이라고 쓰면 전체로 읽힌다.
        n6 = val.get("ret_6m_n") or val["comps_n"]
        r.append(f"참고로 비교기업 {n6}곳의 공모가 대비 6개월 뒤 수익률 중앙값은 "
                 f"{pctstr(val['median_ret_6m'], 1)}입니다.")
    if val.get("split_hint"):
        r.append(val["split_hint"]["message"])
    return "\n".join(r)


def _method_reply(result: dict) -> str:
    """할인·세금·모델 오차. 범위 답글과 합치면 500자를 넘는다."""
    val, opt = result["valuation"], result.get("option")
    r = []
    if opt:
        r.append(f"[계산] 지금 가치는 {opt['discount_label']}로 {opt['discount_years']}년 할인했습니다.")
        sc = opt["scenarios"].get("기준", {})
        if sc.get("gross_krw"):
            head = (f"세금(기준 시나리오)은 벤처기업 비과세 {krw(sc['tax_free_krw'])} 적용 후 "
                    if opt.get("is_venture")
                    else "세금(기준 시나리오)은 벤처기업 비과세 없이 ")
            r.append(head + f"소득세 {krw(sc['income_tax_krw'])} + "
                            f"증권거래세 {krw(sc['transfer_tax_krw'])}.")
            if not opt.get("is_venture"):
                r.append("벤처기업 인증이 있으면 행사이익 연 2억원까지 비과세라 세금이 크게 줄어듭니다.")
    bt = result.get("backtest") or {}
    if bt.get("n"):
        r.append(f"{'' if opt else '[계산] '}이 방식으로 실제 상장사 {bt['n']}곳을 거꾸로 맞혀보면 "
                 f"시총 오차 중앙값 {pctstr(bt['mape_median'])}, 보수~낙관 범위 안에 들어간 비율은 "
                 f"{pctstr(bt['inside_rate'])}입니다.")
    if val.get("basis_note"):
        r.append(val["basis_note"])
    r.append(f"데이터 기준일 {dataset.data_as_of()}.")
    return "\n".join(r)


def _probability_reply(result: dict) -> str:
    pred = result["prediction"]
    r = [f"[상장 가능성 근거] {pred['rate_basis']} 예비심사 {pred['sample_n']}건 중 "
         f"승인 {pctstr(pred['approval_rate'])}, 승인 뒤 상장 {pctstr(pred['listing_rate_given_approval'])}."]
    r.append(f"트랙: {pred['track']}")
    gate = result.get("listing_gate") or {}
    if gate.get("verdict") == "미달":
        # 근거를 덮어쓰지 않고 앞에 붙인다. 승인율·트랙 정보는 그대로 남아야 한다.
        r = ["[상장요건] " + n for n in gate["notes"]] + r
    elif gate.get("verdict") == "규모 미확인":
        # 시총을 못 낸 것이지 요건에 못 미친 것이 아니다. 상장요건이라고 적지 않는다.
        r = ["[규모 미확인] " + n for n in gate["notes"]] + r
    peers = result.get("peers_in_review") or []
    if peers:
        p = peers[0]
        r.append(f"비슷한 규모로 지금 심사 중: {p['name']}"
                 f"(매출 {krw(p['revenue_krw'])}, {p['filed_date']} 청구, {p['status']})")
    return "\n".join(r)


def _option_reply(result: dict) -> str:
    opt, pred = result["option"], result["prediction"]
    sc = opt["scenarios"]
    a6 = {k: sc[k].get("after_tax_6m_krw") for k in SCEN}
    cost = sc.get("기준", {}).get("exercise_cost_krw")
    r = []
    if cost and not _all_zero(opt):
        r.append(f"[행사할 때 드는 돈] {krw(cost)} (행사가 × 행사 수량). "
                 "이 돈을 먼저 내야 주식이 됩니다.")
    # 6개월 뒤 주가는 한쪽으로 쏠려 있지 않다. 중앙값 하나만 적으면 음수 한 개가
    # 결과의 전부가 되는데, 실제로는 3곳 중 1곳 이상이 공모가를 넘긴다.
    sp = opt.get("ret_6m_spread") or {}
    mid6 = sc.get("기준", {})
    lo6, hi6 = mid6.get("after_tax_6m_low_krw"), mid6.get("after_tax_6m_high_krw")
    has_spread = all(sp.get(k) is not None for k in ("p25", "p75", "n", "positive_rate"))
    if (any(v for v in a6.values()) and opt.get("median_ret_6m") is not None
            and not _all_zero(opt)):
        line = (f"[상장 6개월 뒤에 판다면] 기준 시나리오로 "
                f"{_krw_signed(mid6.get('after_tax_6m_krw'))}.")
        if has_spread:
            line += (f" 최근 상장사 {sp['n']}곳의 6개월 수익률은 "
                     f"하위 25% {pctstr(sp['p25'], 1)} · 중앙값 {pctstr(opt['median_ret_6m'], 1)} · "
                     f"상위 25% {pctstr(sp['p75'], 1)}로 갈렸고, "
                     f"{pctstr(sp['positive_rate'])}는 공모가를 넘겼습니다.")
            if lo6 is not None and hi6 is not None:
                line += f" 같은 폭을 적용하면 {_krw_signed(lo6)} ~ {_krw_signed(hi6)}입니다."
        else:
            line += f" 최근 상장사 중앙값 {pctstr(opt['median_ret_6m'], 1)}를 적용한 값입니다."
        line += " 세금은 공모가 기준으로 이미 정해지니, 주가가 빠지면 그만큼 손해입니다."
        r.append(line)
    if opt.get("quantity_6m") and opt["quantity_6m"] > opt["quantity_at_ipo"]:
        r.append(f"위 6개월 숫자는 그때까지 행사 가능해지는 {opt['quantity_6m']:,}주 기준입니다"
                 f"(상장 시점 {opt['quantity_at_ipo']:,}주).")
    r.append(f"[행사 가능] 오늘 {opt['quantity_today']:,}주"
             f"({pctstr(opt['vested_today_pct'])}), 상장 예상 시점 {opt['quantity_at_ipo']:,}주"
             f"({pctstr(opt['vested_at_ipo_pct'])}).")
    if opt.get("expiry_date"):
        r.append(f"행사 기간 만료 {opt['expiry_date']}.")
    if opt.get("ownership_pct") and opt["ownership_pct"] >= 0.01:
        r.append(f"지분 {pctstr(opt['ownership_pct'], 2)}면 최대주주등에 해당할 수 있습니다. "
                 "그 경우 상장 후 6개월(기술성장기업 1년) 의무보유가 걸립니다.")
    if opt.get("lockup_months"):
        r.append(f"상장 후 {opt['lockup_months']}개월은 팔 수 없다고 봤습니다"
                 f"(매도 가능 {opt['sellable_date']}).")
    for w in opt["warnings"]:
        r.append("⚠️ " + w)
    return "\n".join(r)


def replies(result: dict) -> list[str]:
    """답글 순서: 비교기업 → 범위·가정 → 계산 근거 → 상장 가능성 → (옵션이 있으면) 행사·6개월."""
    out = [_comps_reply(result), _range_reply(result), _method_reply(result),
           _probability_reply(result)]
    if result.get("option"):
        out.append(_option_reply(result))
    return out


def render(result: dict) -> dict:
    main = main_post(result)
    reps = replies(result)
    # Threads는 답글도 500자다. 넘긴 답글이 있으면 번호를 돌려준다.
    return {"main": main, "main_length": len(main), "over_limit": max(0, len(main) - LIMIT),
            "replies": reps, "reply_lengths": [len(r) for r in reps],
            "replies_over_limit": [i for i, r in enumerate(reps, 1) if len(r) > LIMIT]}
