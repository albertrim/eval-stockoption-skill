"""데이터셋 빌드 — 38·네이버·FDR·DART를 합쳐 data/*.json 을 만든다.

usage: builder/.venv/bin/python builder/build.py [--years 3] [--no-dart] [--limit N]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "builder"))

from lib import dart, krx, naver, sector, src38  # noqa: E402
from lib.common import mkrw  # noqa: E402

DATA = ROOT / "data"
SPAC = ("스팩", "제1호", "기업인수목적")


def is_spac(name: str) -> bool:
    return "스팩" in name or "기업인수목적" in name


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "0/0"


def build_listings(since: dt.date, limit: int | None, use_dart: bool, report: list[str]) -> list[dict]:
    raw = [r for r in src38.list_new_listings(since) if not is_spac(r["name_38"])]
    report.append(f"38 신규상장 목록(비스팩) {len(raw)}건")
    if limit:
        raw = raw[:limit]
    corp_idx = dart.corp_index() if use_dart else {}
    out: list[dict] = []
    fail = {"detail": 0, "code": 0, "naver": 0, "prices": 0, "filing": 0}
    for i, row in enumerate(raw, 1):
        try:
            d = src38.detail(row["no"])
        except Exception as e:  # noqa: BLE001
            fail["detail"] += 1
            report.append(f"  ! {row['name_38']} 상세 실패: {e}")
            continue
        code = d.get("code")
        if not code:
            fail["code"] += 1
            continue
        if (d.get("market_38") or "") != "코스닥":
            continue
        rec: dict = {
            "code": code, "name": d["name_38"], "listing_date": row["listing_date"],
            "warnings": [],
            "band_low": d["band_low"], "band_high": d["band_high"], "ipo_price": d["ipo_price"],
            "inst_demand_ratio": d["inst_demand_ratio"], "retail_sub_ratio": d["retail_sub_ratio"],
            "lockup_commit_pct": d["lockup_commit_pct"],
            "offer_shares": int(d["offer_shares"]) if d["offer_shares"] else None,
            "new_shares": int(d["new_shares"]) if d["new_shares"] else None,
            "old_shares": int(d["old_shares"]) if d["old_shares"] is not None else None,
            "offer_amount_krw": mkrw(d["offer_amount_mkrw"]),
            "underwriter": d["underwriter"],
            "revenue_at_filing_krw": mkrw(d["rev_at_filing_mkrw"]),
            "net_income_at_filing_krw": mkrw(d["ni_at_filing_mkrw"]),
            "industry_38": d["industry_38"],
            "source_urls": {"ipo_terms": d["source_url"]},
        }
        rec |= krx.profile(code)
        try:
            f = naver.financials(code)
            rec["financials"] = {str(y): v for y, v in sorted(f["years"].items())}
            rec["industry_naver"] = f["industry_naver"]
            rec["shares_now"] = f["shares_now"] or rec.get("shares_now_krx")
            rec["source_urls"]["financials"] = f["source_url"]
        except Exception as e:  # noqa: BLE001
            fail["naver"] += 1
            rec["financials"] = {}
            rec["shares_now"] = rec.get("shares_now_krx")
            rec["warnings"].append(f"네이버 재무 실패: {e}")
        try:
            rec["prices"] = krx.prices(code, row["listing_date"])
        except Exception:  # noqa: BLE001
            fail["prices"] += 1
            rec["prices"] = {}
        if use_dart:
            cc = dart.find_corp(d["name_38"], code, corp_idx)
            if cc:
                try:
                    bgn = (dt.date.fromisoformat(row["listing_date"]) - dt.timedelta(days=730)).strftime("%Y%m%d")
                    rec |= dart.filing_facts(cc, bgn, row["listing_date"].replace("-", ""))
                    rec |= dart.company(cc)
                except Exception as e:  # noqa: BLE001
                    fail["filing"] += 1
                    rec["warnings"].append(f"DART 실패: {e}")
            else:
                fail["filing"] += 1
        finalize(rec)
        out.append(rec)
        if i % 20 == 0:
            print(f"  ... {i}/{len(raw)}", file=sys.stderr)
    report.append(f"  실패: {fail}")
    return out


def finalize(rec: dict) -> None:
    """파생값·항등식 검증. 값이 어긋나면 warnings에 남긴다."""
    shares_ipo = rec.get("shares_at_ipo")
    if shares_ipo:
        rec["shares_source"] = "filing"
    else:
        shares_ipo = rec.get("shares_now")
        rec["shares_source"] = "now" if shares_ipo else None
    rec["shares_at_ipo"] = shares_ipo
    price = rec.get("ipo_price")
    rec["ipo_market_cap_krw"] = int(price * shares_ipo) if price and shares_ipo else None

    if price and rec.get("offer_shares") and rec.get("offer_amount_krw"):
        calc = price * rec["offer_shares"]
        if abs(calc - rec["offer_amount_krw"]) / rec["offer_amount_krw"] > 0.02:
            rec["warnings"].append(f"공모금액 불일치: 계산 {calc:,.0f} vs 표기 {rec['offer_amount_krw']:,}")
    if rec.get("new_shares") is not None and rec.get("old_shares") is not None and rec.get("offer_shares"):
        if rec["new_shares"] + rec["old_shares"] != rec["offer_shares"]:
            rec["warnings"].append("신주+구주 ≠ 공모주식수")
    if rec.get("listing_date_krx") and rec["listing_date_krx"] != rec["listing_date"]:
        rec["warnings"].append(f"상장일 불일치: 38 {rec['listing_date']} vs KRX {rec['listing_date_krx']}")

    # 상장 직전 회계연도 실적 → 공모가 기준 배수
    year_prev = str(dt.date.fromisoformat(rec["listing_date"]).year - 1)
    fin = (rec.get("financials") or {}).get(year_prev, {})
    rev = fin.get("revenue") or rec.get("revenue_at_filing_krw")
    ni = fin.get("net_income") or rec.get("net_income_at_filing_krw")
    op = fin.get("operating_income")
    rec["base_year"] = year_prev
    rec["revenue_krw"], rec["net_income_krw"], rec["operating_income_krw"] = rev, ni, op
    cap = rec["ipo_market_cap_krw"]
    rec["ipo_psr"] = round(cap / rev, 2) if cap and rev and rev > 0 else None
    rec["ipo_per"] = round(cap / ni, 2) if cap and ni and ni > 0 else None
    rec["profitable"] = bool(op and op > 0) if op is not None else (bool(ni and ni > 0))

    rec["sector_tag"] = sector.classify(rec.get("industry_naver"), rec.get("industry_38"),
                                        rec.get("industry_krx"))
    rec["years_since_listing"] = round(
        (dt.date.today() - dt.date.fromisoformat(rec["listing_date"])).days / 365.25, 2)
    rec["track"] = "기술성장" if rec.get("dept_krx") == "기술성장기업부" else "일반"
    if rec.get("new_shares") and shares_ipo:
        pre = shares_ipo - rec["new_shares"]
        rec["new_share_ratio"] = round(rec["new_shares"] / pre, 4) if pre > 0 else None
    else:
        rec["new_share_ratio"] = None
    p = rec.get("prices") or {}
    for label in ("1m", "3m", "6m", "12m"):
        c = p.get(f"close_{label}")
        rec[f"ret_{label}"] = round(c / price - 1, 4) if c and price else None
    if p.get("latest_close") and price:
        rec["ret_latest"] = round(p["latest_close"] / price - 1, 4)
    if rec.get("option_strike_krw") and price:
        rec["option_to_ipo_ratio"] = round(rec["option_strike_krw"] / price, 4)


def build_pipeline(report: list[str], use_dart: bool) -> dict:
    rows = [r for r in src38.list_filings() if not is_spac(r["name_38"])]
    report.append(f"38 예비심사 청구 이력(비스팩) {len(rows)}건")
    today = dt.date.today()
    for r in rows:
        r["revenue_krw"] = mkrw(r.pop("revenue_mkrw"))
        r["net_income_krw"] = mkrw(r.pop("net_income_mkrw"))
        r["capital_krw"] = mkrw(r.pop("capital_mkrw"))
        r["sector_tag"] = sector.classify(None, r.get("industry_38"))
    # 진행 중인 건과 최근 3년 청구분만 상세 보강 (설립일·시장구분·승인일)
    cut = (today - dt.timedelta(days=365 * 3)).isoformat()
    need = [r for r in rows if r["no"] and (r["status"] in {"심사중", "승인"} or r["filed_date"] >= cut)]
    report.append(f"  상세 보강 대상 {len(need)}건")
    for i, r in enumerate(need, 1):
        try:
            r |= {k: v for k, v in src38.filing_detail(r["no"]).items() if v is not None}
        except Exception as e:  # noqa: BLE001
            r["detail_error"] = str(e)
        if i % 50 == 0:
            print(f"  ... 청구상세 {i}/{len(need)}", file=sys.stderr)
    # 원본에 오타로 보이는 미래 청구일이 섞여 있다(예: 2028-08-25). 통계와 "심사 중" 목록
    # 양쪽을 오염시키므로 여기서 표시하고 뺀다.
    today_s = today.isoformat()
    future = [r for r in rows if (r.get("filed_date") or "") > today_s]
    if future:
        report.append(f"  미래 청구일 {len(future)}건 제외: "
                      + ", ".join(f"{r['name_38']}({r['filed_date']})" for r in future[:5]))
    rows = [r for r in rows if (r.get("filed_date") or "") <= today_s]
    kosdaq = [r for r in rows if (r.get("market_38") or "코스닥") == "코스닥"]
    in_review = [r for r in kosdaq if r["status"] in {"심사중", "승인"}]
    report.append(f"  코스닥 {len(kosdaq)}건, 심사 진행 중 {len(in_review)}건")
    return {"filings": kosdaq, "in_review": in_review}


def build_base_rates(pipe: dict, listings: list[dict], report: list[str]) -> dict:
    today = dt.date.today()
    rows = pipe["filings"]

    def window(years: int) -> list[dict]:
        cut = (today - dt.timedelta(days=365 * years)).isoformat()
        # 결론이 난 건만 (심사중 제외) — 진행 중인 건을 분모에 넣으면 승인율이 낮게 나온다
        return [r for r in rows if r["filed_date"] >= cut and r["status"] != "심사중"]

    def rates(sub: list[dict]) -> dict:
        n = len(sub)
        if not n:
            return {"n": 0}
        approved = [r for r in sub if r["status"] in {"승인", "상장"}]
        listed = [r for r in sub if r["status"] == "상장"]
        withdrawn = [r for r in sub if r["status"] == "철회"]
        return {
            "n": n,
            "approval_rate": round(len(approved) / n, 4),
            "listing_rate_given_approval": round(len(listed) / len(approved), 4) if approved else None,
            "withdraw_rate": round(len(withdrawn) / n, 4),
            "n_approved": len(approved), "n_listed": len(listed),
        }

    out: dict = {"as_of": today.isoformat(), "overall": {}, "by_sector": {}}
    for years in (3, 5, 10):
        out["overall"][f"{years}y"] = rates(window(years))

    for tag in sector.TAGS:
        sub = [r for r in window(5) if r["sector_tag"] == tag]
        if len(sub) >= 10:
            out["by_sector"][tag] = rates(sub)

    # 청구 → 상장 소요 개월 (실제 상장한 건, 최근 5년)
    months = []
    by_name = {r["name"]: r for r in listings}
    for r in window(5):
        if r["status"] != "상장":
            continue
        hit = by_name.get(r["name_38"])
        if not hit:
            continue
        f = dt.date.fromisoformat(r["filed_date"])
        l = dt.date.fromisoformat(hit["listing_date"])
        if 0 < (l - f).days < 365 * 3:
            months.append((l - f).days / 30.44)
    if months:
        months.sort()
        out["filed_to_listed_months"] = {
            "n": len(months), "p25": round(months[len(months) // 4], 1),
            "median": round(st.median(months), 1), "p75": round(months[3 * len(months) // 4], 1),
        }

    approved_months = []
    for r in window(5):
        if not r.get("approved_date"):
            continue
        try:
            f = dt.date.fromisoformat(r["filed_date"])
            a = dt.date.fromisoformat(r["approved_date"])
        except ValueError:
            continue
        if 0 < (a - f).days < 365 * 2:
            approved_months.append((a - f).days / 30.44)
    if approved_months:
        approved_months.sort()
        out["filed_to_approved_months"] = {
            "n": len(approved_months), "median": round(st.median(approved_months), 1),
            "p25": round(approved_months[len(approved_months) // 4], 1),
            "p75": round(approved_months[3 * len(approved_months) // 4], 1),
        }

    # 설립 → 청구 연수 (업종별 중앙값)
    founded: dict[str, list[float]] = {}
    for r in rows:
        if not r.get("founded_date"):
            continue
        try:
            f0 = dt.date.fromisoformat(r["founded_date"])
            f1 = dt.date.fromisoformat(r["filed_date"])
        except ValueError:
            continue
        yrs = (f1 - f0).days / 365.25
        if 0 < yrs < 60:
            founded.setdefault(r["sector_tag"], []).append(yrs)
    out["founded_to_filed_years"] = {
        "overall": round(st.median(sum(founded.values(), [])), 1) if founded else None,
        "by_sector": {k: {"median": round(st.median(v), 1), "n": len(v)}
                      for k, v in founded.items() if len(v) >= 5},
    }
    out["track_share"] = {}
    for tag in sector.TAGS:
        sub = [r for r in listings if r["sector_tag"] == tag]
        if sub:
            out["track_share"][tag] = {
                "n": len(sub),
                "tech_track_share": round(sum(r["track"] == "기술성장" for r in sub) / len(sub), 3),
            }
    report.append(f"기준율: 3년 {out['overall']['3y']}, 청구→상장 {out.get('filed_to_listed_months')}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-dart", action="store_true")
    ap.add_argument("--skip-pipeline", action="store_true")
    args = ap.parse_args()

    use_dart = dart.enabled() and not args.no_dart
    report: list[str] = [f"빌드 {dt.datetime.now():%Y-%m-%d %H:%M}  DART={'on' if use_dart else 'off'}"]
    since = dt.date.today() - dt.timedelta(days=365 * args.years)
    DATA.mkdir(exist_ok=True)

    print("[1/4] 신규상장 수집", file=sys.stderr)
    listings = build_listings(since, args.limit, use_dart, report)

    print("[2/4] 청구 이력 수집", file=sys.stderr)
    if args.skip_pipeline and (DATA / "pipeline.json").exists():
        pipe = json.loads((DATA / "pipeline.json").read_text())
    else:
        pipe = build_pipeline(report, use_dart)

    print("[3/4] 기준율 계산", file=sys.stderr)
    base = build_base_rates(pipe, listings, report)

    print("[4/4] 저장", file=sys.stderr)
    coverage = {}
    for field in ("ipo_price", "revenue_krw", "shares_at_ipo", "ipo_market_cap_krw", "new_share_ratio",
                  "ret_6m", "applied_multiple", "discount_low", "options_outstanding",
                  "option_strike_krw", "founded_date"):
        coverage[field] = pct(sum(1 for r in listings if r.get(field) is not None), len(listings))
    filing_source = sum(1 for r in listings if r.get("shares_source") == "filing")
    report.append(f"필드 커버리지: {json.dumps(coverage, ensure_ascii=False, indent=2)}")
    report.append(f"shares_at_ipo 신고서 출처: {pct(filing_source, len(listings))}")
    warn = [f"  {r['code']} {r['name']}: {w}" for r in listings for w in r["warnings"]]
    report.append(f"경고 {len(warn)}건" + ("\n" + "\n".join(warn[:30]) if warn else ""))

    (DATA / "kosdaq_ipo.json").write_text(json.dumps(
        {"as_of": dt.date.today().isoformat(), "years": args.years, "companies": listings},
        ensure_ascii=False, indent=1))
    (DATA / "pipeline.json").write_text(json.dumps(pipe, ensure_ascii=False, indent=1))
    (DATA / "base_rates.json").write_text(json.dumps(base, ensure_ascii=False, indent=1))

    manifest = {
        "data_version": dt.date.today().isoformat(),
        "skill_version": (ROOT / "VERSION").read_text().strip() if (ROOT / "VERSION").exists() else "0.0.0",
        "companies": len(listings), "filings": len(pipe["filings"]), "in_review": len(pipe["in_review"]),
        "coverage": coverage,
        "files": {},
    }
    for name in ("kosdaq_ipo.json", "pipeline.json", "base_rates.json", "tax_params.json"):
        p = DATA / name
        if p.exists():
            manifest["files"][name] = {
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
                "bytes": p.stat().st_size,
            }
    (DATA / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    (ROOT / "builder" / "build_report.txt").write_text("\n".join(report))
    print("\n".join(report))


if __name__ == "__main__":
    main()
