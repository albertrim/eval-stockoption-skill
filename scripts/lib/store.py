"""~/.ipo-eval/ — 사용자 프로필과 내려받은 데이터. 이 폴더 밖으로 나가는 것은 없다."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

HOME = Path(os.environ.get("IPO_EVAL_HOME") or (Path.home() / ".ipo-eval"))
DATA = HOME / "data"
PROFILES = HOME / "profiles"
LAST_CHECK = HOME / "last_check"
BUNDLED = Path(__file__).resolve().parents[2] / "data"


def ensure() -> None:
    PROFILES.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)


def _data_version(p: Path) -> str:
    try:
        return str(json.loads(p.read_text(encoding="utf-8")).get("data_version") or "")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""


def downloaded_is_current() -> bool:
    """내려받은 데이터가 동봉 데이터보다 오래되지 않았는지.

    플러그인 업데이트는 새 코드와 새 동봉 데이터를 같이 가져온다. 그 뒤에도 예전에 내려받은
    사본이 남아 있으면 새 코드가 옛 데이터를 읽는다. 기준일이 더 새로운 쪽을 쓴다.
    """
    d, b = DATA / "manifest.json", BUNDLED / "manifest.json"
    if not d.exists():
        return False
    if not b.exists():
        return True
    return _data_version(d) >= _data_version(b)


def data_file(name: str) -> Path:
    """내려받은 사본과 동봉 사본 중 기준일이 새로운 쪽. 같으면 내려받은 쪽."""
    p = DATA / name
    if p.exists() and downloaded_is_current():
        return p
    return BUNDLED / name


def load_data(name: str) -> dict:
    p = data_file(name)
    if not p.exists():
        raise FileNotFoundError(
            f"데이터 파일이 없습니다: {name}. `ipo_eval.py update apply --data` 로 내려받으세요."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def slug(name: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|\s]+", "_", (name or "").strip())
    return s[:60] or "unnamed"


def profile_path(name: str) -> Path:
    return PROFILES / f"{slug(name)}.json"


def list_profiles() -> list[dict]:
    ensure()
    out = []
    for p in sorted(PROFILES.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.append({"name": d.get("name") or p.stem, "path": str(p),
                    "updated_at": d.get("updated_at"), "options": len(d.get("options") or [])})
    return out


def load_profile(name: str) -> dict | None:
    p = profile_path(name)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_profile(profile: dict) -> Path:
    ensure()
    profile["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    p = profile_path(profile.get("name", ""))
    p.write_text(json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8")
    return p
