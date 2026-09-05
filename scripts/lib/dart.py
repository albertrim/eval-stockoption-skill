"""DART 전자공시 조회 — 회사 이름으로 기업개황·감사보고서 수치를 가져온다.

표준 라이브러리만 쓴다. 키가 없거나 못 찾으면 조용히 실패하고, 호출한 쪽은 사용자에게
직접 묻는 기존 흐름으로 돌아간다.

키를 찾는 순서: 환경변수 DART_API_KEY → ~/.ipo-eval/dart_key → <스킬>/builder/.env
키는 https://opendart.fss.or.kr 에서 무료로 발급받는다.
"""
from __future__ import annotations

import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from . import store

API = "https://opendart.fss.or.kr/api"
TIMEOUT = 20
CORP_TTL = 7 * 86400
SKILL_ROOT = Path(__file__).resolve().parents[2]
CACHE = store.HOME / "cache"

EOK = 100_000_000


def key() -> str:
    k = (os.environ.get("DART_API_KEY") or "").strip()
    if k:
        return k
    f = store.HOME / "dart_key"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    env = SKILL_ROOT / "builder" / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DART_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _get(path: str, **params) -> bytes:
    url = f"{API}/{path}?" + urllib.parse.urlencode({**params, "crtfc_key": key()})
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        return r.read()


def _corp_xml() -> Path:
    """전체 기업 코드표(약 30MB). 7일 캐시."""
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / "CORPCODE.xml"
    if p.exists() and (time.time() - p.stat().st_mtime) < CORP_TTL:
        return p
    with zipfile.ZipFile(io.BytesIO(_get("corpCode.xml"))) as z:
        p.write_bytes(z.read(z.namelist()[0]))
    return p


def _norm(s: str) -> str:
    return re.sub(r"주식회사|㈜|\(주\)|\s+", "", s or "")


RANK = {"exact": 0, "contains": 1, "renamed": 2}


def _match(want: str, n: str) -> str | None:
    """사명 변경이 잦다. 옛 이름으로 등록된 회사를 새 이름으로도 찾아야 한다."""
    if n == want:
        return "exact"
    if want in n:
        return "contains"
    if len(n) >= 3 and n in want:
        return "renamed"
    return None


def search(name: str) -> list[dict]:
    """이름으로 기업을 찾는다. 정확히 맞는 것을 앞에 둔다."""
    want = _norm(name)
    if not want:
        return []
    hits = []
    for _, e in ET.iterparse(_corp_xml(), events=("end",)):
        if e.tag != "list":
            continue
        raw = e.findtext("corp_name") or ""
        how = _match(want, _norm(raw))
        if how:
            hits.append({"corp_code": e.findtext("corp_code"), "corp_name": raw,
                         "stock_code": (e.findtext("stock_code") or "").strip(),
                         "matched": how, "exact": how == "exact"})
        e.clear()
    hits.sort(key=lambda h: (RANK[h["matched"]], len(h["corp_name"])))
    return hits[:10]


def company(corp_code: str) -> dict:
    return json.loads(_get("company.json", corp_code=corp_code).decode("utf-8"))


def filings(corp_code: str) -> list[dict]:
    """감사보고서·사업보고서 목록을 최근 것부터."""
    y = time.gmtime().tm_year
    d = json.loads(_get("list.json", corp_code=corp_code, bgn_de=f"{y - 6}0101",
                        end_de=time.strftime("%Y%m%d"), page_count=100).decode("utf-8"))
    if d.get("status") != "000":
        return []
    keep = [x for x in d.get("list", [])
            if "감사보고서" in x["report_nm"] or "사업보고서" in x["report_nm"]]
    return sorted(keep, key=lambda x: x["rcept_dt"], reverse=True)


def _text(rcept_no: str) -> str:
    """공시 한 건의 본문 전체.

    사업보고서 zip에는 본문과 첨부(감사보고서·연결감사보고서)가 함께 들어 있다. 첨부까지
    이어 붙이면 자회사 손익표의 '매출액'을 회사 매출로 읽는다. 본문만 읽는다.
    """
    with zipfile.ZipFile(io.BytesIO(_get("document.xml", rcept_no=rcept_no))) as z:
        names = z.namelist()
        main = f"{rcept_no}.xml"
        pick = main if main in names else max(names, key=lambda n: z.getinfo(n).file_size)
        raw = z.read(pick).decode("utf-8", "replace")
    t = re.sub(r"<[^>]+>", "\n", raw)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"')):
        t = t.replace(a, b)
    return "\n".join(x for x in (l.strip() for l in t.split("\n")) if x)


