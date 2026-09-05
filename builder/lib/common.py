"""빌더 공통 — HTTP 캐시, 요청 간격, 파싱 헬퍼."""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "builder" / ".cache"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

_last_hit: dict[str, float] = {}


def _throttle(host: str, gap: float) -> None:
    prev = _last_hit.get(host, 0.0)
    wait = gap - (time.time() - prev)
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()


def fetch(url: str, *, encoding: str = "utf-8", ns: str = "misc", key: str | None = None,
          gap: float = 0.4, refresh: bool = False, timeout: int = 25) -> str:
    """GET 후 텍스트 반환. ns/key로 디스크 캐시. 캐시 적중 시 네트워크 안 씀."""
    key = key or hashlib.sha1(url.encode()).hexdigest()[:16]
    path = CACHE / ns / f"{key}.html"
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    _throttle(ns, gap)
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    r.encoding = encoding
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(r.text, encoding="utf-8")
    return r.text


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def leaf_tables(bs: BeautifulSoup):
    """중첩 테이블의 최말단만 — 38커뮤니케이션은 레이아웃 테이블이 겹겹이다."""
    return [t for t in bs.select("table") if not t.select("table")]


def num(s: str | None) -> float | None:
    """'-20,950 (백만원)' → -20950.0 / '(11,318)' → -11318.0 / None."""
    if s is None:
        return None
    s = s.strip()
    if not s or s in {"-", "—", "n.a.", "N/A"}:
        return None
    neg = s.startswith("(") and ")" in s
    m = re.search(r"-?[\d,]+(?:\.\d+)?", s)
    if not m:
        return None
    v = float(m.group().replace(",", ""))
    return -abs(v) if neg else v


def pairs(table) -> dict[str, str]:
    """th/td가 라벨-값으로 번갈아 오는 표를 dict로."""
    out: dict[str, str] = {}
    for tr in table.select("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.select("th,td")]
        for i in range(0, len(cells) - 1, 2):
            label = cells[i].replace("\xa0", " ").strip()
            if label and label not in out:
                out[label] = cells[i + 1].replace("\xa0", " ").strip()
    return out


def eok(v: float | None) -> int | None:
    """억원 → 원(정수)."""
    return None if v is None else int(round(v * 100_000_000))


def mkrw(v: float | None) -> int | None:
    """백만원 → 원(정수)."""
    return None if v is None else int(round(v * 1_000_000))
