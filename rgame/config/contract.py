"""配置契约。

按《数据与配置契约》实现：

- 通用字段：id / schema_version / enabled / tags / source_doc / notes；
- 范围、单位、必填字段校验；
- 跨引用一致性（preset → weapon，drop_table → enemy，weapon → damage...）。

校验失败抛出 :class:`SchemaError` 时阻止启动。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping


class SchemaError(ValueError):
    """配置错误；按《数据与配置契约》§4 在 ``error`` 级时阻止启动。"""


@dataclass
class ConfigBundle:
    enemies: dict[str, dict] = field(default_factory=dict)
    weapons: dict[str, dict] = field(default_factory=dict)
    cards: dict[str, dict] = field(default_factory=dict)
    drop_tables: dict[str, dict] = field(default_factory=dict)
    presets: dict[str, dict] = field(default_factory=dict)
    stages: dict[str, dict] = field(default_factory=dict)
    achievements: dict[str, dict] = field(default_factory=dict)
    schema_version: str = "0.1.0"
    config_version: str = "0.1.0"
    formula_version: str = "0.1.0"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _require(d: Mapping, path: str, *keys: str) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, Mapping) or k not in cur:
            raise SchemaError(f"缺少字段：{path}.{k}")
        cur = cur[k]
    return cur


def _check_positive(d: Mapping, path: str, value: float, *keys: str) -> None:
    if value <= 0 and not math.isnan(value):
        raise SchemaError(f"{path} 必须 > 0；当前 {value}")


def _check_nonneg(d: Mapping, path: str, value: float, *keys: str) -> None:
    if value < 0:
        raise SchemaError(f"{path} 必须 ≥ 0；当前 {value}")


# --- 校验函数 ----------------------------------------------------------------


def validate_enemy(cfg: Mapping[str, Any], *, path: str = "enemy") -> None:
    eid = _require(cfg, path, "id")
    _ = _require(cfg, f"{path}.{eid}", "archetype")
    hp = _require(cfg, f"{path}.{eid}", "max_hp")
    _check_positive(cfg, f"{path}.{eid}.max_hp", hp)
    speed = _require(cfg, f"{path}.{eid}", "move_speed")
    _check_nonneg(cfg, f"{path}.{eid}.move_speed", speed)
    cd = _require(cfg, f"{path}.{eid}", "attack_interval")
    _check_positive(cfg, f"{path}.{eid}.attack_interval", cd)
    dt = _require(cfg, f"{path}.{eid}", "drop_table_id")
    # 远程型 / 投射物参数若提供则要合法
    if "projectile_speed" in cfg:
        _check_positive(cfg, f"{path}.{eid}.projectile_speed", cfg["projectile_speed"])


def validate_weapon(cfg: Mapping[str, Any], *, path: str = "weapon") -> None:
    wid = _require(cfg, path, "id")
    base = _require(cfg, f"{path}.{wid}", "base_damage")
    _check_positive(cfg, f"{path}.{wid}.base_damage", base)
    interval = _require(cfg, f"{path}.{wid}", "attack_interval")
    _check_positive(cfg, f"{path}.{wid}.attack_interval", interval)
    sense = _require(cfg, f"{path}.{wid}", "sense_radius")
    rng = _require(cfg, f"{path}.{wid}", "attack_range")
    if rng > sense:
        raise SchemaError(
            f"{path}.{wid}.attack_range 必须 ≤ sense_radius（{rng} > {sense}）"
        )


def validate_card(cfg: Mapping[str, Any], *, path: str = "card") -> None:
    cid = _require(cfg, path, "id")
    tier = _require(cfg, f"{path}.{cid}", "tier")
    if tier not in ("silver", "gold", "color"):
        raise SchemaError(f"{path}.{cid}.tier 非法：{tier}")
    w = _require(cfg, f"{path}.{cid}", "weight")
    _check_positive(cfg, f"{path}.{cid}.weight", w)
    if "effects" in cfg:
        for i, eff in enumerate(cfg["effects"]):
            if "type" not in eff:
                raise SchemaError(f"{path}.{cid}.effects[{i}] 缺 type")


def validate_drop_table(cfg: Mapping[str, Any], *, path: str = "drop_table") -> None:
    did = _require(cfg, path, "id")
    items = _require(cfg, f"{path}.{did}", "entries")
    if not isinstance(items, list) or not items:
        raise SchemaError(f"{path}.{did}.entries 必须是非空列表")
    total = 0.0
    for i, it in enumerate(items):
        wt = it.get("weight", 0)
        if wt < 0:
            raise SchemaError(f"{path}.{did}.entries[{i}].weight < 0")
        total += wt
    if total <= 0:
        raise SchemaError(f"{path}.{did}.entries 总权重必须 > 0")


def validate_preset(cfg: Mapping[str, Any], *, path: str = "preset") -> None:
    pid = _require(cfg, path, "id")
    attrs = _require(cfg, f"{path}.{pid}", "attributes")
    _check_positive(cfg, f"{path}.{pid}.attributes.max_hp", attrs.get("max_hp", 0))
    _check_positive(cfg, f"{path}.{pid}.attributes.move_speed", attrs.get("move_speed", 0))
    weapons = cfg.get("weapon_stack")
    if not weapons or not isinstance(weapons, list):
        raise SchemaError(f"{path}.{pid}.weapon_stack 必须是非空列表")


def validate_achievement(cfg: Mapping[str, Any], *, path: str = "achievement") -> None:
    aid = _require(cfg, path, "id")
    series = _require(cfg, f"{path}.{aid}", "series")
    grade = _require(cfg, f"{path}.{aid}", "grade")
    if grade not in (1, 2, 3):
        raise SchemaError(f"{path}.{aid}.grade 必须是 1/2/3；当前 {grade}")
    _check_nonneg(cfg, f"{path}.{aid}", cfg.get("threshold", 0))


def validate_stage(cfg: Mapping[str, Any], *, path: str = "stage") -> None:
    sid = _require(cfg, path, "id")
    if "clear_score" not in cfg:
        raise SchemaError(f"{path}.{sid} 缺少 clear_score 字段（无尽模式可显式为 None）")
    cs = cfg.get("clear_score")
    if cs is not None and cs <= 0:
        raise SchemaError(f"{path}.{sid}.clear_score 必须 > 0（无尽模式可为空）")
    event = cfg.get("environment_event")
    if event is None:
        return
    event_path = f"{path}.{sid}.environment_event"
    for key in ("id", "name", "desc", "icon_id", "hazard_pattern", "hazard_icon"):
        value = _require(event, event_path, key)
        if not isinstance(value, str) or not value.strip():
            raise SchemaError(f"{event_path}.{key} 必须是非空字符串")
    if event["hazard_pattern"] not in ("mine_pulse", "rail_lock"):
        raise SchemaError(f"{event_path}.hazard_pattern 不支持：{event['hazard_pattern']!r}")
    for key in (
        "duration", "spawn_interval", "hazard_radius", "hazard_damage", "hazard_arm_delay",
    ):
        value = _require(event, event_path, key)
        if not isinstance(value, (int, float)) or value <= 0:
            raise SchemaError(f"{event_path}.{key} 必须是正数")
    spawn_count = _require(event, event_path, "spawn_count")
    if not isinstance(spawn_count, int) or spawn_count <= 0:
        raise SchemaError(f"{event_path}.spawn_count 必须是正整数")
    if event["hazard_arm_delay"] >= 2.5:
        raise SchemaError(f"{event_path}.hazard_arm_delay 必须小于炸弹引爆时长 2.5 秒")
    if event["duration"] < 0.5 + event["spawn_interval"] * (spawn_count - 1) + 2.5:
        raise SchemaError(f"{event_path}.duration 不足以容纳最后一枚危险标记的引爆时间")


def validate_config_bundle(bundle: ConfigBundle) -> None:
    """校验整个 bundle 的交叉引用。"""
    cfg = bundle
    errors: list[str] = []
    warnings: list[str] = []

    for enemy_id, enemy in cfg.enemies.items():
        try:
            validate_enemy(enemy)
        except SchemaError as e:
            errors.append(str(e))
        # drop_table_id
        dt = enemy.get("drop_table_id")
        if dt not in cfg.drop_tables:
            errors.append(f"enemy {enemy_id} 引用未知 drop_table {dt!r}")

    for wid, w in cfg.weapons.items():
        try:
            validate_weapon(w)
        except SchemaError as e:
            errors.append(str(e))

    for cid, c in cfg.cards.items():
        try:
            validate_card(c)
        except SchemaError as e:
            errors.append(str(e))

    for did, d in cfg.drop_tables.items():
        try:
            validate_drop_table(d)
        except SchemaError as e:
            errors.append(str(e))

    for pid, p in cfg.presets.items():
        try:
            validate_preset(p)
        except SchemaError as e:
            errors.append(str(e))
        for w in p.get("weapon_stack", []):
            if w not in cfg.weapons:
                errors.append(f"preset {pid} 引用未知 weapon {w!r}")

    for aid, a in cfg.achievements.items():
        try:
            validate_achievement(a)
        except SchemaError as e:
            errors.append(str(e))

    for sid, s in cfg.stages.items():
        try:
            validate_stage(s)
        except SchemaError as e:
            errors.append(str(e))

    # 卡的"适用武器"引用（若声明）
    for cid, c in cfg.cards.items():
        apply_to = c.get("applies_to_weapon")
        if apply_to is None:
            continue
        if apply_to in ("*", "active", "active_weapon"):
            continue
        if apply_to not in cfg.weapons:
            warnings.append(f"card {cid} 引用未知 weapon {apply_to!r}")

    cfg.errors.extend(errors)
    cfg.warnings.extend(warnings)

    if errors:
        msg = "config 校验失败：\n - " + "\n - ".join(errors)
        if warnings:
            msg += "\nwarn：\n - " + "\n - ".join(warnings)
        raise SchemaError(msg)