NUM = r"\(?-?[\d,]{4,}\)?"


def _num(s: str) -> float | None:
    s = s.strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "")
    if not re.fullmatch(r"-?\d+", s):
        return None
    v = float(s)
    return -v if neg else v


# 재무제표 표는 원·천원·백만원을 섞어 쓴다. 단위를 안 보면 매출 1.7조가 17억으로 읽힌다.
UNIT = {"원": 1, "천원": 1_000, "백만원": 1_000_000, "십억원": 1_000_000_000}
UNIT_RE = re.compile(r"단위\s*[::]?\s*(십억원|백만원|천원|원)")


def _scale_at(txt: str, pos: int) -> int:
    """표 라벨 바로 앞에 적힌 '(단위 : 천원)'을 찾아 배수를 돌려준다."""
    head = txt[max(0, pos - 4000):pos]
    ms = UNIT_RE.findall(head)
    return UNIT[ms[-1]] if ms else 1


WINDOW = 40   # 라벨 뒤 이만큼의 줄 안에서만 숫자를 찾는다. 넘어가면 다른 표다.


def _after(txt: str, label: str, count: int = 2) -> tuple[list[float], int]:
    """표에서 라벨 바로 뒤에 오는 숫자들. 주석번호(2자리 이하)는 건너뛴다."""
    m = re.search(re.escape(label) + r"\s*\n((?:.*\n){0,3}?)", txt)
    if not m:
        return [], -1
    out = []
    for line in txt[m.end():].split("\n", WINDOW)[:WINDOW]:
        v = _num(line)
        if v is None:
            if len(out) >= count or re.search(r"[가-힣]", line) and out:
                break
            continue
        if abs(v) < 1000 and not out:      # 주석 번호
            continue
        out.append(v)
        if len(out) >= count:
            break
    return out, m.start()


# 라벨 없이 '매출액'만 찾으면 주석 표의 아무 숫자나 물어온다. 손익계산서·요약재무정보의
# 로마숫자 항목만 인정한다. 못 찾으면 값을 내지 않고 사용자에게 묻는다.
def _roman(*words: str) -> tuple[str, ...]:
    out = []
    for w in words:
        for r in ("Ⅰ", "I", "Ⅳ", "IV", "Ⅲ", "III"):
            out += [f"{r}. {w}", f"{r}.{w}"]
    return tuple(out)


REV_LABELS = _roman("매출액", "영업수익")
OP_LABELS = _roman("영업이익(손실)", "영업이익")
LOSS_LABELS = _roman("영업손실")
# 사업보고서 요약재무정보는 로마숫자 없이 '매출액', '영업손익'으로만 적는 회사가 많다(컬리 등).
# 요약재무정보 표 안에서만 맨몸 라벨을 허용한다. 문서 전체에서 허용하면 주석 표를 물어온다.
BARE_REV_LABELS = ("매출액", "영업수익")
BARE_OP_LABELS = ("영업이익(손실)", "영업손익", "영업이익")
BARE_LOSS_LABELS = ("영업손실",)
SUMMARY_SPAN = 20_000


def _pick(seg: str, labels, count: int = 2) -> tuple[list[float], int]:
    """찾은 값에 표 단위를 곱해 원 단위로 맞춘다."""
    for lb in labels:
        v, pos = _after(seg, lb, count)
        if v:
            k = _scale_at(seg, pos)
            return [x * k for x in v], pos
    return [], -1


# "요약연결재무정보"도 "요약 연결 재무정보"도 있다(컬리). 띄어쓰기를 무시하지 않으면 연결 표를
# 별도라고 적는다.
HEAD_RE = re.compile(r"요약\s*(연결|별도)?\s*재무정보")


def _basis_at(seg: str, pos: int) -> str | None:
    """이 표가 연결인지 별도인지. 바로 앞의 소제목으로 정한다.

    문서에 '가. 요약연결재무정보'와 '나. 요약재무정보'가 나란히 실린다. 근처에 '연결'이
    있는지 세는 식으로 짐작하면 연결 숫자를 별도라고 적는다. 사용자가 확인해야 하는
    값이라 틀린 라벨은 값이 틀린 것과 같다.
    """
    ms = HEAD_RE.findall(seg[:pos])
    if not ms:
        return None
    return "연결" if ms[-1] == "연결" else "별도"


