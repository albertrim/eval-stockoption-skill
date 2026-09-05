#!/usr/bin/env python3
"""ipo-eval — 비상장 회사의 코스닥 상장 시나리오와 스톡옵션 가치 계산기.

표준 라이브러리만 쓴다. 계산은 전부 여기서 하고, 문장은 LLM이 붙인다.

  update check | update apply --data
  dart      --name <회사명>
  validate  --profile <이름>
  company   --profile <이름>
  option    --profile <이름> [--option N]
  format    --profile <이름> [--threads]
  profiles
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import dart, dataset, listing_rules, predict, store, threads, update, valuate  # noqa: E402
from lib import option_value as ov  # noqa: E402
from lib.tax import TaxDataMissing  # noqa: E402
from lib.validate import validate_company, validate_option  # noqa: E402


def out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def _load(name: str) -> dict:
    p = store.load_profile(name)
    if p is None:
        raise SystemExit(json.dumps(
            {"ok": False, "error": f"'{name}' 프로필이 없습니다.",
             "profiles": [x["name"] for x in store.list_profiles()]}, ensure_ascii=False))
    return p


def cmd_dart(args) -> None:
    out(dart.lookup(args.name))


def cmd_company(args) -> None:
    prof = _load(args.profile)
    errs = validate_company(prof)
    if errs:
        out({"ok": False, "errors": errs})
        raise SystemExit(1)
    shares = prof.get("shares_outstanding")
    estimated = list(prof.get("estimated") or [])
    lr = prof.get("last_round") or {}
    if not shares and lr.get("post_money_krw") and lr.get("price_per_share_krw"):
        shares = int(round(lr["post_money_krw"] / lr["price_per_share_krw"]))
        if "shares_outstanding" not in estimated:
            estimated.append("shares_outstanding")
    op = prof.get("operating_income_krw")
    profitable = bool(op and op > 0)
    val = valuate.estimate(
        sector_tag=prof["sector_tag"], revenue=prof.get("revenue_krw"),
        net_income=prof.get("net_income_krw") or op, operating_income=op,
        profitable=profitable, shares_outstanding=shares,
        founded_year=prof.get("founded_year"),
        last_round_krw=(prof.get("last_round") or {}).get("post_money_krw"))
    pred = predict.estimate(
        sector_tag=prof["sector_tag"], stage=int(prof["stage"]),
        stage_date=prof.get("stage_date"), revenue=prof.get("revenue_krw"),
        profitable=profitable, founded_year=prof.get("founded_year"),
        revenue_prev=prof.get("revenue_prev_krw"))
    gate = listing_rules.check(val["market_cap_krw"].get("기준"), prof.get("revenue_krw"), profitable)
    if val.get("scale_warning"):
        gate = {"verdict": "규모 미달", "notes": [val["scale_warning"]]}
    if gate["verdict"] in {"미달", "규모 미달"}:
        # 형식요건에 못 닿는 규모다. 청구 이력 기반 확률을 그대로 쓰면 사용자를 오도한다.
        pred["probability"] = round(min(pred["probability"], 0.05), 3)
        pred["probability_is_estimate"] = True
        pred["reasons"].insert(0, gate["notes"][0])
    result = {
        "company": {k: prof.get(k) for k in
                    ("name", "sector_tag", "founded_year", "revenue_krw", "revenue_prev_krw",
                     "operating_income_krw", "stage", "stage_date", "business_description")},
        "shares_outstanding": shares, "estimated": estimated,
        "prediction": pred, "valuation": val, "listing_gate": gate,
        "peers_in_review": predict.peers_in_review(prof["sector_tag"], prof.get("revenue_krw")),
        "backtest": dataset.backtest(),
        "data_as_of": dataset.data_as_of(),
    }
    result["company"]["profitable"] = profitable
    # 회사 숫자가 바뀌면 그 위에서 계산한 옵션 결과는 못 쓴다. 지우지 않으면
    # 한 장의 글에 새 주당가와 옛 세후가치가 섞인다.
    stale = len((prof.get("result") or {}).get("options") or {})
    prof.setdefault("result", {})["company"] = result
    prof["result"]["options"] = {}
    prof["shares_outstanding"] = shares
    prof["estimated"] = estimated
    store.save_profile(prof)
    out({"ok": True, "options_recalc_needed": stale, **result})


def cmd_option(args) -> None:
    prof = _load(args.profile)
    company = (prof.get("result") or {}).get("company")
    if not company:
        out({"ok": False, "error": "회사 계산 결과가 없습니다. 먼저 `company`를 실행하세요."})
        raise SystemExit(1)
    options = prof.get("options") or []
    if not options:
        out({"ok": False, "error": "저장된 스톡옵션이 없습니다."})
        raise SystemExit(1)
    idx = (args.option or 1) - 1
    if not 0 <= idx < len(options):
        out({"ok": False, "error": f"옵션 번호는 1~{len(options)} 입니다."})
        raise SystemExit(1)
    o = options[idx]
    errs = validate_option(o, prof.get("shares_outstanding"))
    if errs:
        out({"ok": False, "errors": errs})
        raise SystemExit(1)
    res = ov.evaluate(
        quantity=int(o["quantity"]), strike_krw=float(o["strike_krw"]),
        grant_date=o["grant_date"], vest_schedule=o["vest_schedule"],
        expiry_date=o.get("expiry_date"), salary_krw=o.get("salary_krw"),
        company_result=company, is_venture=bool(o.get("is_venture", True)))
    prof.setdefault("result", {}).setdefault("options", {})[str(idx)] = res
    store.save_profile(prof)
    out({"ok": True, "option_index": idx + 1, "option": res,
         "company": company["company"], "prediction": company["prediction"],
         "valuation": company["valuation"]})


def cmd_format(args) -> None:
    prof = _load(args.profile)
    company = (prof.get("result") or {}).get("company")
    if not company:
        out({"ok": False, "error": "회사 계산 결과가 없습니다. 먼저 `company`를 실행하세요."})
        raise SystemExit(1)
    result = dict(company)
    opts = (prof.get("result") or {}).get("options") or {}
    idx = str((args.option or 1) - 1)
    if idx in opts:
        result["option"] = opts[idx]
    out({"ok": True, **threads.render(result)})


def cmd_validate(args) -> None:
    prof = _load(args.profile)
    errs = validate_company(prof)
    for i, o in enumerate(prof.get("options") or [], 1):
        errs += [f"옵션 {i}: {e}" for e in validate_option(o, prof.get("shares_outstanding"))]
    out({"ok": not errs, "errors": errs})
    if errs:
        raise SystemExit(1)


def cmd_profiles(_args) -> None:
    out({"ok": True, "home": str(store.HOME), "profiles": store.list_profiles()})


def cmd_update(args) -> None:
    if args.action == "check":
        out(update.check(force=args.force))
    else:
        out(update.apply(data=args.data, skill=args.skill))


def main() -> None:
    ap = argparse.ArgumentParser(prog="ipo_eval.py", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("update"); u.add_argument("action", choices=["check", "apply"])
    u.add_argument("--data", action="store_true"); u.add_argument("--skill", action="store_true")
    u.add_argument("--force", action="store_true"); u.set_defaults(fn=cmd_update)

    for name, fn in (("company", cmd_company), ("validate", cmd_validate)):
        p = sub.add_parser(name); p.add_argument("--profile", required=True); p.set_defaults(fn=fn)
    for name, fn in (("option", cmd_option), ("format", cmd_format)):
        p = sub.add_parser(name); p.add_argument("--profile", required=True)
        p.add_argument("--option", type=int, default=1); p.set_defaults(fn=fn)
    d = sub.add_parser("dart"); d.add_argument("--name", required=True); d.set_defaults(fn=cmd_dart)
    sub.add_parser("profiles").set_defaults(fn=cmd_profiles)

    args = ap.parse_args()
    try:
        args.fn(args)
    except SystemExit:
        raise
    except FileNotFoundError as e:
        out({"ok": False, "error": str(e)})
        raise SystemExit(2) from None
    except json.JSONDecodeError as e:
        out({"ok": False, "error": f"데이터 파일이 깨졌습니다: {e}"})
        raise SystemExit(2) from None
    except (TaxDataMissing, ValueError, KeyError) as e:
        out({"ok": False, "error": str(e)})
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
