"""ipo-eval 계산 엔진 테스트. 표준 unittest만 쓴다.

  python3 scripts/tests/test_all.py
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import comps, dart, dataset, listing_rules, money, predict, store, tax, threads, update, validate, valuate  # noqa: E402
from lib.option_value import _add_months, evaluate, vested_ratio  # noqa: E402


class TestMoney(unittest.TestCase):
    def test_units_always_present(self):
        self.assertEqual(money.krw(3_000), "3,000원")
        self.assertEqual(money.krw(29_900_000), "2,990만원")
        self.assertEqual(money.krw(108_000_000), "1억800만원")
        self.assertEqual(money.krw(550_000_000), "5억5,000만원")
        self.assertEqual(money.krw(55_000_000_000), "550억원")
        self.assertEqual(money.krw(100_000_000), "1억원")

    def test_rounding_does_not_produce_1억0000만원(self):
        # 9,999.6만원이 반올림으로 1억이 되는 경계
        self.assertEqual(money.krw(199_999_500), "2억원")

    def test_negative_is_zero_not_minus(self):
        self.assertEqual(money.krw(-5_000_000), "0원")

    def test_none_is_dash(self):
        self.assertEqual(money.krw(None), "—")
        self.assertEqual(money.won(None), "—")


class TestVesting(unittest.TestCase):
    SCHED = [{"after_months": 24, "cumulative_pct": 0.5},
             {"after_months": 36, "cumulative_pct": 0.75},
             {"after_months": 48, "cumulative_pct": 1.0}]

    def test_before_first_step_is_zero(self):
        self.assertEqual(vested_ratio("2023-03-15", self.SCHED, dt.date(2025, 3, 14)), 0.0)

    def test_on_the_day_counts(self):
        self.assertEqual(vested_ratio("2023-03-15", self.SCHED, dt.date(2025, 3, 15)), 0.5)

    def test_steps(self):
        self.assertEqual(vested_ratio("2023-03-15", self.SCHED, dt.date(2026, 6, 1)), 0.75)
        self.assertEqual(vested_ratio("2023-03-15", self.SCHED, dt.date(2030, 1, 1)), 1.0)

    def test_month_end_does_not_overflow(self):
        self.assertEqual(_add_months(dt.date(2024, 1, 31), 1), dt.date(2024, 2, 29))
        self.assertEqual(_add_months(dt.date(2023, 1, 31), 1), dt.date(2023, 2, 28))
        self.assertEqual(_add_months(dt.date(2023, 12, 15), 12), dt.date(2024, 12, 15))


class TestValidate(unittest.TestCase):
    BASE = {"name": "테스트", "sector_tag": "it_saas", "founded_year": 2019,
            "revenue_krw": 1_000_000_000, "stage": 3, "stage_date": "2026-01-01",
            "shares_outstanding": 1_000_000}

    def test_good_profile_passes(self):
        self.assertEqual(validate.validate_company(dict(self.BASE)), [])

    def test_negative_revenue_caught(self):
        p = dict(self.BASE, revenue_krw=-1)
        self.assertTrue(any("음수" in e for e in validate.validate_company(p)))

    def test_stage_out_of_range_caught(self):
        self.assertTrue(any("0~5" in e for e in validate.validate_company(dict(self.BASE, stage=7))))

    def test_future_filing_date_caught(self):
        p = dict(self.BASE, stage_date="2099-01-01")
        self.assertTrue(any("미래" in e for e in validate.validate_company(p)))

    def test_bad_sector_caught(self):
        p = dict(self.BASE, sector_tag="saas")
        self.assertTrue(any("업종" in e for e in validate.validate_company(p)))

    def test_missing_shares_and_round_caught(self):
        p = dict(self.BASE); p.pop("shares_outstanding")
        self.assertTrue(any("발행주식수" in e for e in validate.validate_company(p)))

    def test_unit_mistake_caught(self):
        # "85억"을 8500으로 넣은 것. 억→원 변환은 LLM이 하므로 여기서 막아야 한다
        p = dict(self.BASE, revenue_krw=8_500)
        self.assertTrue(any("억 단위" in e for e in validate.validate_company(p)))
        p = dict(self.BASE, shares_outstanding=12)
        self.assertTrue(any("단위(주)" in e for e in validate.validate_company(p)))
        p = dict(self.BASE, last_round={"post_money_krw": 400, "price_per_share_krw": 8000})
        self.assertTrue(any("억 단위" in e for e in validate.validate_company(p)))
        # 0은 "매출 없음"이라 통과한다
        self.assertEqual(validate.validate_company(dict(self.BASE, revenue_krw=0)), [])

    OPT = {"quantity": 5000, "strike_krw": 3000, "grant_date": "2023-03-15",
           "expiry_date": "2030-03-14",
           "vest_schedule": [{"after_months": 24, "cumulative_pct": 1.0}]}

    def test_good_option_passes(self):
        self.assertEqual(validate.validate_option(dict(self.OPT)), [])

    def test_expiry_before_grant_caught(self):
        o = dict(self.OPT, expiry_date="2022-01-01")
        self.assertTrue(any("만료일" in e for e in validate.validate_option(o)))

    def test_zero_strike_caught(self):
        self.assertTrue(any("행사가" in e for e in validate.validate_option(dict(self.OPT, strike_krw=0))))

    def test_schedule_not_reaching_100_caught(self):
        o = dict(self.OPT, vest_schedule=[{"after_months": 24, "cumulative_pct": 0.5}])
        self.assertTrue(any("100%" in e for e in validate.validate_option(o)))

    def test_schedule_going_backwards_caught(self):
        o = dict(self.OPT, vest_schedule=[{"after_months": 24, "cumulative_pct": 0.8},
                                          {"after_months": 36, "cumulative_pct": 0.5},
                                          {"after_months": 48, "cumulative_pct": 1.0}])
        self.assertTrue(any("줄었" in e for e in validate.validate_option(o)))


class TestComps(unittest.TestCase):
    def test_metric_choice(self):
        self.assertEqual(comps.pick_metric(1e10, 1e9, True), "per")
        self.assertEqual(comps.pick_metric(1e10, -1e9, False), "psr")
        self.assertEqual(comps.pick_metric(0, -1e9, False), "abs")

    def test_tiny_revenue_uses_absolute_marketcap(self):
        # 임상 단계 바이오: 매출 8억에 PSR을 곱하면 근거 없는 숫자가 나온다
        self.assertEqual(comps.pick_metric(800_000_000, -1e10, False), "abs")
        self.assertEqual(comps.pick_metric(3_000_000_000, -1e10, False), "psr")

    def test_thin_profit_falls_back_to_psr(self):
        # 매출 1,000억에 이익 10억(1%)이면 PER 26배를 곱해 시총 268억이 나온다.
        # 흑자여도 매출로 봐야 한다.
        self.assertEqual(comps.pick_metric(100e9, 1e9, True), "psr")
        self.assertTrue(comps.thin_margin(100e9, 1e9))
        # 이익률이 두툼하면 그대로 PER
        self.assertEqual(comps.pick_metric(100e9, 10e9, True), "per")
        self.assertFalse(comps.thin_margin(100e9, 10e9))
        # 매출이 미미하면 PSR로 갈 수 없으니 PER을 유지한다
        self.assertEqual(comps.pick_metric(1e9, 1e7, True), "per")

    def test_percentiles_ordered(self):
        rows = [{"ipo_psr": v} for v in (1, 2, 3, 4, 5, 6, 7, 8)]
        q = comps.percentiles(rows, "psr")
        self.assertLess(q["low"], q["mid"])
        self.assertLess(q["mid"], q["high"])
        self.assertEqual(q["n"], 8)

    def test_single_comp_does_not_crash(self):
        q = comps.percentiles([{"ipo_psr": 4.0}], "psr")
        self.assertEqual(q["low"], 4.0)
        self.assertEqual(q["high"], 4.0)

    def test_band_is_wider_than_quartiles(self):
        # 백테스트에서 p25~p75가 실제를 41%밖에 못 담아 p10~p90으로 넓혔다
        self.assertLessEqual(comps.LOW_Q, 0.15)
        self.assertGreaterEqual(comps.HIGH_Q, 0.85)

    def test_group_covers_small_sectors(self):
        self.assertIn("ecommerce_platform", comps.group_peers("beauty"))
        self.assertIn("it_saas", comps.group_peers("ai_data"))

    def test_thin_sector_starts_from_group_rung(self):
        # ai_data는 2곳뿐이라 업종군이 출발선이다. "3단계 넓혔다"가 나오면 안 된다
        sel = comps.select("ai_data", 1.5e10, False, "psr")
        self.assertTrue(sel["sector_thin"])
        self.assertLess(sel["sector_thin"]["n"], comps.MIN_COMPS)
        self.assertEqual(sel["relaxed_steps"], 0)
        self.assertFalse(sel["relaxed"])
        # 표본이 넉넉한 업종은 원래대로 0단계부터 센다
        sel = comps.select("it_saas", 3e10, True, "per")
        self.assertIsNone(sel["sector_thin"])
        self.assertEqual(sel["relaxed_steps"], 0)

    def test_comps_carry_industry(self):
        val = valuate.estimate(sector_tag="industrial", revenue=7.5e10, net_income=-8e9,
                               operating_income=-8e9, profitable=False, shares_outstanding=12_000_000)
        self.assertTrue(all("industry" in c for c in val["comps"]))
        self.assertTrue(any(c["industry"] for c in val["comps"]))

    def test_split_hint_follows_the_mid_price_only(self):
        # 기준 주당가가 공모가 범위 안이면 낙관이 범위 밖이어도 힌트를 붙이지 않는다
        val = valuate.estimate(sector_tag="it_saas", revenue=1e11, net_income=1e9,
                               operating_income=1e9, profitable=True, shares_outstanding=8_000_000)
        mid = val["price_per_share"]["기준"]
        if val["split_hint"]:
            self.assertFalse(valuate.PRICE_LOW <= mid <= valuate.PRICE_HIGH)
        else:
            self.assertTrue(valuate.PRICE_LOW <= mid <= valuate.PRICE_HIGH)

    def test_per_path_says_it_uses_operating_income(self):
        val = valuate.estimate(sector_tag="hardware_semi", revenue=8e10, net_income=9e9,
                               operating_income=9e9, profitable=True, shares_outstanding=5_000_000)
        self.assertEqual(val["metric"], "per")
        self.assertIn("영업이익", val["per_basis_note"])


class TestMoneySigned(unittest.TestCase):
    def test_loss_is_shown_not_swallowed(self):
        # 6개월 뒤 손실이 "0원"으로 삼켜지던 버그
        self.assertEqual(money.krw(-54_949_687, signed=True), "-5,495만원")
        self.assertEqual(money.krw(-54_949_687), "0원")

    def test_jo_boundary(self):
        self.assertEqual(money.krw(999_950_000_000), "1조원")
        self.assertEqual(money.krw(1_000_000_000_000), "1조원")
        self.assertEqual(money.krw(1_683_800_000_000), "1조6,838억원")


class TestTax(unittest.TestCase):
    """세금은 손계산과 맞춰 고정한다. tax_params.json 값이 바뀌면 여기서 깨져야 한다."""

    def test_progressive_income_tax(self):
        self.assertEqual(round(tax.income_tax(300_000_000)), 103_466_000)

    def test_zero_and_negative(self):
        self.assertEqual(tax.income_tax(0), 0.0)
        self.assertEqual(tax.income_tax(-1_000_000), 0.0)

    def test_venture_exemption_applies_first(self):
        r = tax.exercise_tax(300_000_000, 0)
        self.assertEqual(r["exempt"], 200_000_000)
        self.assertEqual(round(r["tax"]), 21_516_000)

    def test_marginal_rate_stacks_on_salary(self):
        low = tax.exercise_tax(300_000_000, 0)["tax"]
        high = tax.exercise_tax(300_000_000, 80_000_000)["tax"]
        self.assertGreater(high, low)
        self.assertEqual(round(high), 38_522_000)

    def test_non_venture_pays_much_more(self):
        v = tax.exercise_tax(100_000_000, 0, venture=True)["tax"]
        nv = tax.exercise_tax(100_000_000, 0, venture=False)["tax"]
        self.assertEqual(v, 0.0)
        self.assertEqual(round(nv), 21_516_000)

    def test_transfer_tax_is_kosdaq_rate(self):
        self.assertEqual(round(tax.transfer_tax(100_000_000)), 200_000)

    def test_employee_has_no_lockup(self):
        self.assertEqual(tax.lockup_months(major_shareholder=False), 0)
        self.assertGreater(tax.lockup_months(major_shareholder=True), 0)


class TestFanCap(unittest.TestCase):
    def test_extreme_outlier_is_clamped(self):
        rows = [{"ipo_psr": v} for v in (1, 1.1, 1.2, 1.3, 99)]
        q = comps.percentiles(rows, "psr")
        self.assertLessEqual(q["high"], q["mid"] * comps.FAN_CAP + 1e-9)
        self.assertGreaterEqual(q["low"], q["mid"] / comps.FAN_CAP - 1e-9)

    def test_order_never_inverts(self):
        for vals in ([1], [1, 100], [5, 5, 5], [0.1, 2, 3, 400]):
            q = comps.percentiles([{"ipo_psr": v} for v in vals], "psr")
            self.assertLessEqual(q["low"], q["mid"])
            self.assertLessEqual(q["mid"], q["high"])


class TestThreadsConsistency(unittest.TestCase):
    """글에 찍힌 숫자가 계산 결과와 같은 기준인지. 결함 1~3이 전부 여기서 났다."""

    def _result(self, *, scope="IT·소프트웨어", qty=5000, qty_ipo=3750, after=(1, 2, 3)):
        return {
            "company": {"name": "T", "sector_tag": "it_saas"},
            "prediction": {"probability": 0.6, "probability_is_estimate": False,
                           "stage_label": "예비심사 청구", "expected_ipo_label": "2027년 상반기",
                           "expected_ipo_date": "2027-01", "rate_basis": "x", "sample_n": 10,
                           "approval_rate": 0.7, "listing_rate_given_approval": 0.9,
                           "track": "일반", "reasons": []},
            "valuation": {"market_cap_krw": {"보수": 1e10, "기준": 2e10, "낙관": 3e10},
                          "price_per_share": {"보수": 1000, "기준": 2000, "낙관": 3000},
                          "comps_n": 5, "comps_scope": scope, "comps": [{"name": "A"}],
                          "criteria": "c", "relaxed": False, "metric": "psr",
                          "metric_label": "PSR",
                          "quartiles": {"low": 1, "mid": 2, "high": 3},
                          "new_share_ratio": 0.2, "shares_at_ipo": 6_000_000},
            "option": {"quantity": qty, "quantity_at_ipo": qty_ipo, "quantity_today": qty_ipo,
                       "strike_krw": 500, "vested_today_pct": 0.75, "vested_at_ipo_pct": 0.75,
                       "expired_before_ipo": False, "expiry_date": "2030-01-01",
                       "ownership_pct": qty_ipo / 6_000_000, "lockup_months": 0,
                       "is_venture": True, "median_ret_6m": -0.1, "warnings": [],
                       "discount_label": "한국은행 기준금리 연 3.00%", "discount_years": 0.4,
                       "sellable_date": "2027-01",
                       "scenarios": {k: {"after_tax_krw": v * 1e7, "present_value_krw": v * 1e7,
                                         "price_per_share": 2000, "gross_krw": v * 1e7,
                                         "exercise_cost_krw": 1e6, "income_tax_krw": 0,
                                         "tax_free_krw": 1e7, "transfer_tax_krw": 1e5,
                                         "after_tax_6m_krw": -1e7 if k == "보수" else v * 1e7}
                                     for k, v in zip(("보수", "기준", "낙관"), after)}},
        }

    def test_headline_quantity_matches_the_money(self):
        main = threads.main_post(self._result())
        self.assertIn("5,000주 중 상장 시점 행사 가능 3,750주", main)

    def test_full_vest_shows_plain_quantity(self):
        main = threads.main_post(self._result(qty=5000, qty_ipo=5000))
        self.assertIn("내 스톡옵션 5,000주 (행사가", main)

    def test_scope_label_not_faked(self):
        main = threads.main_post(self._result(scope="코스닥"))
        self.assertIn("최근 코스닥 상장 5곳 기준", main)
        self.assertNotIn("IT·소프트웨어", main)

    def test_six_month_loss_is_negative_in_replies(self):
        r = self._result()
        r["option"]["scenarios"]["기준"]["after_tax_6m_krw"] = -1e7
        joined = "\n".join(threads.replies(r))
        self.assertIn("-1,000만원", joined)

    def test_six_month_line_degrades_without_spread(self):
        # 분포가 없으면 "하위 25% —" 같은 빈칸 문장이 나가면 안 된다
        joined = "\n".join(threads.replies(self._result()))
        self.assertIn("[상장 6개월 뒤에 판다면]", joined)
        self.assertNotIn("하위 25%", joined)
        self.assertNotIn("—는 공모가", joined)

    def test_six_month_line_shows_both_sides_when_spread_exists(self):
        r = self._result()
        r["option"]["ret_6m_spread"] = {"p25": -0.32, "median": -0.16, "p75": 0.15,
                                        "n": 17, "positive_rate": 0.353}
        r["option"]["scenarios"]["기준"]["after_tax_6m_low_krw"] = 1.5e7
        r["option"]["scenarios"]["기준"]["after_tax_6m_high_krw"] = 3.0e7
        joined = "\n".join(threads.replies(r))
        self.assertIn("상위 25% 15.0%", joined)
        self.assertIn("35%는 공모가를 넘겼습니다", joined)
        self.assertIn("1,500만원 ~ 3,000만원", joined)

    def test_main_post_within_limit(self):
        self.assertLessEqual(len(threads.main_post(self._result())), threads.LIMIT)

    def test_main_post_shows_only_the_mid_value(self):
        main = threads.main_post(self._result())
        self.assertIn("· 예상 시총 200억원", main)
        self.assertNotIn("100억원 / 200억원", main)
        self.assertIn("· 세후 손에 쥐는 돈 2,000만원", main)
        self.assertNotIn("1,000만원 / 2,000만원", main)

    def test_relaxation_depth_is_reported(self):
        r = self._result()
        r["valuation"]["relaxed"] = True
        r["valuation"]["relaxed_steps"] = 4
        joined = "\n".join(threads.replies(r))
        self.assertIn("4단계 넓혔습니다", joined)
        self.assertIn("이 업종의 배수라고 보기 어렵습니다", joined)

    def test_replies_keep_the_range(self):
        joined = "\n".join(threads.replies(self._result()))
        self.assertIn("[범위]", joined)
        self.assertIn("100억원~300억원", joined)

    def test_replies_are_five_and_each_within_limit(self):
        r = self._result()
        reps = threads.replies(r)
        self.assertEqual(len(reps), 5)
        rendered = threads.render(r)
        self.assertEqual(rendered["replies_over_limit"], [])
        self.assertEqual(len(rendered["reply_lengths"]), 5)
        # 회사만 계산했으면 옵션 답글이 빠져 4개
        r.pop("option")
        self.assertEqual(len(threads.replies(r)), 4)

    def test_six_month_median_is_attributed_to_comps(self):
        r = self._result()
        r["valuation"]["median_ret_6m"] = -0.1
        joined = "\n".join(threads.replies(r))
        self.assertIn("비교기업 5곳의 공모가 대비 6개월 뒤", joined)
        self.assertNotIn("최근 상장사는 공모가 대비", joined)

    def test_comps_show_industry_and_per_basis(self):
        r = self._result()
        r["valuation"]["comps"] = [{"name": "A", "industry": "자동차부품"}]
        r["valuation"]["metric"] = "per"
        r["valuation"]["per_basis_note"] = "PER은 영업이익에 곱했습니다."
        joined = "\n".join(threads.replies(r))
        self.assertIn("A(자동차부품)", joined)
        self.assertIn("PER(영업이익 기준)", joined)
        self.assertIn("PER은 영업이익에 곱했습니다.", joined)

    def test_thin_sector_is_explained_not_blamed(self):
        r = self._result()
        r["valuation"]["sector_thin"] = {"n": 2, "group": "IT·하드웨어"}
        r["valuation"]["relaxed"] = False
        r["valuation"]["relaxed_steps"] = 0
        joined = "\n".join(threads.replies(r))
        self.assertIn("2곳뿐이라 IT·하드웨어 업종군에서 골랐습니다", joined)
        self.assertNotIn("보기 어렵습니다", joined)

    def test_scale_unknown_is_not_called_a_listing_requirement(self):
        r = self._result()
        r["listing_gate"] = {"verdict": "규모 미확인", "notes": ["규모를 가늠할 근거가 없습니다."]}
        joined = "\n".join(threads.replies(r))
        self.assertIn("[규모 미확인] 규모를 가늠할 근거가 없습니다.", joined)
        self.assertNotIn("[상장요건]", joined)


class TestGate(unittest.TestCase):
    """'못 미친다'와 '모른다'를 같은 5%로 만들면 안 된다."""

    def _pred(self):
        return {"probability": 0.35, "probability_is_estimate": True, "reasons": ["a"]}

    def test_below_floor_caps_probability(self):
        pred = self._pred()
        listing_rules.apply(pred, {"verdict": "미달", "notes": ["작다"]})
        self.assertEqual(pred["probability"], 0.05)
        self.assertEqual(pred["reasons"][0], "작다")

    def test_unknown_scale_keeps_probability(self):
        pred = self._pred()
        listing_rules.apply(pred, {"verdict": "규모 미확인", "notes": ["모른다"]})
        self.assertEqual(pred["probability"], 0.35)
        self.assertIn("모른다", pred["reasons"])


class TestOptionSixMonths(unittest.TestCase):
    """행사하지 않은 옵션이 6개월 뒤에 손실이 날 수는 없다."""

    def _company(self, prices):
        return {"prediction": {"expected_ipo_date": "2027-06", "track": "일반"},
                "valuation": {"price_per_share": prices, "shares_at_ipo": 6_000_000,
                              "median_ret_6m": -0.2,
                              "ret_6m_spread": {"p25": -0.4, "median": -0.2, "p75": 0.3,
                                                "n": 20, "positive_rate": 0.4}}}

    def test_out_of_the_money_has_no_six_month_value(self):
        r = evaluate(quantity=1000, strike_krw=40_000, grant_date="2023-01-01",
                     vest_schedule=[{"after_months": 24, "cumulative_pct": 1.0}],
                     expiry_date="2031-01-01", salary_krw=None,
                     company_result=self._company({"보수": 10_000, "기준": 20_000, "낙관": 30_000}))
        for s in r["scenarios"].values():
            self.assertEqual(s["after_tax_krw"], 0.0)
            self.assertIsNone(s["after_tax_6m_krw"])
            self.assertIsNone(s["after_tax_6m_low_krw"])

    def test_in_the_money_keeps_six_month_value(self):
        r = evaluate(quantity=1000, strike_krw=5_000, grant_date="2023-01-01",
                     vest_schedule=[{"after_months": 24, "cumulative_pct": 1.0}],
                     expiry_date="2031-01-01", salary_krw=None,
                     company_result=self._company({"보수": 10_000, "기준": 20_000, "낙관": 30_000}))
        self.assertIsNotNone(r["scenarios"]["기준"]["after_tax_6m_krw"])
        self.assertGreater(r["scenarios"]["기준"]["after_tax_krw"], 0)


class TestDartParsing(unittest.TestCase):
    """사업보고서 요약재무정보는 로마숫자 없이 적는 회사가 많다(컬리)."""

    DOC = ("1. 요약재무정보\n가. 요약연결재무정보\n(단위: 원)\n구 분\n제12기\n제11기\n"
           "매출액\n2,367,115,187,275\n2,195,645,501,699\n2,077,354,737,526\n"
           "영업손익\n13,100,524,714\n(18,329,152,144)\n(143,640,061,103)\n"
           "주당순이익\n(367)\n(964)\n")

    def test_bare_labels_in_summary_table(self):
        fin = dart._income(self.DOC)
        self.assertEqual(fin["revenue"], 2_367_115_187_275)
        self.assertEqual(fin["revenue_prev"], 2_195_645_501_699)
        self.assertEqual(fin["operating_income"], 13_100_524_714)

    def test_spaced_heading_still_marks_consolidated(self):
        # "1. 요약재무정보" 제목 다음에 "가. 요약 연결 재무정보"가 오면 그 표는 연결이다
        doc = self.DOC.replace("가. 요약연결재무정보", "가. 요약 연결 재무정보")
        self.assertEqual(dart._income(doc)["basis"], "연결")
        self.assertEqual(dart._income(self.DOC)["basis"], "연결")

    def test_parenthesised_loss_keeps_its_sign(self):
        doc = self.DOC.replace("13,100,524,714", "(13,100,524,714)")
        self.assertEqual(dart._income(doc)["operating_income"], -13_100_524_714)

    def test_bare_labels_need_summary_heading(self):
        # 요약재무정보 표가 없으면 맨몸 라벨은 쓰지 않는다. 주석 표를 물어올 수 있다
        self.assertIsNone(dart._income(self.DOC.replace("요약재무정보", "재무"))["revenue"])

    def test_shares_table_beats_sentence(self):
        doc = ("당사가 발행할 주식의 총수는 500,000,000주이며, 발행주식의 총수는 보통주식 42,344,572주 입니다.\n"
               "(기준일 :\n2025년 12월 31일\n)\n(단위 : 주, %)\n구 분\n"
               "Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)\n42,344,572\n-\n-\n42,344,572\n-\n")
        self.assertEqual(dart._shares(doc)["diluted"], 42_344_572)


class TestStoreDataChoice(unittest.TestCase):
    """플러그인 업데이트로 동봉 데이터가 새것이면 옛 내려받은 사본이 이기면 안 된다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._home, self._data = store.HOME, store.DATA
        store.HOME = Path(self.tmp); store.DATA = store.HOME / "data"; store.DATA.mkdir(parents=True)
        self.bundled_version = json.loads((store.BUNDLED / "manifest.json").read_text())["data_version"]

    def tearDown(self):
        store.HOME, store.DATA = self._home, self._data
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _download(self, version: str):
        (store.DATA / "manifest.json").write_text(json.dumps({"data_version": version}))
        (store.DATA / "base_rates.json").write_text("{}")

    def test_older_download_is_ignored(self):
        self._download("2000-01-01")
        self.assertEqual(store.data_file("base_rates.json"), store.BUNDLED / "base_rates.json")

    def test_newer_download_wins(self):
        self._download("2999-01-01")
        self.assertEqual(store.data_file("base_rates.json"), store.DATA / "base_rates.json")
        # 내려받다 만 파일은 동봉본으로
        self.assertEqual(store.data_file("kosdaq_ipo.json"), store.BUNDLED / "kosdaq_ipo.json")

    def test_same_version_prefers_download(self):
        self._download(self.bundled_version)
        self.assertEqual(store.data_file("base_rates.json"), store.DATA / "base_rates.json")


