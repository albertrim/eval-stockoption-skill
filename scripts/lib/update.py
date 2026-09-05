"""데이터·스킬 업데이트 — GitHub의 정적 파일만 읽는다. 보내는 것은 없다."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import store

REPO = "albertrim/eval-stockoption-skill"
RAW_ROOT = f"https://raw.githubusercontent.com/{REPO}/main"
RAW = f"{RAW_ROOT}/data"
FILES = ("manifest.json", "kosdaq_ipo.json", "pipeline.json", "base_rates.json", "tax_params.json")
CHECK_INTERVAL = 24 * 3600
TIMEOUT = 4
SKILL_ROOT = Path(__file__).resolve().parents[2]


def _local_manifest() -> dict:
    try:
        return store.load_data("manifest.json")
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _remote_manifest() -> dict | None:
    try:
        with urllib.request.urlopen(f"{RAW}/manifest.json", timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _installed_skill_version() -> str | None:
    """설치된 스킬 코드의 버전. 내려받은 manifest가 아니라 폴더의 VERSION을 본다.

    manifest.json에는 데이터와 스킬 버전이 같이 들어 있다. 데이터만 갱신해도 그 파일이
    통째로 덮어써져, 코드는 옛 버전 그대로인데 최신이라고 나온다.
    """
    p = SKILL_ROOT / "VERSION"
    if p.exists():
        v = p.read_text(encoding="utf-8").strip()
        if v:
            return v
    try:
        return json.loads((store.BUNDLED / "manifest.json").read_text(encoding="utf-8")
                          ).get("skill_version")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _remote_skill_version(remote: dict) -> str | None:
    """저장소의 VERSION 파일. 이것만 올리면 사용자에게 새 버전이 보이게 한다."""
    try:
        with urllib.request.urlopen(f"{RAW_ROOT}/VERSION", timeout=TIMEOUT) as r:
            v = r.read().decode("utf-8").strip()
            if v:
                return v
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError):
        pass
    return remote.get("skill_version")


def check(force: bool = False) -> dict:
    store.ensure()
    local = _local_manifest()
    if not force and store.LAST_CHECK.exists():
        age = time.time() - store.LAST_CHECK.stat().st_mtime
        if age < CHECK_INTERVAL:
            return {"ok": True, "skipped": "24시간 안에 이미 확인했습니다",
                    "data_version": local.get("data_version")}
    remote = _remote_manifest()
    store.LAST_CHECK.write_text(str(time.time()))
    if remote is None:
        return {"ok": True, "offline": True, "message": "업데이트 서버에 닿지 못했습니다. 가진 데이터로 진행합니다.",
                "data_version": local.get("data_version")}
    data_new = remote.get("data_version") != local.get("data_version")
    skill_local, skill_remote = _installed_skill_version(), _remote_skill_version(remote)
    skill_new = bool(skill_remote) and skill_remote != skill_local
    return {
        "ok": True, "update_available": bool(data_new or skill_new),
        "data": {"local": local.get("data_version"), "remote": remote.get("data_version"),
                 "changed": data_new},
        "skill": {"local": skill_local, "remote": skill_remote, "changed": skill_new},
        "companies": remote.get("companies"),
    }


def apply(*, data: bool = False, skill: bool = False) -> dict:
    store.ensure()
    result: dict = {"ok": True}
    if data:
        got, failed = [], []
        for name in FILES:
            tmp = store.DATA / f"{name}.part"
            try:
                with urllib.request.urlopen(f"{RAW}/{name}", timeout=30) as r:
                    body = r.read()
                json.loads(body.decode("utf-8"))       # 깨진 파일을 덮어쓰지 않는다
                tmp.write_bytes(body)
                shutil.move(str(tmp), store.DATA / name)
                got.append(name)
            except Exception as e:  # noqa: BLE001
                tmp.unlink(missing_ok=True)
                failed.append(f"{name}: {e}")
        result["data"] = {"downloaded": got, "failed": failed}
        result["ok"] = not failed
    if skill:
        if (SKILL_ROOT / ".git").exists():
            p = subprocess.run(["git", "-C", str(SKILL_ROOT), "pull", "--ff-only"],
                               capture_output=True, text=True, timeout=60)
            result["skill"] = {"method": "git pull", "returncode": p.returncode,
                               "output": (p.stdout + p.stderr).strip()}
            result["ok"] = result["ok"] and p.returncode == 0
        else:
            result["skill"] = {
                "method": "manual",
                "message": f"git으로 설치한 폴더가 아닙니다. https://github.com/{REPO} 에서 "
                           f"다시 받아 {SKILL_ROOT} 를 덮어써 주세요. "
                           "입력한 프로필은 ~/.ipo-eval/ 에 있어 지워지지 않습니다.",
            }
    return result
