"""데이터셋 접근 — 상장사 목록, 청구 이력, 기준율, 세제 파라미터."""
from __future__ import annotations

import functools

from . import store


@functools.lru_cache(maxsize=1)
def companies() -> list[dict]:
    return store.load_data("kosdaq_ipo.json")["companies"]


@functools.lru_cache(maxsize=1)
def data_as_of() -> str:
    return store.load_data("kosdaq_ipo.json").get("as_of", "?")


@functools.lru_cache(maxsize=1)
def base_rates() -> dict:
    return store.load_data("base_rates.json")


@functools.lru_cache(maxsize=1)
def pipeline() -> dict:
    return store.load_data("pipeline.json")


@functools.lru_cache(maxsize=1)
def tax_params() -> dict:
    return store.load_data("tax_params.json")


@functools.lru_cache(maxsize=1)
def backtest() -> dict:
    """모델을 과거 상장사에 거꾸로 적용했을 때의 오차. 없으면 빈 dict."""
    try:
        bt = store.load_data("manifest.json").get("backtest") or {}
    except (FileNotFoundError, ValueError):
        return {}
    if not bt.get("n"):
        return {}
    return {"n": bt["n"], "mape_median": bt.get("mape_median"),
            "inside_rate": bt.get("inside_low_high_rate", bt.get("inside_p25_p75_rate"))}


SECTOR_LABEL = {
    "it_saas": "IT·소프트웨어", "ai_data": "AI·데이터", "bio_health": "바이오·헬스케어",
    "beauty": "화장품·뷰티", "ecommerce_platform": "이커머스·플랫폼", "fintech": "핀테크·금융",
    "content_game": "콘텐츠·게임", "hardware_semi": "하드웨어·반도체",
    "industrial": "제조·산업재", "other": "기타",
}