class TestPredictRates(unittest.TestCase):
    """흑자 여부가 확률에 실제로 반영되는지. 안 되면 두 회사가 같은 값을 받는다."""

    def test_profit_and_loss_use_different_rates(self):
        prof, basis_p = predict._rates(True)
        loss, basis_l = predict._rates(False)
        self.assertNotEqual(prof["approval_rate"], loss["approval_rate"])
        self.assertGreater(prof["approval_rate"], loss["approval_rate"])
        self.assertIn("흑자", basis_p)
        self.assertIn("적자", basis_l)
        # 표본이 얇으면 노이즈를 확률로 내보내게 된다
        self.assertGreaterEqual(prof["n"], 100)
        self.assertGreaterEqual(loss["n"], 100)

    def test_profitable_company_gets_higher_probability(self):
        kw = dict(sector_tag="it_saas", stage=3, stage_date=None, revenue=5e10,
                  founded_year=2018, revenue_prev=4e10)
        p = predict.estimate(profitable=True, **kw)["probability"]
        l = predict.estimate(profitable=False, **kw)["probability"]
        self.assertGreater(p, l)

    def test_falls_back_when_by_profit_missing(self):
        br = dataset.base_rates()
        saved = br.get("by_profit")
        try:
            br["by_profit"] = {}
            rates, basis = predict._rates(True)
            self.assertEqual(basis, "코스닥 전체 최근 5년")
            self.assertIsNotNone(rates["approval_rate"])
        finally:
            br["by_profit"] = saved


