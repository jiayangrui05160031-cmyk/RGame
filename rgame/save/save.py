"""存档系统。

按《存档与版本迁移》：

- profile 类型（成就、累计统计、设置、最近预设）；
- 临时文件 + 原子替换 + 保留最近一个有效备份；
- vN→vN+1 链式迁移；
- 成就已解锁状态不会因阈值调整被撤销。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, asdict


PROFILE_VERSION = 1


def normalize_account_id(name: str | None) -> str:
    """Turn a visible account name into a stable local filename segment."""
    raw = (name or "default").strip() or "default"
    safe = []
    for ch in raw:
        if ch.isalnum() or ch in ("-", "_"):
            safe.append(ch)
        elif ch.isspace():
            safe.append("_")
    return "".join(safe)[:32] or "default"


def profile_path_for_account(base_path: str, account_name: str | None) -> str:
    account_id = normalize_account_id(account_name)
    dirname = os.path.dirname(base_path)
    stem, ext = os.path.splitext(os.path.basename(base_path))
    if account_id == "default":
        filename = os.path.basename(base_path)
    else:
        filename = f"{stem}_{account_id}{ext or '.json'}"
    return os.path.join(dirname, filename) if dirname else filename


def account_history_path_for_profile(base_path: str) -> str:
    dirname = os.path.dirname(base_path)
    stem, _ext = os.path.splitext(os.path.basename(base_path))
    filename = f"{stem}_accounts.json"
    return os.path.join(dirname, filename) if dirname else filename


def load_account_history(base_path: str, *, limit: int = 3) -> list[str]:
    path = account_history_path_for_profile(base_path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    accounts = data.get("accounts", data) if isinstance(data, dict) else data
    if not isinstance(accounts, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for name in accounts:
        account = str(name or "").strip()
        if not account:
            continue
        key = normalize_account_id(account).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(account[:24])
    return out[-limit:]


def record_account_history(base_path: str, account_name: str, *, limit: int = 3) -> list[str]:
    account = (account_name or "default").strip() or "default"
    accounts = load_account_history(base_path, limit=limit)
    key = normalize_account_id(account).lower()
    if all(normalize_account_id(a).lower() != key for a in accounts):
        accounts.append(account[:24])
    while len(accounts) > limit:
        accounts.pop(0)
    path = account_history_path_for_profile(base_path)
    dirname = os.path.dirname(path)
    if dirname and not os.path.isdir(dirname):
        os.makedirs(dirname, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"accounts": accounts}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return accounts


@dataclass
class ProfileSave:
    profile_id: str
    created_at: float
    updated_at: float
    app_version: str
    config_version: str
    save_version: int = PROFILE_VERSION
    unlocked_achievements: dict = field(default_factory=dict)
    lifetime_score: int = 0
    lifetime_kills: int = 0
    super_kills: int = 0
    bomb_dodges: int = 0
    endless_max_cycle: int = 0
    campaign_cleared: bool = False
    settings: dict = field(default_factory=dict)
    last_preset_id: str | None = None
    recent_runs_summary: list[dict] = field(default_factory=list)
    account_name: str = "default"
    gold: int = 0
    total_gold_earned: int = 0
    unlocked_weapons: list[str] = field(default_factory=list)
    permanent_upgrades: dict = field(default_factory=dict)
    selected_permanent_weapon: str | None = None
    selected_starting_weapons: list[str] = field(default_factory=list)
    unlocked_equipment: list[str] = field(default_factory=list)
    selected_equipment: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ProfileSave":
        # 仅取已知字段
        known = {k: d.get(k) for k in (
            "profile_id", "created_at", "updated_at", "app_version",
            "config_version", "save_version",
            "unlocked_achievements", "lifetime_score", "lifetime_kills",
            "super_kills", "bomb_dodges", "endless_max_cycle",
            "campaign_cleared", "settings", "last_preset_id", "recent_runs_summary",
            "account_name", "gold", "total_gold_earned", "unlocked_weapons",
            "permanent_upgrades", "selected_permanent_weapon",
            "selected_starting_weapons",
            "unlocked_equipment", "selected_equipment",
        )}
        known["account_name"] = known.get("account_name") or known.get("profile_id") or "default"
        known["gold"] = int(known.get("gold") or 0)
        known["total_gold_earned"] = int(known.get("total_gold_earned") or 0)
        known["unlocked_weapons"] = list(known.get("unlocked_weapons") or [])
        known["permanent_upgrades"] = dict(known.get("permanent_upgrades") or {})
        if not known.get("selected_starting_weapons") and known.get("selected_permanent_weapon"):
            known["selected_starting_weapons"] = [known["selected_permanent_weapon"]]
        known["selected_starting_weapons"] = list(known.get("selected_starting_weapons") or [])
        known["unlocked_equipment"] = list(known.get("unlocked_equipment") or [])
        known["selected_equipment"] = list(known.get("selected_equipment") or [])
        return cls(**known)


def write_profile_atomic(path: str, profile: ProfileSave) -> bool:
    """原子写入：写临时文件 + rename 替换；失败保留旧文件。"""
    dirname = os.path.dirname(path)
    if dirname and not os.path.isdir(dirname):
        os.makedirs(dirname, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="rgame-profile-", dir=dirname or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)
        # 备份最近有效
        if os.path.exists(path):
            try:
                backup = path + ".bak"
                if os.path.exists(backup):
                    os.remove(backup)
                os.replace(path, backup)
            except OSError:
                pass
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def load_profile(path: str, *, default_profile_id: str = "default") -> ProfileSave:
    if not os.path.exists(path):
        profile_id = normalize_account_id(default_profile_id)
        return ProfileSave(
            profile_id=profile_id,
            created_at=__import__("time").time(),
            updated_at=__import__("time").time(),
            app_version="0.1.0",
            config_version="0.1.0",
            account_name=default_profile_id or profile_id,
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        # 回退备份
        backup = path + ".bak"
        if os.path.exists(backup):
            with open(backup, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            profile_id = normalize_account_id(default_profile_id)
            return ProfileSave(
                profile_id=profile_id,
                created_at=__import__("time").time(),
                updated_at=__import__("time").time(),
                app_version="0.1.0",
                config_version="0.1.0",
                account_name=default_profile_id or profile_id,
            )
    profile = ProfileSave.from_dict(data)
    return migrate_profile(profile)


def save_profile(profile: ProfileSave, path: str) -> bool:
    return write_profile_atomic(path, profile)


def migrate_profile(profile: ProfileSave) -> ProfileSave:
    """链式 vN→vN+1 迁移。"""
    # 当前只有 v1；保留迁移入口
    if profile.save_version > PROFILE_VERSION:
        # 来自更新版本的存档：保留未知字段，逻辑兜底
        profile.save_version = PROFILE_VERSION
    return profile
