"""백테스트 — 데이터셋의 회사를 비상장인 척 넣어 공모시총을 맞혀본다.

leave-one-out: 대상 회사를 비교기업 풀에서 뺀 뒤 같은 규칙으로 추정하고 실제와 비교한다.
결과(MAPE·시나리오 적중률)는 manifest.json 에 적어 Threads 답글에서 그대로 인용한다.

usage: builder/.venv/bin/python builder/backtest.py
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import comps as comps_mod  # noqa: E402
from lib import dataset  # noqa: E402


def run() -> dict:
    all_rows = dataset.companies()
    errors: list[float] = []
    inside = 0
    scored = 0
    by_sector: dict[str, list[float]] = {}

    for target in all_rows:
        actual = target.get("ipo_market_cap_krw")
        if not actual or actual <= 0:
            continue
        rev, ni = target.get("revenue_krw"), target.get("net_income_krw")
        profitable = bool(target.get("profitable"))
        metric = comps_mod.pick_metric(rev, ni, profitable)
        base = {"per": ni, "psr": rev, "abs": None}[metric]
        if metric != "abs" and (not base or base <= 0):
            continue

        # 자기 자신을 뺀 풀로 다시 고른다
        saved = dataset.companies.__wrapped__ if hasattr(dataset.companies, "__wrapped__") else None
        pool = [c for c in all_rows if c["code"] != target["code"]]
        dataset.companies.cache_clear()
        dataset.companies.__dict__  # noqa: B018
        sel = _select_with_pool(pool, target["sector_tag"], rev, profitable, metric)
        if len(sel["comps"]) < comps_mod.MIN_COMPS:
            continue
        q = comps_mod.percentiles(sel["comps"], metric)
        est = q["mid"] if metric == "abs" else q["mid"] * base
        lo = q["low"] if metric == "abs" else q["low"] * base
        hi = q["high"] if metric == "abs" else q["high"] * base
        err = abs(est - actual) / actual
        errors.append(err)
        by_sector.setdefault(target["sector_tag"], []).append(err)
        scored += 1
        if lo <= actual <= hi:
            inside += 1
        _ = saved

    if not errors:
        return {"n": 0}
    errors.sort()
    return {
        "n": scored,
        "mape_median": round(st.median(errors), 3),
        "mape_mean": round(st.fmean(errors), 3),
        "err_p25": round(errors[len(errors) // 4], 3),
        "err_p75": round(errors[3 * len(errors) // 4], 3),
        "inside_low_high_rate": round(inside / scored, 3),
        "low_q": comps_mod.LOW_Q, "high_q": comps_mod.HIGH_Q, "fan_cap": comps_mod.FAN_CAP,
        "by_sector": {k: {"n": len(v), "mape_median": round(st.median(v), 3)}
                      for k, v in sorted(by_sector.items()) if len(v) >= 5},
    }


def _select_with_pool(pool: list[dict], sector_tag: str, revenue: float | None,
                      profitable: bool, metric: str) -> dict:
    """comps.select 과 같은 사다리를 주어진 풀에만 적용한다."""
    usable = [c for c in pool if comps_mod._usable(c, metric)]
    peers = comps_mod.group_peers(sector_tag)
    same = [c for c in usable if c.get("sector_tag") == sector_tag]
    same_pnl = [c for c in same if bool(c.get("profitable")) == profitable]
    grp = [c for c in usable if c.get("sector_tag") in peers]
    grp_pnl = [c for c in grp if bool(c.get("profitable")) == profitable]
    band = comps_mod._band
    ladder = []
    if revenue:
        ladder += [[c for c in same_pnl if band(c, revenue, comps_mod.NEAR)],
                   [c for c in same_pnl if band(c, revenue, comps_mod.WIDE)]]
    ladder.append(same_pnl)
    if revenue:
        ladder += [[c for c in grp_pnl if band(c, revenue, comps_mod.NEAR)],
                   [c for c in grp_pnl if band(c, revenue, comps_mod.WIDE)]]
    ladder += [grp_pnl, grp]
    if revenue:
        ladder.append([c for c in usable if bool(c.get("profitable")) == profitable
                       and band(c, revenue, comps_mod.NEAR)])
    ladder.append([c for c in usable if bool(c.get("profitable")) == profitable])
    for sub in ladder:
        if len(sub) >= comps_mod.MIN_COMPS:
            return {"comps": sub}
    return {"comps": max(ladder, key=len)}


def main() -> None:
    res = run()
    print(json.dumps(res, ensure_ascii=False, indent=1))
    mf = ROOT / "data" / "manifest.json"
    if mf.exists():
        m = json.loads(mf.read_text())
        m["backtest"] = res
        mf.write_text(json.dumps(m, ensure_ascii=False, indent=1))
        print(f"\nmanifest.json 에 기록했습니다.", file=sys.stderr)


if __name__ == "__main__":
    main()