class TestPreFilingHonesty(unittest.TestCase):
    """근거 없는 계수를 곱한 값에 없는 정밀도를 붙이면 안 된다."""

    KW = dict(sector_tag="industrial", revenue=7.5e10, profitable=False,
              founded_year=2018, revenue_prev=6.7e10)

    def test_pre_filing_probability_is_coarse(self):
        for stage in (0, 1, 2):
            r = predict.estimate(stage=stage, stage_date=None, **self.KW)
            self.assertTrue(r["probability_is_estimate"])
            # 5% 단위로 떨어져야 한다
            self.assertAlmostEqual(r["probability"] * 20, round(r["probability"] * 20), places=6)

    def test_filed_probability_keeps_precision(self):
        r = predict.estimate(stage=3, stage_date="2026-07-15", **self.KW)
        self.assertFalse(r["probability_is_estimate"])
        self.assertNotAlmostEqual(r["probability"] * 20, round(r["probability"] * 20), places=6)

    def test_pre_filing_reason_says_the_factor_is_unfounded(self):
        r = predict.estimate(stage=1, stage_date=None, **self.KW)
        self.assertTrue(any("근거 데이터가 없습니다" in x for x in r["reasons"]))


class TestUpdateCheck(unittest.TestCase):
    """데이터만 갱신해도 스킬이 최신인 것처럼 보이면 안 된다."""

    REMOTE = {"data_version": "2026-10-01", "skill_version": "0.2.0"}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._home, self._data = store.HOME, store.DATA
        self._check = store.LAST_CHECK
        store.HOME = Path(self.tmp)
        store.DATA = store.HOME / "data"
        store.PROFILES = store.HOME / "profiles"
        store.LAST_CHECK = store.HOME / "last_check"
        # 저장소의 VERSION 파일 값에 테스트가 끌려다니면 안 된다. 양쪽 다 고정한다.
        self._rm = update._remote_manifest
        self._rsv = update._remote_skill_version
        self._isv = update._installed_skill_version
        update._remote_manifest = lambda: self.REMOTE
        update._remote_skill_version = lambda r: "0.2.0"
        update._installed_skill_version = lambda: "0.1.0"

    def tearDown(self):
        store.HOME, store.DATA, store.LAST_CHECK = self._home, self._data, self._check
        store.PROFILES = store.HOME / "profiles"
        update._remote_manifest, update._remote_skill_version = self._rm, self._rsv
        update._installed_skill_version = self._isv
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_skill_update_survives_a_data_only_apply(self):
        first = update.check(force=True)
        self.assertTrue(first["skill"]["changed"])
        # update apply --data 는 원격 manifest를 통째로 내려받는다. 그 안에 skill_version이
        # 들어 있어, 예전에는 이 시점에 스킬도 최신으로 잘못 표시됐다.
        store.ensure()
        (store.DATA / "manifest.json").write_text(json.dumps(self.REMOTE), encoding="utf-8")
        after = update.check(force=True)
        self.assertFalse(after["data"]["changed"])
        self.assertTrue(after["skill"]["changed"])
        self.assertTrue(after["update_available"])

    def test_local_ahead_of_remote_is_not_an_update(self):
        # 아직 push 안 한 0.7.0 개발 폴더에서 원격 0.6.0을 "새 버전"이라고 하면 안 된다
        self.assertFalse(update._newer("0.6.0", "0.7.0"))
        self.assertTrue(update._newer("0.10.0", "0.9.0"))
        self.assertFalse(update._newer("2026-09-05", "2026-09-05"))
        self.assertTrue(update._newer("2026-10-01", "2026-09-05"))
        self.assertTrue(update._newer("0.1.0", None))

    def test_plugin_cache_is_never_git_pulled(self):
        # 플러그인은 ~/.claude/plugins/cache/<마켓>/<플러그인>/<버전>/ 에 복사본으로 들어온다.
        # 여기서 git pull을 시도하거나 "폴더를 덮어써라"고 하면 안 된다.
        saved = update.SKILL_ROOT
        try:
            update.SKILL_ROOT = Path(self.tmp) / ".claude" / "plugins" / "cache" / "ipo-eval" / "ipo-eval" / "0.7.0"
            update.SKILL_ROOT.mkdir(parents=True)
            self.assertEqual(update.install_method(), "plugin")
            res = update.apply(skill=True)
            self.assertEqual(res["skill"]["method"], "plugin")
            self.assertIn("/plugin update ipo-eval", res["skill"]["message"])
            self.assertNotIn("덮어써", res["skill"]["message"])
            self.assertEqual(update.check(force=True)["skill"]["how"], "/plugin update ipo-eval")
        finally:
            update.SKILL_ROOT = saved


if __name__ == "__main__":
    unittest.main(verbosity=2)