def _income(txt: str) -> dict:
    """매출액·영업손익. 사업보고서는 요약재무정보 표, 감사보고서는 손익계산서에서 읽는다.

    연결을 먼저 본다. 상장 공모 평가도 연결 기준으로 한다.
    """
    i = txt.find("요약재무정보")
    seg = txt[i:] if i >= 0 else txt
    rev, pos = _pick(seg, REV_LABELS)
    op, _ = _pick(seg, OP_LABELS)
    loss = False
    if not op:
        op, _ = _pick(seg, LOSS_LABELS)
        loss = bool(op)
    if i >= 0:
        summary = seg[:SUMMARY_SPAN]
        if not rev:
            rev, pos = _pick(summary, BARE_REV_LABELS)
        if not op:
            op, _ = _pick(summary, BARE_OP_LABELS)
            if not op:
                op, _ = _pick(summary, BARE_LOSS_LABELS)
                loss = bool(op)
    # '영업손실' 라벨이면 값이 양수로 적혀 있어도 손실이다. 그 밖의 라벨은 괄호 음수를 믿는다.
    operating_income = None
    if op:
        operating_income = -abs(op[0]) if loss else op[0]
    return {"basis": _basis_at(seg, pos) if rev else None,
            "revenue": rev[0] if rev else None,
            "revenue_prev": rev[1] if len(rev) > 1 else None,
            "operating_income": operating_income}


def _shares(txt: str) -> dict:
    """자본금 주석의 보통주 수와, 우선주 발행조건 표의 발행주식수 합계.

    보통주만으로는 상장 시 주식수가 안 나온다. 부채로 분류된 전환우선주가 상장 전에
    보통주로 바뀌기 때문이다. 둘 다 돌려주고 어느 쪽을 쓸지는 사람이 정한다.
    """
    # 사업보고서는 '주식의 총수 현황' 표가 우선주까지 합산해 준다. 합계는 각 열보다
    # 크거나 같으므로 최댓값을 고르면 열 순서를 몰라도 맞는다.
    # 같은 문구가 본문 문장("발행주식의 총수는 보통주식 N주 입니다")에 먼저 나오기도 한다.
    # 숫자가 따라오는 첫 번째 것, 즉 표를 쓴다.
    for m in re.finditer(r"발행주식의 총수[^\n]*\n((?:[^\n]*\n){0,4})", txt):
        vals = [v for v in (_num(x) for x in m.group(1).split("\n")) if v]
        if vals:
            n = int(max(vals))
            return {"common": None, "preferred": None, "diluted": n, "total": n}

    common = None
    m = re.search(r"발행한 (?:보통주식 주식수|주식의 총수)[^\n]*\n\s*([\d,]+)\s*주", txt)
    if m:
        common = int(m.group(1).replace(",", ""))
    pref = 0
    for m in re.finditer(r"^발행주식수\s*$", txt, re.M):
        for line in txt[m.end():].split("\n")[1:8]:
            v = _num(line)
            if v is None:
                break
            pref += int(v)
    return {"common": common, "preferred": pref or None,
            "diluted": (common + pref) if common and pref else common,
            "total": None}


def _options(txt: str) -> dict:
    """주식기준보상 주석의 기말 미행사 수량.

    '기 말' 행은 퇴직급여·차입금 주석에도 나온다. 주석 범위 안으로 좁히지 않으면
    엉뚱한 표의 숫자를 물어온다.
    """
    i = max(txt.find("주식기준보상"), txt.find("주식매수선택권"))
    if i < 0:
        return {"outstanding": None, "exercisable": None}
    seg = txt[i:i + 8000]
    m = re.search(r"기\s*말\s*\n\s*([\d,]+)\s*\n\s*([\d,]+)\s*\n", seg)
    m2 = re.search(r"기말 행사가능한 주식수\s*\n\s*([\d,]+)", seg)
    return {"outstanding": int(m.group(1).replace(",", "")) if m else None,
            "exercisable": int(m2.group(1).replace(",", "")) if m2 else None}


def lookup(name: str) -> dict:
    """회사 이름 하나로 DART를 훑어 프로필에 넣을 값을 모은다."""
    if not key():
        return {"ok": False, "reason": "no_key",
                "message": "DART API 키가 없어 건너뜁니다. opendart.fss.or.kr 에서 발급받아 "
                           "DART_API_KEY 환경변수나 ~/.ipo-eval/dart_key 에 넣으면 다음부터 씁니다."}
    try:
        hits = search(name)
    except (urllib.error.URLError, TimeoutError, OSError, zipfile.BadZipFile, ET.ParseError) as e:
        return {"ok": False, "reason": "offline", "message": f"DART에 닿지 못했습니다: {e}"}
    if not hits:
        return {"ok": False, "reason": "not_found",
                "message": f"DART에 '{name}'으로 등록된 기업이 없습니다."}
    top = hits[0]
    try:
        info = company(top["corp_code"])
        docs = filings(top["corp_code"])
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        return {"ok": False, "reason": "offline", "message": f"DART에 닿지 못했습니다: {e}"}

    est = info.get("est_dt") or ""
    out = {"ok": True, "corp_code": top["corp_code"], "corp_name": info.get("corp_name") or top["corp_name"],
           "listed": bool((info.get("stock_code") or "").strip()),
           "founded_year": int(est[:4]) if len(est) >= 4 and est[:4].isdigit() else None,
           "established": est, "candidates": hits[:5], "report": None, "financials": None,
           "shares": None, "stock_options": None}
    if not docs:
        out["message"] = "감사보고서가 없습니다. 값은 직접 물어봐야 합니다."
        return out

    # 가장 최근 보고서를 쓴다. 감사보고서만 고르면 사업보고서를 내기 시작한 회사에서
    # 몇 년 묵은 숫자를 읽는다. 같은 날짜에 둘 다 있으면 별도(연결 아님)를 먼저 본다.
    latest = docs[0]["rcept_dt"]
    same = [d for d in docs if d["rcept_dt"] == latest]
    doc = next((d for d in same if not d["report_nm"].startswith("연결")), same[0])
    try:
        txt = _text(doc["rcept_no"])
    except (urllib.error.URLError, TimeoutError, OSError, zipfile.BadZipFile) as e:
        out["message"] = f"감사보고서 본문을 읽지 못했습니다: {e}"
        return out

    out["report"] = {"name": doc["report_nm"].strip(), "rcept_no": doc["rcept_no"],
                     "rcept_dt": doc["rcept_dt"]}
    fin, sh, so = _income(txt), _shares(txt), _options(txt)
    if fin.get("basis") is None and "감사보고서" in doc["report_nm"]:
        # 요약재무정보가 없는 감사보고서는 보고서 이름이 곧 기준이다.
        fin["basis"] = "연결" if doc["report_nm"].startswith("연결") else "별도"
    out["dropped"] = _sanitize(fin, sh, so)
    out["financials"], out["shares"], out["stock_options"] = fin, sh, so
    if out["dropped"]:
        out["message"] = ("보고서에서 읽지 못한 항목이 있습니다(" + ", ".join(out["dropped"]) +
                          "). 그 값은 사용자에게 직접 물어보세요.")
    return out


MAX_REVENUE = 1e15          # 1,000조. 이보다 크면 표를 잘못 읽은 것이다
# 표 단위가 원이 아니라 천원·백만원이면 값이 1,000배 작게 잡힌다. 매출 1억이 안 되는
# 회사는 상장 후보가 아니므로, 그런 값은 단위를 잘못 읽은 것으로 보고 버린다.
MIN_REVENUE = 100_000_000
MAX_OP_RATIO = 3.0          # 영업손익이 매출의 3배를 넘으면 다른 표를 읽은 것이다
MAX_SHARES = 5_000_000_000


def _sanitize(fin: dict, sh: dict, so: dict) -> list[str]:
    """자릿수가 틀린 값이 조용히 시총 계산으로 흘러가면 안 된다. 의심스러우면 버린다."""
    dropped = []
    r, rp = fin.get("revenue"), fin.get("revenue_prev")
    if r is not None and not (MIN_REVENUE <= r < MAX_REVENUE):
        fin["revenue"] = r = None
        dropped.append("매출액")
    if rp is not None and (r is None or not (MIN_REVENUE <= rp < MAX_REVENUE) or rp == r):
        # 당기 매출을 못 믿으면 전년도 값도 못 믿는다. 같은 값이면 한 칸을 두 번 읽은 것이다
        fin["revenue_prev"] = None
        dropped.append("전년 매출액")
    op = fin.get("operating_income")
    if op is not None and (r is None or abs(op) > r * MAX_OP_RATIO):
        fin["operating_income"] = None
        dropped.append("영업손익")

    n = sh.get("diluted") or sh.get("total")
    if n is not None and not (100 <= n <= MAX_SHARES):
        for k in ("common", "preferred", "diluted", "total"):
            sh[k] = None
        n = None
        dropped.append("발행주식수")
    for k in ("outstanding", "exercisable"):
        v = so.get(k)
        if v is not None and (v <= 0 or v > MAX_SHARES or (n and v > n)):
            so[k] = None
            dropped.append(f"스톡옵션({k})")
    return dropped
