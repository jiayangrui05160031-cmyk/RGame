"""游戏引擎（核心调度层）。

职责：

- 把 ``StateMachine``、``EventBus``、``TimeKeeper``、``NameRng``；
- 让 ``Combat / Enemies / Drops / Cards / Level / Achievements`` 全部基于同一个 ``RunContext``；
- 每帧调用 :py:meth:`tick`：
    1. 输入采样；
    2. 玩家移动；
    3. 敌人推进 / 死亡；
    4. 武器循环推进 / 投射物推进；
    5. 命中检测 / 伤害结算；
    6. 掉落拾取 / 炸弹引爆；
    7. 抽卡 / 升级队列；
    8. 超级怪兽警告 / 1 秒警告推进；
    9. 关卡通关判定 / 无尽循环；
    10. 状态机 flush + 时间推进；
    11. 成就提示推进。

通过 :class:`InputProvider` 抽象键鼠 / 触屏输入，UI 层仅渲染 ``Engine`` 暴露的状态快照。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional

from .core.event_bus import EventBus
from .core.run_context import RunContext, RunMode
from .core.state_machine import (
    State,
    BOOT, MAIN_MENU, MODE_SELECT, PRESET_SELECT, RUNNING, PAUSED,
    SUPER_WARNING, LEVEL_UP, CARD_SELECT, STAGE_CLEAR, ENDING, RESULT, ERROR,
    StateMachine,
)
from .core.time_keeper import TimeKeeper
from .core.rng import make_rng_streams

from .config.contract import ConfigBundle
from .config.content import TEMP_BUFF_EFFECTS, load_default_bundle

from .combat.targeting import TargetCandidate
from .combat.weapons import WeaponSystem, weapon_tick, WeaponPhase
from .combat.projectiles import ProjectileSystem
from .combat.damage import armory_reduction

from .enemies.enemies import Enemy, spawn_enemy, step_enemy, EnemyState
from .enemies.spawn_director import SpawnDirector, Sector, ENEMY_HARD_CAP, SpawnConfig
from .enemies.time_scaling import stage_modifiers, enemy_spawned_snapshot, elite_bonus_score

from .player.player import Player, apply_player_damage, heal_player, effective_stats, player_step, PlayerStatus
from .player.movement import (
    normalize_move, apply_movement, clamp_to_playable_bounds, PlayableBounds,
)
from .player.input_provider import InputAction, InputProvider

from .drops.drops import (
    DROP_HARD_CAP, DropSystem, Pickup, HazardBomb,
    create_drop_system, spawn_drops_on_enemy_defeated,
)
from .cards.cards import CardSystem, create_card_system
from .level.scoring import ScoringSystem
from .level.level_up import LevelSystem, create_level_system, xp_from_kill, xp_to_next
from .achievements.achievements import AchievementSystem, create_achievement_system
from .enemies.super_enemy import SuperEnemyDirector, SuperEnemy, SuperSkill

from .save.save import ProfileSave, load_profile, save_profile

from .log.logging import StructuredLogger, NullLogger, create_logger

LOGIC_DT_MAX = 1 / 30  # 防帧时间过大跳跃


ACTIVE_SKILLS = {
    "bomb_trap": {"name": "四雷", "duration": 0.1, "cooldown": 18.0, "damage": 46.0, "radius": 150.0},
    "roll": {"name": "翻滚", "duration": 0.35, "cooldown": 5.0, "distance": 260.0},
    "axe_orbit": {"name": "斧刃", "duration": 5.0, "cooldown": 20.0, "damage": 18.0, "radius": 170.0},
}


CARD_COMBO_SETS = {
    "might": {
        "name": "大力三连",
        "cards": {"c_atk_plus", "c_heavy_atk", "c_rainbow_core"},
        "bonus": "攻击 +18%，攻速 +6%",
        "effects": {"dmg_pct": 0.18, "aspd_pct": 0.06},
    },
    "rapid": {
        "name": "疾风三连",
        "cards": {"c_speed_plus", "c_move_plus", "c_desperation"},
        "bonus": "攻速 +16%，移速 +6%",
        "effects": {"aspd_pct": 0.16, "move_speed_pct": 0.06},
    },
    "bulwark": {
        "name": "壁垒三连",
        "cards": {"c_hp_plus", "c_armor_plus", "c_compound_armor", "c_regen_shield", "c_invuln_shell"},
        "bonus": "最大生命 +25，护甲 +5",
        "effects": {"max_hp_flat": 25, "armor_flat": 5},
    },
    "reach": {
        "name": "远狩三连",
        "cards": {"c_range_plus", "c_arc_plus", "c_sniper_calibrate", "c_global_sense"},
        "bonus": "射程 +14%，穿透 +1",
        "effects": {"range_pct": 0.14, "penetration": 1},
    },
}

WEAPON_RARITY_RULES = {
    "common": {"name": "普通", "max_level": 6, "color": "#b8c4d6"},
    "rare": {"name": "稀有", "max_level": 7, "color": "#5ec8ff"},
    "epic": {"name": "史诗", "max_level": 8, "color": "#c77dff"},
    "legendary": {"name": "传说", "max_level": 9, "color": "#ffd15c"},
}


WEAPON_RARITY_BY_ID = {
    "w_melee_blade": "common",
    "w_rifle_precise": "common",
    "w_shotgun_spread": "rare",
    "w_orbiter_omni": "rare",
    "w_laser_charge": "epic",
    "w_arcane_orb": "epic",
    "w_great_cleaver": "epic",
    "w_ricochet_ball": "epic",
    "w_laser_cannon": "legendary",
    "w_thunder_daggers": "rare",
    "w_frost_lance": "rare",
    "w_flame_handcannon": "epic",
    "w_starfall_bow": "epic",
    "w_venom_knife": "rare",
    "w_magnetic_ringblade": "epic",
    "w_holy_scepter": "epic",
    "w_blood_scythe": "epic",
    "w_void_pistols": "rare",
    "w_rockfall_hammer": "epic",
    "w_wind_tachi": "rare",
    "w_thunder_array": "legendary",
    "w_railbow": "legendary",
    "w_ember_drone": "epic",
}


WEAPON_SYNERGIES = {
    "steam_burst": {
        "name": "蒸汽爆裂",
        "weapons": {"w_frost_lance", "w_flame_handcannon"},
        "min_level": 3,
        "desc": "命中时 24% 触发范围蒸汽伤害。",
    },
    "thunder_chain": {
        "name": "雷链",
        "weapons": {"w_thunder_daggers", "w_thunder_array"},
        "min_level": 3,
        "desc": "命中时弹跳电击附近敌人。",
    },
    "corrupt_blood": {
        "name": "腐血",
        "weapons": {"w_venom_knife", "w_blood_scythe"},
        "min_level": 3,
        "desc": "敌人死亡时按最大生命治疗玩家。",
    },
    "focused_lattice": {
        "name": "聚焦光网",
        "weapons": {"w_laser_cannon", "w_laser_charge"},
        "min_level": 3,
        "desc": "连续攻击同一目标逐步增伤。",
    },
    "earth_shock": {
        "name": "震地",
        "weapons": {"w_rockfall_hammer", "w_great_cleaver"},
        "min_level": 3,
        "desc": "重型近战概率释放地面冲击波。",
    },
}


ENEMY_AFFIXES = {
    "ice_armor": {"name": "冰甲", "color": "#8ce7ff"},
    "split": {"name": "分裂", "color": "#b98cff"},
    "lifesteal": {"name": "吸血", "color": "#ff5c8a"},
    "reflect": {"name": "反射", "color": "#ffe66d"},
    "volatile": {"name": "爆燃", "color": "#ff7a3d"},
    "swift": {"name": "迅捷", "color": "#7dff9a"},
    "summoner": {"name": "召唤", "color": "#d99bff"},
}


RANDOM_EVENTS = {
    "supply_pod": {"name": "补给舱", "duration": 7.0, "desc": "恢复生命并获得临时护盾。"},
    "black_market": {"name": "黑市商人", "duration": 7.0, "desc": "以生命换取随机高阶武器。"},
    "alien_relic": {"name": "外星遗迹", "duration": 10.0, "desc": "获得一次随机特殊能力。"},
    "unstable_energy": {"name": "失控能源", "duration": 18.0, "desc": "敌人更强，但金币和经验翻倍。"},
    "rescue_beacon": {"name": "救援信标", "duration": 20.0, "desc": "保护目标，完成后获得奖励。"},
    "meteor_rain": {"name": "陨石雨", "duration": 12.0, "desc": "躲避陨石，结束掉落资源。"},
}


CHALLENGE_POOL = [
    {"id": "kill_80_2m", "name": "2分钟内击杀80个敌人", "type": "kills_in_time", "target": 80, "time_limit": 120.0},
    {"id": "no_roll_wave", "name": "不使用翻滚坚持60秒", "type": "no_roll_time", "target": 60.0},
    {"id": "melee_elite", "name": "近战武器击杀1个精英", "type": "melee_elite", "target": 1},
    {"id": "killstreak_30", "name": "保持连杀不低于30", "type": "killstreak", "target": 30},
    {"id": "no_heal_clear", "name": "本关不拾取生命恢复", "type": "no_heal_stage", "target": 1},
    {"id": "four_thunder_10", "name": "四雷一次击杀10个敌人", "type": "bomb_multikill", "target": 10},
]


EQUIPMENT_ITEMS = {
    "eq_coin_magnet": {
        "name": "金币磁环",
        "desc": "金币收益 +18%，拾取范围 +20%",
        "effects": {"gold_bonus": 0.18, "pickup_radius_pct": 0.20},
    },
    "eq_vital_core": {
        "name": "生命核心",
        "desc": "最大生命 +35",
        "effects": {"max_hp_flat": 35},
    },
    "eq_overclock": {
        "name": "超频齿轮",
        "desc": "全部武器攻速 +10%",
        "effects": {"aspd_pct": 0.10},
    },
    "eq_luck_lens": {
        "name": "幸运透镜",
        "desc": "暴击率 +5%，金币收益 +8%",
        "effects": {"crit_chance": 0.05, "gold_bonus": 0.08},
    },
    "eq_guard_plate": {
        "name": "守卫甲片",
        "desc": "护甲 +5，护盾上限 +35",
        "effects": {"armor_flat": 5, "shield_flat": 35},
    },
    "eq_second_wind": {
        "name": "回声心脏",
        "desc": "复活生命提高到 65%",
        "effects": {"revive_hp_ratio": 0.65},
    },
    "eq_xp_charm": {
        "name": "学徒徽章",
        "desc": "经验获取 +18%",
        "effects": {"xp_gain_pct": 0.18},
    },
}


SHOP_ITEMS = {
    "weapon:w_shotgun_spread": {"name": "永久武器：散射霰弹", "cost": 120, "weapon_id": "w_shotgun_spread"},
    "weapon:w_orbiter_omni": {"name": "永久武器：环绕哨兵", "cost": 150, "weapon_id": "w_orbiter_omni"},
    "weapon:w_laser_charge": {"name": "永久武器：光束矩阵", "cost": 190, "weapon_id": "w_laser_charge"},
    "weapon:w_arcane_orb": {"name": "永久武器：奥术回响", "cost": 190, "weapon_id": "w_arcane_orb"},
    "weapon:w_great_cleaver": {"name": "永久武器：裂地大砍刀", "cost": 220, "weapon_id": "w_great_cleaver"},
    "weapon:w_ricochet_ball": {"name": "永久武器：棱镜弹球", "cost": 240, "weapon_id": "w_ricochet_ball"},
    "weapon:w_laser_cannon": {"name": "永久武器：激光炮", "cost": 260, "weapon_id": "w_laser_cannon"},
    "weapon:w_thunder_daggers": {"name": "永久武器：雷鸣短刃", "cost": 135, "weapon_id": "w_thunder_daggers"},
    "weapon:w_frost_lance": {"name": "永久武器：冰脊长枪", "cost": 165, "weapon_id": "w_frost_lance"},
    "weapon:w_flame_handcannon": {"name": "永久武器：赤焰手炮", "cost": 210, "weapon_id": "w_flame_handcannon"},
    "weapon:w_starfall_bow": {"name": "永久武器：星坠弓", "cost": 205, "weapon_id": "w_starfall_bow"},
    "weapon:w_venom_knife": {"name": "永久武器：毒雾匕首", "cost": 150, "weapon_id": "w_venom_knife"},
    "weapon:w_magnetic_ringblade": {"name": "永久武器：磁暴环刃", "cost": 230, "weapon_id": "w_magnetic_ringblade"},
    "weapon:w_holy_scepter": {"name": "永久武器：圣辉权杖", "cost": 215, "weapon_id": "w_holy_scepter"},
    "weapon:w_blood_scythe": {"name": "永久武器：血契镰刀", "cost": 225, "weapon_id": "w_blood_scythe"},
    "weapon:w_void_pistols": {"name": "永久武器：虚空双枪", "cost": 195, "weapon_id": "w_void_pistols"},
    "weapon:w_rockfall_hammer": {"name": "永久武器：岩崩战锤", "cost": 245, "weapon_id": "w_rockfall_hammer"},
    "weapon:w_wind_tachi": {"name": "永久武器：风切太刀", "cost": 205, "weapon_id": "w_wind_tachi"},
    "weapon:w_thunder_array": {"name": "永久武器：四雷阵盘", "cost": 255, "weapon_id": "w_thunder_array"},
    "weapon:w_railbow": {"name": "永久武器：磁轨长弓", "cost": 285, "weapon_id": "w_railbow"},
    "weapon:w_ember_drone": {"name": "永久武器：熔核无人机", "cost": 275, "weapon_id": "w_ember_drone"},
    "equipment:eq_coin_magnet": {"name": "装备：金币磁环", "cost": 120, "equipment_id": "eq_coin_magnet"},
    "equipment:eq_vital_core": {"name": "装备：生命核心", "cost": 140, "equipment_id": "eq_vital_core"},
    "equipment:eq_overclock": {"name": "装备：超频齿轮", "cost": 160, "equipment_id": "eq_overclock"},
    "equipment:eq_luck_lens": {"name": "装备：幸运透镜", "cost": 170, "equipment_id": "eq_luck_lens"},
    "equipment:eq_guard_plate": {"name": "装备：守卫甲片", "cost": 180, "equipment_id": "eq_guard_plate"},
    "equipment:eq_second_wind": {"name": "装备：回声心脏", "cost": 210, "equipment_id": "eq_second_wind"},
    "equipment:eq_xp_charm": {"name": "装备：学徒徽章", "cost": 130, "equipment_id": "eq_xp_charm"},
    "upgrade:atk": {"name": "永久强化：攻击核心", "cost": 180, "upgrade": "atk", "max_level": 5},
    "upgrade:hp": {"name": "永久强化：生命核心", "cost": 160, "upgrade": "hp", "max_level": 5},
    "upgrade:gold": {"name": "永久强化：金币磁芯", "cost": 140, "upgrade": "gold", "max_level": 3},
}


DEFAULT_ACCOUNT_WEAPONS = ["w_rifle_precise", "w_melee_blade"]
DEFAULT_ACCOUNT_EQUIPMENT = ["eq_coin_magnet", "eq_xp_charm"]
MAX_CAMPAIGN_STAGE = 5
STAGE_CLEAR_THRESHOLDS = {1: 1200, 2: 2600, 3: 4800, 4: 6800, 5: 9000}
STAGE_BOSS_THRESHOLDS = {1: 900, 2: 2000, 3: 3600, 4: 5200, 5: 7200}


@dataclass
class EngineDebug:
    fps: float = 0
    logic_dt_avg: float = 0
    enemies: int = 0
    projectiles: int = 0
    pickups: int = 0
    bombs: int = 0
    drawn_stress: int = 0


class Engine:
    """单局驱动器。"""

    def __init__(
        self,
        bundle: ConfigBundle | None = None,
        *,
        platform: str = "win",
        input_provider: InputProvider | None = None,
        save_path: str | None = None,
        log_path: str | None = None,
        seed: int | None = None,
        enable_disk_log: bool = False,
        max_event_log: int = 4096,
        mode: str = RunMode.CAMPAIGN,
        preset_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.bundle = bundle or load_default_bundle()
        # ---- 基础 ----
        self.run_id = run_id or f"run-{int(time.time()*1000) % 1_000_000:06d}"
        self.seed = seed if seed is not None else int(time.time()) & 0xFFFFFFFF
        self.context = RunContext(
            run_id=self.run_id,
            run_seed=self.seed,
            mode=mode,
            preset_id=preset_id or "preset_balanced",
            config_version=self.bundle.config_version,
            app_version="0.1.0",
            platform=platform,
        )
        self.event_bus = self.context.bus
        self.timer = self.context.timer
        self.state_machine = self.context.state_machine
        self.rng = self.context.rng

        # ---- 子系统 ----
        self.player = Player(
            entity_id="player",
            position=(960.0, 540.0),
        )
        # 渲染层使用的外观选择，不参与战斗数值与存档进度。
        self.player_skin_id = "vanguard"
        # 玩家 / 武器栈
        self.weapon_sys = WeaponSystem()
        preset = self.bundle.presets[self.context.preset_id]
        attrs = preset["attributes"]
        self.player.base_max_hp = attrs["max_hp"]
        self.player.base_move_speed = attrs["move_speed"]
        self.player.base_armor = attrs.get("armor", 0)
        self.player.base_pickup_radius = attrs.get("pickup_radius", 90)
        self.player.current_hp = self.player.base_max_hp
        self.player.current_shield = attrs.get("current_shield", 0)
        self.player.max_shield = attrs.get("max_shield", 0)
        self.player.current_armor = self.player.base_armor
        weapon_cfgs = [self.bundle.weapons[wid] for wid in preset["weapon_stack"]]
        self.weapon_sys.populate(weapon_cfgs, active_weapon_id=preset.get("active_weapon"))

        self.drop_sys = create_drop_system(self.event_bus)

        self.projectile_sys = ProjectileSystem(bus=self.event_bus)
        self.scoring_sys = ScoringSystem(self.event_bus)
        self.level_sys = create_level_system(self.event_bus)
        self.card_sys = create_card_system(self.event_bus, self.bundle.cards)
        self.ach_sys = create_achievement_system(self.event_bus, self.bundle.achievements)

        # S2 修复：订阅 damage_applied，把玩家攻击的 overflow 累加到 card_sys.attack_overflow
        # 下次攻击时通过 _emit 把累计溢出加成到基础伤害上（CB-007/CBT-007）
        self.event_bus.subscribe("damage_applied", self._on_damage_applied_for_overflow)

        self.spawn_director = SpawnDirector(
            bounds=(48, 48, 1920 - 48, 1080 - 48),
        )
        self.spawn_director.enemies = []

        self.super_director = SuperEnemyDirector()
        # 战斗中表现、伤害 50% 上限用的"参考怪兽有效生命"
        self.reference_monster_def = self.bundle.enemies["spinner_chaser"]
        self._last_run_progress_min = 0

        # ---- 玩家被动成长 ----
        self.player_passive_triggered = {1: False, 2: False, 3: False}

        # ---- 输入 ----
        self.input_provider = input_provider

        # ---- 日志 ----
        self.logger = create_logger(
            run_id=self.run_id,
            run_seed=self.seed,
            app_version="0.1.0",
            config_version=self.bundle.config_version,
            platform=platform,
            maxlen=max_event_log,
            path=log_path,
            enable_disk=enable_disk_log,
        )
        self.state_machine.on_enter(lambda s: self.logger.set_state(s.name))
        self.state_machine.on_enter(lambda s: self.bus_publish_state_change(s))
        self.state_machine.force(MAIN_MENU)
        self.logger.set_state("MAIN_MENU")

        # ---- 持续状态 ----
        self.debug = EngineDebug()
        self._fence_dt = 0.0
        self._frame_count = 0
        self.bounds = PlayableBounds(48, 48, 1920 - 48, 1080 - 48)
        self.unlocked_achievements_snapshot: set[str] = set()
        self._card_offer_now: Optional[object] = None
        self._level_offer_now: Optional[list] = None
        self._ending_left = 0.0
        self._ending_result = "defeat"
        # 渲染层读取的攻击表现快照；不参与伤害计算。
        self.last_player_attack_time = -99.0
        self.last_player_attack_angle = 0.0
        self.last_player_attack_range = 0.0
        self.last_player_attack_arc = 0.0
        self.last_player_attack_is_melee = False
        self.last_player_attack_weapon = ""
        self.last_weapon_switch_time = -99.0
        self.stage_lockdown = False
        self.stage_boss_defeated = False
        self.stage_boss_queued = False
        self.stage_featured_enemy_spawned = False
        self.active_skill_id = "bomb_trap"
        self.active_skill_cd_left = 0.0
        self.active_skill_left = 0.0
        self.active_skill_tick_left = 0.0
        self.active_skill_uses = 0
        self.temp_buff_until: dict[str, float] = {}
        self.roll_start_pos: tuple[float, float] | None = None
        self.roll_target_pos: tuple[float, float] | None = None
        self.roll_duration = 0.0
        self.roll_left = 0.0
        self.last_roll_finished_at = -99.0
        self.last_roll_finished_pos: tuple[float, float] | None = None
        self.run_revives_left = 1
        self.run_gold_earned = 0
        self.card_combo_counts = {key: 0 for key in CARD_COMBO_SETS}
        self.card_combo_unlocked: set[str] = set()
        self.last_combo_notice: dict | None = None
        self.weapon_synergies_active: set[str] = set()
        self.weapon_synergy_state: dict[str, dict] = {}
        self.last_weapon_synergy_notice: dict | None = None
        self.last_damage_numbers: list[dict] = []
        self.active_random_event: dict | None = None
        self.next_random_event_at = 24.0
        self.random_event_history: list[dict] = []
        self.stage_environment_events_seen: set[int] = set()
        self.run_challenges: list[dict] = []
        self.last_challenge_notice: dict | None = None
        self.kill_streak = 0
        self.last_kill_time = 0.0
        self.last_killstreak_notice: dict | None = None
        self._stage_heal_pickups = 0
        self.selected_starting_weapon_id: str | None = None
        self.selected_starting_weapon_ids: list[str] = list(DEFAULT_ACCOUNT_WEAPONS)
        self.selected_equipment_ids: list[str] = list(DEFAULT_ACCOUNT_EQUIPMENT)
        self._run_recorded = False
        self.last_hazard_dodge_check: dict[str, bool] = {}
        # 上一帧玩家被记录进炸弹危险圈的状态
        self._in_bomb_zone: dict[str, bool] = {}
        self.bomb_player_within_armed: dict[str, bool] = {}

        # ---- 持久化 ----
        self.profile_path = save_path
        self.profile: ProfileSave = load_profile(self.profile_path) if self.profile_path else ProfileSave(
            profile_id="default",
            created_at=time.time(),
            updated_at=time.time(),
            app_version="0.1.0",
            config_version=self.bundle.config_version,
        )
        self._load_profile_into_systems()

    # ========================================================================
    # 公共查询：HUD / UI 只需读取这些快照
    # ========================================================================

    def state(self) -> str:
        return self.state_machine.current.name

    def current_weapon_label(self) -> str:
        w = self.weapon_sys.active
        if w is None:
            return "—"
        return w.config.get("display_name", w.weapon_id)

    def weapon_stack_labels(self) -> list[str]:
        return [w.config.get("display_name", w.weapon_id) for w in self.weapon_sys.stack]

    def active_weapon_index(self) -> int:
        return self.weapon_sys.active_index

    def kills_in_run(self) -> int:
        return self.context.kills_run

    def _load_profile_into_systems(self) -> None:
        self.ach_sys.unlocked = dict(getattr(self.profile, "unlocked_achievements", {}) or {})
        self.ach_sys.stats_lifetime["lifetime_score"] = float(getattr(self.profile, "lifetime_score", 0) or 0)
        self.ach_sys.stats_lifetime["lifetime_kills"] = float(getattr(self.profile, "lifetime_kills", 0) or 0)
        self.ach_sys.stats_lifetime["super_kills_lifetime"] = float(getattr(self.profile, "super_kills", 0) or 0)
        self.ach_sys.stats_lifetime["bomb_dodges_lifetime"] = float(getattr(self.profile, "bomb_dodges", 0) or 0)
        if getattr(self.profile, "campaign_cleared", False):
            self.ach_sys.stats_lifetime["campaign_cleared"] = 1.0
        self.selected_starting_weapon_id = getattr(self.profile, "selected_permanent_weapon", None)
        self.selected_starting_weapon_ids = self._valid_starting_weapons(getattr(self.profile, "selected_starting_weapons", []) or [])
        self.selected_equipment_ids = self._valid_equipment(getattr(self.profile, "selected_equipment", []) or [])

    def _account_weapon_pool(self) -> list[str]:
        return list(dict.fromkeys(DEFAULT_ACCOUNT_WEAPONS + self.unlocked_weapon_ids()))

    def _valid_starting_weapons(self, weapon_ids: list[str]) -> list[str]:
        pool = [wid for wid in self._account_weapon_pool() if wid in self.bundle.weapons]
        chosen = [wid for wid in weapon_ids if wid in pool]
        for wid in pool:
            if len(chosen) >= 2:
                break
            if wid not in chosen:
                chosen.append(wid)
        return chosen[:2]

    def _account_equipment_pool(self) -> list[str]:
        return list(dict.fromkeys(DEFAULT_ACCOUNT_EQUIPMENT + self.unlocked_equipment_ids()))

    def _valid_equipment(self, equipment_ids: list[str]) -> list[str]:
        pool = [eid for eid in self._account_equipment_pool() if eid in EQUIPMENT_ITEMS]
        chosen = [eid for eid in equipment_ids if eid in pool]
        for eid in pool:
            if len(chosen) >= 2:
                break
            if eid not in chosen:
                chosen.append(eid)
        return chosen[:2]

    def switch_account(self, account_name: str, save_path: str | None = None) -> None:
        """Switch to another passwordless local profile."""
        from .save.save import normalize_account_id
        self._persist_profile()
        self.profile_path = save_path or self.profile_path
        if self.profile_path:
            self.profile = load_profile(self.profile_path, default_profile_id=account_name)
        else:
            account_id = normalize_account_id(account_name)
            self.profile = ProfileSave(
                profile_id=account_id,
                account_name=account_name or account_id,
                created_at=time.time(),
                updated_at=time.time(),
                app_version="0.1.0",
                config_version=self.bundle.config_version,
            )
        self._load_profile_into_systems()

    def gold(self) -> int:
        return int(getattr(self.profile, "gold", 0) or 0)

    def unlocked_weapon_ids(self) -> list[str]:
        return list(dict.fromkeys(getattr(self.profile, "unlocked_weapons", []) or []))

    def account_weapon_pool(self) -> list[str]:
        return self._account_weapon_pool()

    def unlocked_equipment_ids(self) -> list[str]:
        return list(dict.fromkeys(getattr(self.profile, "unlocked_equipment", []) or []))

    def account_equipment_pool(self) -> list[str]:
        return self._account_equipment_pool()

    def permanent_upgrade_level(self, upgrade_id: str) -> int:
        return int((getattr(self.profile, "permanent_upgrades", {}) or {}).get(upgrade_id, 0) or 0)

    def purchase_shop_item(self, item_id: str) -> bool:
        item = SHOP_ITEMS.get(item_id)
        if not item:
            return False
        if "weapon_id" in item and item["weapon_id"] in self.unlocked_weapon_ids():
            return False
        if "equipment_id" in item and item["equipment_id"] in self._account_equipment_pool():
            return False
        if "upgrade" in item and self.permanent_upgrade_level(item["upgrade"]) >= int(item.get("max_level", 1)):
            return False
        cost = int(item["cost"])
        if self.gold() < cost:
            return False
        self.profile.gold = self.gold() - cost
        if "weapon_id" in item:
            weapons = self.unlocked_weapon_ids()
            weapons.append(item["weapon_id"])
            self.profile.unlocked_weapons = list(dict.fromkeys(weapons))
            self.select_starting_weapon(item["weapon_id"], slot=1)
        elif "equipment_id" in item:
            equipment = self.unlocked_equipment_ids()
            equipment.append(item["equipment_id"])
            self.profile.unlocked_equipment = list(dict.fromkeys(equipment))
            self.select_equipment(item["equipment_id"], slot=0 if len(self.selected_equipment_ids) < 2 else 1)
        else:
            upgrades = dict(getattr(self.profile, "permanent_upgrades", {}) or {})
            uid = item["upgrade"]
            upgrades[uid] = min(int(item.get("max_level", 1)), int(upgrades.get(uid, 0) or 0) + 1)
            self.profile.permanent_upgrades = upgrades
        self._persist_profile()
        return True

    def select_permanent_weapon(self, weapon_id: str | None) -> bool:
        return self.select_starting_weapon(weapon_id, slot=1)

    def select_starting_weapon(self, weapon_id: str | None, *, slot: int) -> bool:
        if slot not in (0, 1):
            return False
        if weapon_id is not None and weapon_id not in self._account_weapon_pool():
            return False
        selected = self._valid_starting_weapons(getattr(self, "selected_starting_weapon_ids", []))
        if weapon_id is None:
            return False
        other = 1 - slot
        if selected[other] == weapon_id:
            selected[other] = selected[slot]
        selected[slot] = weapon_id
        self.selected_starting_weapon_ids = self._valid_starting_weapons(selected)
        self.selected_starting_weapon_id = self.selected_starting_weapon_ids[-1] if self.selected_starting_weapon_ids else None
        self.profile.selected_starting_weapons = list(self.selected_starting_weapon_ids)
        self.profile.selected_permanent_weapon = self.selected_starting_weapon_id
        self._persist_profile()
        return True

    def select_equipment(self, equipment_id: str | None, *, slot: int) -> bool:
        if slot not in (0, 1):
            return False
        if equipment_id is not None and equipment_id not in self._account_equipment_pool():
            return False
        selected = self._valid_equipment(getattr(self, "selected_equipment_ids", []))
        if equipment_id is None:
            return False
        other = 1 - slot
        if len(selected) < 2:
            selected = self._valid_equipment(selected)
        if selected[other] == equipment_id:
            selected[other] = selected[slot]
        selected[slot] = equipment_id
        self.selected_equipment_ids = self._valid_equipment(selected)
        self.profile.selected_equipment = list(self.selected_equipment_ids)
        self._persist_profile()
        return True

    def selected_equipment_effects(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for eid in self.selected_equipment_ids:
            for key, value in EQUIPMENT_ITEMS.get(eid, {}).get("effects", {}).items():
                totals[key] = totals.get(key, 0.0) + float(value)
        return totals

    def _apply_weapon_metadata(self) -> None:
        for weapon in self.weapon_sys.stack:
            rarity = WEAPON_RARITY_BY_ID.get(weapon.weapon_id, weapon.config.get("rarity", "common"))
            rule = WEAPON_RARITY_RULES.get(rarity, WEAPON_RARITY_RULES["common"])
            weapon.rarity = rarity
            weapon.max_level = int(rule["max_level"])
            weapon.config.setdefault("rarity", rarity)
            weapon.config.setdefault("max_level", weapon.max_level)
            weapon.breakthrough_unlocked = weapon.level >= weapon.max_level
        self._refresh_weapon_synergies()

    def weapon_synergy_status(self) -> list[dict]:
        ids = {w.weapon_id: w for w in self.weapon_sys.stack}
        rows = []
        for combo_id, cfg in WEAPON_SYNERGIES.items():
            missing = [wid for wid in cfg["weapons"] if wid not in ids]
            low = [wid for wid in cfg["weapons"] if wid in ids and ids[wid].level < int(cfg.get("min_level", 3))]
            rows.append({
                "id": combo_id,
                "name": cfg["name"],
                "desc": cfg["desc"],
                "active": combo_id in self.weapon_synergies_active,
                "missing": missing,
                "low_level": low,
                "min_level": int(cfg.get("min_level", 3)),
            })
        return rows

    def _refresh_weapon_synergies(self) -> None:
        ids = {w.weapon_id: w for w in self.weapon_sys.stack}
        for combo_id, cfg in WEAPON_SYNERGIES.items():
            active = all(wid in ids and ids[wid].level >= int(cfg.get("min_level", 3)) for wid in cfg["weapons"])
            if active and combo_id not in self.weapon_synergies_active:
                self.weapon_synergies_active.add(combo_id)
                notice = {"combo_id": combo_id, "name": cfg["name"], "desc": cfg["desc"], "time": self.timer.run_time}
                self.last_weapon_synergy_notice = notice
                self.event_bus.publish(self._e("weapon_synergy_activated", notice))
            elif not active and combo_id in self.weapon_synergies_active:
                self.weapon_synergies_active.remove(combo_id)

    def _generate_run_challenges(self) -> list[dict]:
        rng = self.context.rng.get("card_rng")
        pool = list(CHALLENGE_POOL)
        rng.shuffle(pool)
        count = 1 + rng.range(3)
        now = self.timer.run_time
        return [
            {
                **pool[i],
                "progress": 0,
                "completed": False,
                "failed": False,
                "started_at": now,
                "deadline": now + float(pool[i].get("time_limit", 999999)),
            }
            for i in range(min(count, len(pool)))
        ]

    def _complete_challenge(self, ch: dict) -> None:
        if ch.get("completed") or ch.get("failed"):
            return
        ch["completed"] = True
        self._grant_gold(18 + 8 * self.context.stage_index, source=f"challenge:{ch['id']}")
        self.context.pending_cards += 1 if ch["type"] in ("killstreak", "melee_elite", "bomb_multikill") else 0
        self.last_challenge_notice = {"id": ch["id"], "name": ch["name"], "time": self.timer.run_time}
        self.event_bus.publish(self._e("challenge_completed", self.last_challenge_notice))

    def _step_challenges(self, dt: float) -> None:
        for ch in self.run_challenges:
            if ch.get("completed") or ch.get("failed"):
                continue
            if self.timer.run_time > ch.get("deadline", 999999) and ch["type"] in ("kills_in_time", "no_roll_time"):
                if ch["type"] == "no_roll_time" and ch.get("progress", 0) >= ch.get("target", 0):
                    self._complete_challenge(ch)
                else:
                    ch["failed"] = True
                    self.event_bus.publish(self._e("challenge_failed", {"id": ch["id"], "name": ch["name"]}))
            elif ch["type"] == "no_roll_time":
                ch["progress"] = float(ch.get("progress", 0.0)) + dt
                if ch["progress"] >= ch["target"]:
                    self._complete_challenge(ch)

    def _active_event_multiplier(self, key: str) -> float:
        ev = self.active_random_event
        if ev and ev.get("id") == "unstable_energy":
            return 2.0 if key in ("gold", "xp") else 1.35
        return 1.0

    def _step_random_events(self, dt: float) -> None:
        ev = self.active_random_event
        if ev is not None:
            ev["left"] = max(0.0, float(ev.get("left", 0)) - dt)
            if ev["id"] == "meteor_rain":
                ev["tick"] = float(ev.get("tick", 0.0)) - dt
                if ev["tick"] <= 0:
                    ev["tick"] = 1.35
                    self._spawn_event_meteor()
            elif ev.get("hazard_pattern"):
                ev["tick"] = float(ev.get("tick", 0.0)) - dt
                if ev["tick"] <= 0 and int(ev.get("spawned", 0)) < int(ev.get("spawn_count", 0)):
                    self._spawn_stage_environment_hazard(ev)
                    ev["spawned"] = int(ev.get("spawned", 0)) + 1
                    ev["tick"] = float(ev.get("spawn_interval", 1.0))
            if ev["id"] == "rescue_beacon":
                d = math.hypot(self.player.position[0] - ev["position"][0], self.player.position[1] - ev["position"][1])
                if d < 250:
                    ev["protected"] = float(ev.get("protected", 0.0)) + dt
            if ev["left"] <= 0:
                self._finish_random_event(ev)
                self.active_random_event = None
                delay = (
                    10.0 if self._has_pending_stage_environment_event()
                    else 32.0 + self.context.rng.get("drop_rng").range(20)
                )
                self.next_random_event_at = self.timer.run_time + delay
            return
        if self.timer.run_time >= self.next_random_event_at:
            self._start_random_event()

    def _has_pending_stage_environment_event(self) -> bool:
        stage_index = int(self.context.stage_index)
        stage = self.bundle.stages.get(f"stage_{stage_index}", {})
        return bool(stage.get("environment_event")) and stage_index not in self.stage_environment_events_seen

    def _start_random_event(self) -> None:
        rng = self.context.rng.get("drop_rng")
        unique_stage_event = self._has_pending_stage_environment_event()
        if unique_stage_event:
            stage = self.bundle.stages[f"stage_{self.context.stage_index}"]
            cfg = stage["environment_event"]
            event_id = cfg["id"]
            self.stage_environment_events_seen.add(int(self.context.stage_index))
        else:
            event_id = list(RANDOM_EVENTS.keys())[rng.range(len(RANDOM_EVENTS))]
            cfg = RANDOM_EVENTS[event_id]
        pos = (
            max(self.bounds.min_x + 80, min(self.bounds.max_x - 80, self.player.position[0] + rng.uniform(-420, 420))),
            max(self.bounds.min_y + 80, min(self.bounds.max_y - 80, self.player.position[1] + rng.uniform(-300, 300))),
        )
        ev = {
            "id": event_id,
            "icon_id": cfg.get("icon_id", event_id),
            "name": cfg["name"],
            "desc": cfg["desc"],
            "left": float(cfg["duration"]),
            "duration": float(cfg["duration"]),
            "position": pos,
            "tick": 0.5,
            "started_at": self.timer.run_time,
            "unique_stage_event": unique_stage_event,
            "hazard_pattern": cfg.get("hazard_pattern"),
            "hazard_icon": cfg.get("hazard_icon", "bomb"),
            "hazard_radius": float(cfg.get("hazard_radius", 0.0)),
            "hazard_damage": float(cfg.get("hazard_damage", 0.0)),
            "hazard_arm_delay": float(cfg.get("hazard_arm_delay", 0.35)),
            "spawn_count": int(cfg.get("spawn_count", 0)),
            "spawn_interval": float(cfg.get("spawn_interval", 1.35)),
            "spawned": 0,
        }
        self.active_random_event = ev
        self.random_event_history.append({"id": event_id, "name": cfg["name"], "time": self.timer.run_time})
        if event_id == "supply_pod":
            eff = effective_stats(self.player)
            heal_player(self.player, amount=eff["max_hp"] * 0.22)
            self.player.current_shield = min(self.player.max_shield + self.player.growth.max_shield_extra + 35, self.player.current_shield + 35)
        elif event_id == "black_market":
            eff = effective_stats(self.player)
            self.player.current_hp = max(1.0, self.player.current_hp - eff["max_hp"] * 0.18)
            self._grant_random_high_tier_weapon(source="black_market")
        elif event_id == "alien_relic":
            self._apply_random_relic_bonus()
        self.event_bus.publish(self._e("random_event_started", {
            "id": event_id,
            "icon_id": ev["icon_id"],
            "name": cfg["name"],
            "desc": cfg["desc"],
            "position": list(pos),
            "duration": cfg["duration"],
        }))

    def _finish_random_event(self, ev: dict) -> None:
        success = True
        if ev["id"] == "rescue_beacon":
            success = float(ev.get("protected", 0.0)) >= ev["duration"] * 0.55
        if success:
            if ev["id"] in ("rescue_beacon", "meteor_rain") or ev.get("unique_stage_event"):
                self._grant_gold(24 + 10 * self.context.stage_index, source=f"event:{ev['id']}")
                self.context.pending_cards += 1
            self.event_bus.publish(self._e("random_event_completed", {"id": ev["id"], "name": ev["name"]}))
        else:
            self.event_bus.publish(self._e("random_event_failed", {"id": ev["id"], "name": ev["name"]}))

    def _spawn_event_meteor(self) -> None:
        rng = self.context.rng.get("drop_rng")
        pos = (
            max(self.bounds.min_x + 40, min(self.bounds.max_x - 40, self.player.position[0] + rng.uniform(-360, 360))),
            max(self.bounds.min_y + 40, min(self.bounds.max_y - 40, self.player.position[1] + rng.uniform(-260, 260))),
        )
        b = HazardBomb(
            entity_id=f"meteor_{int(self.timer.run_time * 1000)}_{rng.range(999)}",
            position=pos,
            radius=105.0,
            base_damage=22.0 + 3 * self.context.stage_index,
            spawn_time=self.timer.run_time,
            arm_delay=0.25,
            armed_at=self.timer.run_time + 0.25,
            lifetime=1.65,
            icon="meteor",
        )
        self.drop_sys.bombs.append(b)

    def _spawn_stage_environment_hazard(self, event: dict) -> None:
        if len(self.drop_sys.pickups) + len(self.drop_sys.bombs) >= DROP_HARD_CAP:
            return
        radius = max(1.0, float(event.get("hazard_radius", 90.0)))
        px, py = self.player.position
        wave = int(event.get("spawned", 0))
        pattern = event.get("hazard_pattern")
        if pattern == "mine_pulse":
            angle = wave * 2.399963229728653 + self.context.rng.get("drop_rng").uniform(-0.2, 0.2)
            distance = 45.0 + (wave % 2) * 24.0
            px += math.cos(angle) * distance
            py += math.sin(angle) * distance
        elif pattern == "rail_lock":
            lead = min(145.0, max(80.0, self.player.base_move_speed * 0.55))
            px += math.cos(self.player.facing) * lead
            py += math.sin(self.player.facing) * lead
        else:
            return
        margin = radius + 16.0
        position = (
            max(self.bounds.min_x + margin, min(self.bounds.max_x - margin, px)),
            max(self.bounds.min_y + margin, min(self.bounds.max_y - margin, py)),
        )
        now = self.timer.run_time
        arm_delay = float(event.get("hazard_arm_delay", 0.45))
        rng = self.context.rng.get("drop_rng")
        bomb = HazardBomb(
            entity_id=f"stage_{event['id']}_{int(now * 1000)}_{rng.range(999)}",
            position=position,
            radius=radius,
            base_damage=float(event.get("hazard_damage", 20.0)),
            spawn_time=now,
            arm_delay=arm_delay,
            armed_at=now + arm_delay,
            lifetime=2.5,
            icon=str(event.get("hazard_icon", "bomb")),
        )
        self.drop_sys.bombs.append(bomb)
        self.event_bus.publish(self._e("environment_hazard_spawned", {
            "event_id": event["id"], "position": list(position), "radius": radius,
        }))

    def _grant_random_high_tier_weapon(self, *, source: str) -> None:
        cur = {w.weapon_id for w in self.weapon_sys.stack}
        cands = [
            wid for wid, rarity in WEAPON_RARITY_BY_ID.items()
            if rarity in ("epic", "legendary") and wid in self.bundle.weapons and wid not in cur
        ] or [wid for wid in self.bundle.weapons if wid not in cur]
        if not cands:
            return
        rng = self.context.rng.get("weapon_pick_rng")
        wid = cands[rng.range(len(cands))]
        new_weapon, _, _ = self.weapon_sys.gain_weapon(self.bundle.weapons[wid])
        self._inherit_global_weapon_growth(new_weapon)
        self._apply_weapon_metadata()
        self.event_bus.publish(self._e("weapon_added", {"weapon_id": wid, "source": source}))

    def _apply_random_relic_bonus(self) -> None:
        rng = self.context.rng.get("drop_rng")
        pick = rng.range(3)
        if pick == 0:
            self.player.growth.dmg_pct_bonus += 0.10
            for w in self.weapon_sys.stack:
                w.dmg_pct_bonus += 0.10
        elif pick == 1:
            self.player.growth.move_speed_pct += 0.08
            self.player.base_pickup_radius *= 1.08
        else:
            self.player.growth.shield_regen_rate = max(self.player.growth.shield_regen_rate, 4.0)

    def _apply_enemy_affixes(self, e: Enemy) -> None:
        if e.is_super or "no_score" in (e.tags or []):
            return
        rng = self.context.rng.get("enemy_spawn_rng")
        chance = min(0.33, 0.05 + 0.035 * self.context.stage_index + (0.05 if e.is_elite else 0.0))
        if not rng.chance(chance):
            return
        keys = list(ENEMY_AFFIXES.keys())
        affix = keys[rng.range(len(keys))]
        e.elite_affixes = tuple(dict.fromkeys((*e.elite_affixes, affix)))
        if affix == "ice_armor":
            e.armor += 8
            e.max_hp *= 1.12
            e.current_hp = e.max_hp
        elif affix == "swift":
            e.move_speed *= 1.45
        elif affix == "lifesteal":
            e.contact_damage *= 1.12
        elif affix == "reflect":
            e.armor += 4
        elif affix == "summoner":
            e.tags = tuple(dict.fromkeys((*e.tags, "summoner")))
            e.bomb_spawn_cooldown = 4.0
        elif affix == "volatile":
            e.base_kill_score += 4
        elif affix == "split":
            e.max_hp *= 1.18
            e.current_hp = e.max_hp

    def _step_enemy_affixes(self, dt: float) -> None:
        for e in list(self.spawn_director.enemies):
            if e.state in (EnemyState.DYING, EnemyState.DEAD) or e.current_hp <= 0:
                continue
            if "lifesteal" in e.elite_affixes:
                d = math.hypot(e.position[0] - self.player.position[0], e.position[1] - self.player.position[1])
                if d < 170:
                    e.current_hp = min(e.max_hp, e.current_hp + e.max_hp * 0.010 * dt)
            if "summoner" in e.elite_affixes:
                e.bomb_spawn_cooldown = max(0.0, e.bomb_spawn_cooldown - dt)
                if e.bomb_spawn_cooldown <= 0:
                    e.bomb_spawn_cooldown = 6.5
                    self._spawn_affix_minion(e)

    def _spawn_affix_minion(self, parent: Enemy) -> None:
        if len(self.spawn_director.enemies) >= ENEMY_HARD_CAP:
            return
        cfg = self.bundle.enemies.get("spinner_chaser")
        if cfg is None:
            return
        rng = self.context.rng.get("enemy_spawn_rng")
        angle = rng.uniform(0, math.tau)
        pos = clamp_to_playable_bounds(
            (parent.position[0] + math.cos(angle) * 55, parent.position[1] + math.sin(angle) * 55),
            self.bounds,
            radius=16,
        )
        child = spawn_enemy(config=cfg, position=pos, rng=rng, time_form=parent.time_form, now=self.timer.run_time)
        child.max_hp *= 0.45
        child.current_hp = child.max_hp
        child.base_kill_score = max(1, child.base_kill_score // 2)
        child.tags = tuple(dict.fromkeys((*child.tags, "no_score")))
        self.spawn_director.enemies.append(child)
        self.event_bus.publish(self._e("affix_minion_spawned", {"parent_id": parent.entity_id, "enemy_id": child.entity_id}))

    def _grant_gold(self, amount: int, *, source: str) -> None:
        if amount <= 0:
            return
        bonus = 1.0 + 0.12 * self.permanent_upgrade_level("gold") + self.selected_equipment_effects().get("gold_bonus", 0.0)
        bonus *= self._active_event_multiplier("gold")
        gained = max(1, int(round(amount * bonus)))
        self.profile.gold = self.gold() + gained
        self.profile.total_gold_earned = int(getattr(self.profile, "total_gold_earned", 0) or 0) + gained
        self.run_gold_earned += gained
        self.event_bus.publish(self._e("gold_gained", {"amount": gained, "source": source}))

    # ========================================================================
    # 主循环入口
    # ========================================================================

    def start_run(self, *, preset_id: str | None = None, skill_id: str | None = None) -> None:
        """从 MODE_SELECT/PRESET_SELECT/MAIN_MENU/RESULT 进入到运行态。"""
        if preset_id and preset_id in self.bundle.presets:
            self.context.preset_id = preset_id
        if skill_id == "invincible":
            skill_id = "bomb_trap"
        if skill_id in ACTIVE_SKILLS:
            self.active_skill_id = skill_id
        # 重新加载预设
        preset = self.bundle.presets[self.context.preset_id]
        attrs = preset["attributes"]
        self.player.base_max_hp = attrs["max_hp"]
        self.player.base_move_speed = attrs["move_speed"]
        self.player.base_armor = attrs.get("armor", 0)
        self.player.base_pickup_radius = attrs.get("pickup_radius", 90)
        self.player.current_hp = self.player.base_max_hp
        self.player.current_shield = attrs.get("current_shield", 0)
        self.player.max_shield = attrs.get("max_shield", 0)
        self.player.current_armor = self.player.base_armor
        self.player.status = PlayerStatus.ACTIVE
        # 开局保护让玩家有时间确认窗口焦点和操作方式。
        self.player.invuln_left = 2.5
        self.player.damage_taken_total = 0
        self.player.shield_absorbed_total = 0
        self.player.extra_max_hp_pct = 0.0
        self.player.growth = self.player.growth.__class__()
        initial_weapon_ids = self._valid_starting_weapons(getattr(self, "selected_starting_weapon_ids", []))
        weapon_cfgs = [self.bundle.weapons[wid] for wid in initial_weapon_ids]
        self.weapon_sys = WeaponSystem()
        self.weapon_sys.populate(weapon_cfgs, active_weapon_id=initial_weapon_ids[0] if initial_weapon_ids else preset.get("active_weapon"))
        # 关卡初始化
        self.context.stage_index = 1
        self.context.endless_cycle = 0
        self.context.stage_score = 0
        self.context.run_score = 0
        self.context.card_score = 0
        self.context.kills_run = 0
        self.context.cards_run = 0
        self.context.cards_run = 0
        self.context.super_progress = 0
        self.context.super_queued = 0
        self.context.pending_cards = 0
        self.context.no_damage_time = 0
        self.context.no_damage_max_run = 0
        self.context.bomb_dodges_run = 0
        self.context.score_run_record = 0
        self.context.last_passive_minute = 0
        self.context.enter_stage(1)
        self.timer.reset_run()
        self.level_sys.reset()
        self._apply_account_perks()
        self.ach_sys.reset()
        self.spawn_director.reset()
        self.drop_sys.reset()
        self.projectile_sys.reset()
        self.super_director.reset()
        self._card_offer_now = None
        self._level_offer_now = None
        self._ending_left = 0.0
        self._ending_result = "defeat"
        self.last_player_attack_time = -99.0
        self.stage_lockdown = False
        self.stage_boss_defeated = False
        self.stage_boss_queued = False
        self.stage_featured_enemy_spawned = False
        self.active_skill_cd_left = 0.0
        self.active_skill_left = 0.0
        self.active_skill_tick_left = 0.0
        self.active_skill_uses = 0
        self.temp_buff_until.clear()
        self.roll_start_pos = None
        self.roll_target_pos = None
        self.roll_duration = 0.0
        self.roll_left = 0.0
        self.last_roll_finished_at = -99.0
        self.last_roll_finished_pos = None
        self.run_revives_left = 1
        self.run_gold_earned = 0
        self.card_combo_counts = {key: 0 for key in CARD_COMBO_SETS}
        self.card_combo_unlocked.clear()
        self.weapon_synergies_active.clear()
        self.weapon_synergy_state.clear()
        self.last_weapon_synergy_notice = None
        self.last_damage_numbers = []
        self.active_random_event = None
        self.next_random_event_at = 24.0
        self.random_event_history = []
        self.stage_environment_events_seen.clear()
        self.run_challenges = self._generate_run_challenges()
        self.last_challenge_notice = None
        self.kill_streak = 0
        self.last_kill_time = 0.0
        self.last_killstreak_notice = None
        self._stage_heal_pickups = 0
        self.selected_equipment_ids = self._valid_equipment(getattr(self, "selected_equipment_ids", []))
        self.last_combo_notice = None
        self._run_recorded = False
        self._in_bomb_zone.clear()
        self.bomb_player_within_armed.clear()
        self.player.position = (960.0, 540.0)
        self.event_bus.reset()
        self._apply_weapon_metadata()
        self.logger.set_state("RUNNING")
        self.state_machine.force(RUNNING)
        # 战斗开始事件
        self.event_bus.publish(self._e("run_started", {
            "run_id": self.context.run_id,
            "run_seed": self.context.run_seed,
            "mode": self.context.mode,
            "preset": self.context.preset_id,
        }))

    # ---- 输入采样与移动 -----------------------------------------------

    def sample_input(self) -> InputAction:
        if self.input_provider is None:
            return InputAction()
        return self.input_provider.sample()

    def end_input_frame(self) -> None:
        if self.input_provider is not None:
            self.input_provider.end_frame()

    def _move_player(self, dir_, dt: float) -> None:
        eff = effective_stats(self.player)
        sp = eff["move_speed"]
        if self.temp_buff_until.get("speed+15%", 0.0) > self.timer.run_time:
            sp *= TEMP_BUFF_EFFECTS["speed+15%"]["move_speed_multiplier"]
        # 低生命危急反击加速
        if self.player.growth.low_hp_move_pct and (self.player.current_hp / max(1.0, eff["max_hp"])) < self.player.growth.low_hp_threshold:
            sp = sp * (1.0 + self.player.growth.low_hp_move_pct)
        (nx, ny), _ = apply_movement(
            self.player.position,
            dir_,
            sp,
            dt,
            bounds=self.bounds,
            radius=22.0,
        )
        self.player.position = (nx, ny)

    # ---- 一帧逻辑 --------------------------------------------------

    def tick(self, dt: float) -> None:
        """主循环一帧。"""
        if dt <= 0:
            return
        dt = min(dt, LOGIC_DT_MAX)
        action = self.sample_input()
        cur = self.state_machine.current
        if cur == RUNNING:
            self._running_step(dt, action)
        elif cur == PAUSED:
            self.timer.freeze_paused(dt)
            if action.pause_press:
                self.state_machine.request(RUNNING)
            self.state_machine.flush()
        elif cur == SUPER_WARNING:
            self._super_warning_step(dt)
        elif cur == LEVEL_UP:
            self._level_up_step(dt, action)
        elif cur == CARD_SELECT:
            self._card_select_step(dt, action)
        elif cur == STAGE_CLEAR:
            self._stage_clear_step(dt, action)
        elif cur == ENDING:
            self._ending_step(dt)
        elif cur == RESULT:
            self._result_step(dt, action)
        elif cur == MAIN_MENU:
            self._main_menu_step(action)
        elif cur == MODE_SELECT:
            self._mode_select_step(action)
        elif cur == PRESET_SELECT:
            self._preset_select_step(action)
        self.state_machine.flush()
        if self.input_provider is not None:
            self.input_provider.end_frame()
        # 记录 fps
        if dt > 0:
            self.debug.fps = (self.debug.fps * 0.9 + (1 / dt) * 0.1)

    # ---- 状态机子步骤 -----------------------------------------------

    def _running_step(self, dt: float, action: InputAction) -> None:
        # 玩家被动成长
        self._apply_passive_growth()
        # 玩家移动
        if (action.move_x or action.move_y) and self.roll_left <= 0:
            dir_ = normalize_move(action.move_x, action.move_y)
            self.player.facing = math.atan2(dir_[1], dir_[0])
            self._move_player(dir_, dt)
        # 武器切换
        weapon_before = self.weapon_sys.active.weapon_id if self.weapon_sys.active else None
        switched = False
        if action.weapon_index is not None:
            switched = self.weapon_sys.request_select(action.weapon_index)
        elif action.switch_weapon:
            switched = self.weapon_sys.request_switch()
        if switched:
            self.last_weapon_switch_time = self.timer.run_time
            self.event_bus.publish(self._e("weapon_switched", {
                "from": weapon_before,
                "to": self.weapon_sys.active.weapon_id if self.weapon_sys.active else None,
            }))
        if action.pause_press:
            self.state_machine.request(PAUSED)
        if action.active_skill:
            self._try_activate_skill(action)
        # 玩家无敌帧 / 护盾再生
        player_step(self.player, dt)
        self._step_active_skill(dt, action)
        # 关卡 / 时间
        self.timer.advance(dt)
        self._step_random_events(dt)
        self._step_challenges(dt)
        if self.player.status == PlayerStatus.ACTIVE:
            self.context.no_damage_time += dt
            self.context.no_damage_max_run = max(self.context.no_damage_max_run, self.context.no_damage_time)
            self._submit_achievement_event("no_damage_time", {"seconds": self.context.no_damage_max_run})
        # 武器循环
        overclock_active = self.temp_buff_until.get("aspd+15%", 0.0) > self.timer.run_time
        for weapon in self.weapon_sys.stack:
            weapon.temporary_attack_speed_multiplier = (
                TEMP_BUFF_EFFECTS["aspd+15%"]["attack_speed_multiplier"] if overclock_active else 1.0
            )
        crit_roll = self.context.rng.get("crit_rng").random() if "crit_rng" in self.context.rng.streams else self._crit_roll_default()
        candidates = self._build_candidates()
        # 武器 tick —— 投射物由 ProjectileSystem 接收
        def _emit(snapshot, target, origin, facing):
            # S2 修复：把累计的攻击溢出加成到本次基础伤害上（CB-007）
            base_damage = snapshot["damage"]
            bonus = 0.0
            if self.card_sys.attack_overflow > 0:
                # 一次性消耗所有累计溢出（避免无限叠加）
                bonus = self.card_sys.attack_overflow
                self.card_sys.attack_overflow = 0.0
                self.player.overflow_attack_power = max(0.0, self.player.overflow_attack_power - bonus)
                self.event_bus.publish(self._e("attack_overflow_consumed", {
                    "amount": bonus,
                    "consumed_at_run_time": self.timer.run_time,
                }))
            effective_damage = base_damage + bonus
            active_cfg = self.weapon_sys.active.config
            is_melee = bool(active_cfg.get("is_melee"))
            dx = target.position[0] - origin[0]
            dy = target.position[1] - origin[1]
            attack_angle = math.atan2(dy, dx)
            self.player.facing = attack_angle
            attack_range = float(snapshot.get("attack_range", active_cfg.get("attack_range", 160)))
            attack_arc = 360.0 if active_cfg.get("omnidirectional") else float(active_cfg.get("attack_arc_deg", 120))
            self.last_player_attack_time = self.timer.run_time
            self.last_player_attack_angle = attack_angle
            self.last_player_attack_range = attack_range
            self.last_player_attack_arc = attack_arc
            self.last_player_attack_is_melee = is_melee
            self.last_player_attack_weapon = snapshot["weapon_id"]
            emit_origin = origin
            spread_count = int(active_cfg.get("spread_projectile_count", 1))
            projectile_count = max(spread_count, int(snapshot.get("projectile_count", 1)))
            visual_kind = "slash" if is_melee else (
                "ricochet" if active_cfg.get("bounces", False)
                else ("laser" if active_cfg.get("beam_width", 0) else "bullet")
            )
            if is_melee and active_cfg.get("clears_enemy_bullets"):
                # 重型近战可以扫掉挥砍扇区内的敌方弹幕，形成高伤低攻速的防守价值。
                for hostile in self.projectile_sys.projectiles:
                    if not hostile.alive or hostile.faction != "enemy":
                        continue
                    hx = hostile.position[0] - origin[0]
                    hy = hostile.position[1] - origin[1]
                    if math.hypot(hx, hy) > attack_range:
                        continue
                    h_angle = math.atan2(hy, hx)
                    diff = (h_angle - attack_angle + math.pi) % (2 * math.pi) - math.pi
                    if abs(math.degrees(diff)) <= attack_arc * 0.5:
                        hostile.alive = False
            self.projectile_sys.emit(
                owner="player",
                faction="player",
                origin=emit_origin,
                target_pos=target.position,
                damage=effective_damage,
                radius=max(float(active_cfg.get("projectile_radius", 6)), 10.0 if is_melee else 0.0),
                speed=float(snapshot.get("projectile_speed", 0) or 0) if not is_melee else 0,
                lifetime=max(0.08, float(snapshot.get("projectile_lifetime", 0.5) or 0.0)),
                penetration=999 if is_melee else snapshot["penetration"],
                crit_chance=snapshot["crit_chance"],
                crit_multiplier=snapshot["crit_multiplier"],
                crit_roll=snapshot["crit_roll"],
                weapon_id=snapshot["weapon_id"],
                source_id="player",
                bounces=bool(active_cfg.get("bounces", False)),
                bounce_left=int(active_cfg.get("bounce_count", 1)),
                is_melee=is_melee,
                splash_radius=attack_range if is_melee else float(active_cfg.get("splash_radius", 0)),
                burst_arc_deg=float(active_cfg.get("spread_arc_deg", 0)) if projectile_count > 1 else 0.0,
                burst_count=projectile_count,
                attack_angle=attack_angle,
                attack_arc_deg=attack_arc,
                visual_kind=visual_kind,
                now=self.timer.run_time,
            )
            return []

        weapon_tick(
            self.weapon_sys,
            dt=dt,
            now=self.timer.run_time,
            candidates=candidates,
            attacker_pos=self.player.position,
            attacker_facing_deg=0.0,  # 全向
            can_attack=True,
            crit_rng_roll=crit_roll,
            projectile_emit=_emit,
        )

        # 投射物推进
        self.projectile_sys.step(dt=dt, now=self.timer.run_time, bounds=self.bounds)

        # 投射物碰撞检测
        self._projectile_collisions()

        # 敌人推进
        self._step_enemies(dt)
        self._step_enemy_affixes(dt)

        # 敌人死亡结算
        self._resolve_enemy_deaths()

        # 玩家受击（接触）
        self._apply_contact_damage(dt)

        # 关卡生成
        self._step_spawning()

        # 玩家被动成长
        self._apply_passive_growth()

        # 掉落 / 拾取 / 炸弹
        self._step_drops(dt)

        # 关卡通关 / 无尽循环
        self._check_stage_progression(action)

        # 抽卡 / 升级队列
        self._check_levelup_queue()
        self._check_card_queue(action)

        # 百杀与超级怪兽
        self._step_super_warning(dt)
        self._step_super_enemy(dt, candidates)

        # 玩家死亡判定
        if self.player.status == PlayerStatus.DYING:
            if self.run_revives_left > 0:
                self.run_revives_left -= 1
                eff = effective_stats(self.player)
                self.player.status = PlayerStatus.ACTIVE
                revive_ratio = max(0.45, self.selected_equipment_effects().get("revive_hp_ratio", 0.45))
                self.player.current_hp = max(1.0, eff["max_hp"] * revive_ratio)
                self.player.invuln_left = 2.0
                self.projectile_sys.reset()
                self.event_bus.publish(self._e("player_revived", {
                    "hp": self.player.current_hp,
                    "card_combos_kept": dict(self.card_combo_counts),
                }))
                return
            self.context.kill_score_to_award = 0
            self.event_bus.publish(self._e("run_ended", {"result": "defeat"}))
            self._ending_result = "defeat"
            self._ending_left = 0.65
            self.state_machine.request(ENDING)
            return

        # 同步成就数据
        self.ach_sys.notify_tick(dt, super_warning_active=False)

    def _super_warning_step(self, dt: float) -> None:
        self.timer.freeze_super_warning(dt)
        self._step_drops(0.0)  # 冻结
        self._step_super_warning(dt)

    def _level_up_step(self, dt: float, action: InputAction) -> None:
        if action.select_index is not None and 0 <= action.select_index < (len(self._level_offer_now or []) or 1):
            idx = action.select_index
            if self._level_offer_now and idx < len(self._level_offer_now):
                self._apply_level_choice(self._level_offer_now[idx])
                self.level_sys.consume_one_choice()
                self._level_offer_now = None
                if self.level_sys.pending_choices > 0:
                    self._generate_level_offers()
                else:
                    self.state_machine.request(RUNNING)

    def _card_select_step(self, dt: float, action: InputAction) -> None:
        if action.refresh_card and not getattr(self._card_offer_now, "refreshed", False):
            previous = self._card_offer_now
            next_seq = self.card_sys.next_offer_seq
            self._card_offer_now = self.card_sys.generate_offer(
                weapon_stack=[w.weapon_id for w in self.weapon_sys.stack],
                active_weapon_id=self.weapon_sys.active.weapon_id if self.weapon_sys.active else None,
                weapon_levels={w.weapon_id: w.level for w in self.weapon_sys.stack},
                rng=self.context.rng.get("card_rng"),
            )
            # 刷新属于同一次已付费抽卡，不得抬高下一次抽卡序号/费用。
            self.card_sys.next_offer_seq = next_seq
            self._card_offer_now.offer_seq = previous.offer_seq
            self._card_offer_now.cost = previous.cost
            self._card_offer_now.refreshed = True
            return
        if action.select_index is not None and 0 <= action.select_index < 3:
            offer = self._card_offer_now
            if offer is None:
                return
            self._apply_card_choice(offer, action.select_index)
            self._card_offer_now = None
            self.state_machine.request(RUNNING)
            self.context.pending_cards = max(0, self.context.pending_cards - 1)

    def _stage_clear_step(self, dt: float, action: InputAction) -> None:
        if action.pause_press or (action.select_index is not None and action.select_index == 0):
            self._advance_stage()

    def _ending_step(self, dt: float) -> None:
        """短暂保留战斗收尾，然后进入可操作的结算页。"""
        self._ending_left = max(0.0, self._ending_left - dt)
        if self._ending_left <= 0:
            if self._ending_result == "defeat":
                self.player.status = PlayerStatus.DEAD
            self._record_run_summary(self._ending_result)
            self._persist_profile()
            self.state_machine.request(RESULT)

    def _result_step(self, dt: float, action: InputAction) -> None:
        # 保存 profile
        self._persist_profile()
        if action.select_index == 0:
            self.start_run(preset_id=self.context.preset_id, skill_id=self.active_skill_id)
        elif action.select_index == 1:
            self.state_machine.request(PRESET_SELECT)
        elif action.select_index == 2:
            self.state_machine.request(MAIN_MENU)

    def _mode_select_step(self, action: InputAction) -> None:
        if action.select_index == 0:
            self.context.mode = RunMode.CAMPAIGN
            self.state_machine.request(PRESET_SELECT)
        elif action.select_index == 1:
            if self.profile.campaign_cleared:
                self.context.mode = RunMode.ENDLESS
                self.state_machine.request(PRESET_SELECT)
            else:
                # 锁定：显示提示后回 MAIN_MENU
                pass
        elif action.select_index == 2:
            self.state_machine.request(MAIN_MENU)

    def _preset_select_step(self, action: InputAction) -> None:
        # 兼容旧状态名；现在这里是开局武器配置页，确认后进入游戏。
        if action.select_index in (0, 1, 2):
            self.start_run(preset_id="preset_balanced")
        elif action.pause_press:
            self.state_machine.request(MODE_SELECT)

    def _main_menu_step(self, action: InputAction) -> None:
        # 主菜单：0=开始，其他覆盖层由渲染层处理，5=退出
        if action.select_index == 0:
            self.state_machine.request(MODE_SELECT)
        elif action.select_index == 5:
            self.running_should_exit = True
            self.state_machine.request(MAIN_MENU)

    # ========================================================================
    # 子系统步骤
    # ========================================================================

    def _apply_account_perks(self) -> None:
        """Apply permanent account unlocks at the start of a run."""
        atk = self.permanent_upgrade_level("atk")
        hp = self.permanent_upgrade_level("hp")
        gold = self.permanent_upgrade_level("gold")
        eq = self.selected_equipment_effects()
        if atk:
            bonus = 0.04 * atk
            self.player.growth.dmg_pct_bonus += bonus
            for w in self.weapon_sys.stack:
                w.dmg_pct_bonus += bonus
        if hp:
            delta = 12.0 * hp
            self.player.base_max_hp += delta
            self.player.current_hp += delta
        if gold:
            self.player.growth.pickup_radius_pct += 0.08 * gold
        if eq.get("pickup_radius_pct"):
            self.player.growth.pickup_radius_pct += eq["pickup_radius_pct"]
        if eq.get("max_hp_flat"):
            delta = eq["max_hp_flat"]
            self.player.base_max_hp += delta
            self.player.current_hp += delta
        if eq.get("armor_flat"):
            self.player.base_armor += eq["armor_flat"]
            self.player.current_armor = self.player.base_armor
        if eq.get("shield_flat"):
            self.player.max_shield += eq["shield_flat"]
            self.player.current_shield += eq["shield_flat"]
        if eq.get("aspd_pct"):
            self.player.growth.aspd_pct_bonus += eq["aspd_pct"]
            for w in self.weapon_sys.stack:
                w.aspd_pct_bonus += eq["aspd_pct"]
        if eq.get("crit_chance"):
            for w in self.weapon_sys.stack:
                w.crit_chance_bonus += eq["crit_chance"]
        if eq.get("xp_gain_pct"):
            self.level_sys.xp_gain_pct += eq["xp_gain_pct"]
        self.selected_starting_weapon_ids = self._valid_starting_weapons(self.selected_starting_weapon_ids)

    def _crit_roll_default(self) -> float:
        # 默认流
        if "crit_rng" not in self.context.rng.streams:
            return 0.0
        return self.context.rng.get("crit_rng").random()

    def _build_candidates(self) -> list[TargetCandidate]:
        cand: list[TargetCandidate] = []
        for e in self.spawn_director.enemies:
            cand.append(TargetCandidate(
                entity_id=e.entity_id,
                position=e.position,
                faction="enemy",
                hp=e.current_hp,
                hp_max=e.max_hp,
                threat=1.5 if e.is_elite else 1.0,
                archetype=e.archetype,
                is_elite=e.is_elite,
                is_super=False,
                alive=e.state not in (EnemyState.DYING, EnemyState.DEAD),
            ))
        if self.super_director.active is not None:
            e = self.super_director.active.enemy
            cand.append(TargetCandidate(
                entity_id=e.entity_id,
                position=e.position,
                faction="enemy",
                hp=e.current_hp,
                hp_max=e.max_hp,
                threat=2.5,
                archetype=e.archetype,
                is_elite=False,
                is_super=True,
                alive=e.state not in (EnemyState.DYING, EnemyState.DEAD),
            ))
        return cand

    def _step_enemies(self, dt: float) -> None:
        bombs_active = sum(1 for b in self.drop_sys.bombs if not b.resolved and self.timer.run_time >= b.armed_at)
        for e in list(self.spawn_director.enemies):
            if e.state == EnemyState.DYING:
                e.state_left -= dt
                if e.state_left <= 0:
                    e.state = EnemyState.DEAD
                continue
            if e.state == EnemyState.DEAD:
                self.spawn_director.enemies.remove(e)
                continue
            # Boss movement and attacks belong to the dedicated skill state machine.
            if e.is_super:
                continue
            if "support" in e.tags:
                e.support_cooldown_left = max(0.0, e.support_cooldown_left - dt)
                if e.support_cooldown_left <= 0 and e.state == EnemyState.SEEKING:
                    allies = [
                        ally for ally in self.spawn_director.enemies
                        if ally is not e
                        and not ally.is_super
                        and ally.state not in (EnemyState.DYING, EnemyState.DEAD)
                        and ally.current_hp < ally.max_hp * 0.82
                        and math.dist(ally.position, e.position) <= e.support_range
                    ]
                    allies.sort(key=lambda ally: ally.current_hp / max(1.0, ally.max_hp))
                    healed = []
                    for ally in allies[:2]:
                        amount = min(ally.max_hp - ally.current_hp, ally.max_hp * e.support_amount_pct)
                        if amount > 0:
                            ally.current_hp += amount
                            healed.append(ally.entity_id)
                    if healed:
                        e.support_target_ids = tuple(healed)
                        e.support_pulse_left = 0.68
                        e.support_cooldown_left = e.support_cooldown
                    else:
                        e.support_cooldown_left = min(1.25, e.support_cooldown)
            def _projectile_emit(enemy_inst, target_pos, *, kind):
                if kind == "bomb":
                    # 由 drop_sys 生成（位置玩家一侧 0.4）
                    self.drop_sys.bombs.append(HazardBomb(
                        entity_id=f"bomb_{enemy_inst.entity_id}",
                        position=target_pos,
                        radius=120.0,
                        base_damage=self.reference_monster_def.get("contact_damage", 18) * 1.0,
                        spawn_time=self.timer.run_time,
                        damage_multiplier=1.0,
                    ))
                    return
                self.projectile_sys.emit(
                    owner=enemy_inst.entity_id,
                    faction="enemy",
                    origin=enemy_inst.position,
                    target_pos=target_pos,
                    damage=enemy_inst.projectile_damage or enemy_inst.contact_damage,
                    radius=float(enemy_inst.projectile_radius or 6),
                    speed=float(enemy_inst.projectile_speed),
                    lifetime=float(enemy_inst.projectile_lifetime),
                    penetration=1,
                    crit_chance=0.0,
                    crit_multiplier=1.0,
                    crit_roll=0.0,
                    weapon_id=None,
                    source_id=enemy_inst.entity_id,
                    is_melee=False,
                    burst_arc_deg=float(enemy_inst.spread_arc_deg),
                    burst_count=max(1, int(enemy_inst.spread_projectile_count)),
                    now=self.timer.run_time,
                    visual_kind={
                        "lantern_shooter": "enemy_arcane",
                        "multinode_spreader": "enemy_shard",
                        "crystal_sniper": "enemy_rail",
                        "rail_turret": "enemy_rail",
                        "rift_dancer": "enemy_phase",
                        "void_mender": "enemy_support",
                        "prism_artillery": "enemy_prism",
                    }.get(enemy_inst.config_id, "enemy_bullet"),
                )
            step_enemy(
                e,
                dt=dt,
                now=self.timer.run_time,
                player_pos=self.player.position,
                player_alive=self.player.status == PlayerStatus.ACTIVE,
                bombs_active_count=bombs_active,
                bus=self.event_bus,
                projectile_emit=_projectile_emit,
            )

    def _resolve_enemy_deaths(self) -> None:
        # 单纯通过生命降到 0 来计分 + 触发掉落 + 触发超级怪兽进度
        super_director = self.super_director
        for e in list(self.spawn_director.enemies):
            # 只允许活体进入一次死亡结算。旧条件会让刚变成 DEAD、尚未来得及
            # 从列表移除的尸体再次回到 DYING，造成无限重复计分/掉落/抽卡。
            if e.current_hp <= 0 and e.state not in (EnemyState.DYING, EnemyState.DEAD):
                e.state = EnemyState.DYING
                # 尸体只保留短促的死亡反馈，随后马上回收，避免堆满画面。
                e.state_left = 0.24
                e.current_hp = 0
                # 计分 + 超级怪兽进度（仅非超级怪的 no_score false）
                if not e.is_super and "no_score" not in (e.tags or []):
                    base_score = e.base_kill_score
                    elite_factor = 4 if e.is_elite else 1
                    self.scoring_sys.award_kill(
                        self.context,
                        base_kill_score=base_score,
                        elite_factor=elite_factor,
                    )
                    # Boss 现在由关卡分数门槛触发，避免开局按击杀数过早刷出。
                    # 经验只由地面经验拾取进入。旧实现击杀直接给一次、拾取
                    # 又给一次，导致升级选择弹窗过于频繁并打断移动。
                    # 成就事件
                    self._submit_achievement_event("enemy_defeated", {"enemy_id": e.entity_id})
                    self._submit_achievement_event("score_awarded", {
                        "run_score": self.context.run_score,
                        "final": base_score * elite_factor,
                    })
                # 死亡事件
                self.event_bus.publish(self._e("enemy_defeated", {
                    "enemy_id": e.entity_id,
                    "config_id": e.config_id,
                    "is_elite": e.is_elite,
                    "is_super": e.is_super,
                    "position": list(e.position),
                    "score": e.base_kill_score * (4 if e.is_elite else 1),
                    "affixes": list(e.elite_affixes),
                }))
                self._handle_enemy_death_extras(e)
                self._update_challenges_on_kill(e)
                # 掉落
                if not e.is_super and "no_score" not in (e.tags or []):
                    self._spawn_drops_for(e)
        # 超级怪兽死亡
        if self.super_director.active and self.super_director.active.enemy.current_hp <= 0 and not self.super_director.active.defeated:
            se = self.super_director.active
            se.enemy.state = EnemyState.DYING
            se.enemy.state_left = 0.32
            self.scoring_sys.award_kill(
                self.context, base_kill_score=se.super_kill_score, elite_factor=1,
            )
            self.context.super_kills_run += 1
            self.event_bus.publish(self._e("super_enemy_defeated", {
                "index": se.index_in_run, "reference": se.reference_archetype,
                "skills": [s.value for s in se.skill_pool],
                "position": list(se.enemy.position),
            }))
            self._submit_achievement_event("super_enemy_defeated", {"index": se.index_in_run})
            self._spawn_drops_for(se.enemy, super_drop=True)
            self._grant_boss_reward(se)
            self.stage_boss_defeated = True
            self.super_director.on_defeated()

    def _handle_enemy_death_extras(self, e: Enemy) -> None:
        if "corrupt_blood" in self.weapon_synergies_active and "w_venom_knife" in {w.weapon_id for w in self.weapon_sys.stack}:
            healed = heal_player(self.player, amount=max(1.0, effective_stats(self.player)["max_hp"] * 0.018))
            if healed > 0:
                self.event_bus.publish(self._e("weapon_synergy_triggered", {
                    "combo_id": "corrupt_blood", "name": "腐血", "healed": healed,
                }))
        if "volatile" in e.elite_affixes:
            self._deal_area_damage(e.position, radius=130, damage=max(12.0, e.contact_damage * 1.4), source_id="affix:volatile")
        if "split" in e.elite_affixes and "split_child" not in (e.tags or []):
            self._spawn_split_children(e)

    def _spawn_split_children(self, e: Enemy) -> None:
        if len(self.spawn_director.enemies) >= ENEMY_HARD_CAP - 1:
            return
        cfg = self.bundle.enemies.get(e.config_id, self.bundle.enemies.get("spinner_chaser"))
        if cfg is None:
            return
        rng = self.context.rng.get("enemy_spawn_rng")
        for i in range(2):
            angle = i * math.pi + rng.uniform(-0.35, 0.35)
            pos = clamp_to_playable_bounds(
                (e.position[0] + math.cos(angle) * 45, e.position[1] + math.sin(angle) * 45),
                self.bounds,
                radius=max(12, e.collision_radius * 0.55),
            )
            child = spawn_enemy(config=cfg, position=pos, rng=rng, time_form=e.time_form, now=self.timer.run_time)
            child.max_hp = max(6.0, e.max_hp * 0.28)
            child.current_hp = child.max_hp
            child.move_speed = e.move_speed * 1.08
            child.collision_radius = max(10.0, e.collision_radius * 0.62)
            child.base_kill_score = max(1, e.base_kill_score // 3)
            child.tags = tuple(dict.fromkeys((*child.tags, "split_child", "no_score")))
            self.spawn_director.enemies.append(child)
        self.event_bus.publish(self._e("enemy_split", {"enemy_id": e.entity_id, "count": 2}))

    def _update_challenges_on_kill(self, e: Enemy) -> None:
        if self.timer.run_time - self.last_kill_time <= 3.0:
            self.kill_streak += 1
        else:
            self.kill_streak = 1
        self.last_kill_time = self.timer.run_time
        if self.kill_streak in (10, 25, 50):
            self.last_killstreak_notice = {"count": self.kill_streak, "time": self.timer.run_time}
            self.event_bus.publish(self._e("killstreak_notice", self.last_killstreak_notice))
        for ch in self.run_challenges:
            if ch.get("completed") or ch.get("failed"):
                continue
            typ = ch["type"]
            if typ == "kills_in_time":
                ch["progress"] = int(ch.get("progress", 0)) + 1
                if ch["progress"] >= ch["target"] and self.timer.run_time <= ch["deadline"]:
                    self._complete_challenge(ch)
            elif typ == "killstreak" and self.kill_streak >= ch["target"]:
                ch["progress"] = self.kill_streak
                self._complete_challenge(ch)
            elif typ == "melee_elite" and e.is_elite:
                wid = getattr(e, "last_hit_weapon_id", "")
                if wid and self.bundle.weapons.get(wid, {}).get("is_melee"):
                    ch["progress"] = int(ch.get("progress", 0)) + 1
                    self._complete_challenge(ch)

    def _grant_boss_reward(self, se) -> None:
        self._grant_gold(35 + 15 * max(1, self.context.stage_index), source="boss")
        self.context.pending_cards += 1
        # 子报告 P1-5：旧实现 `cards_run += 0` 是 dead code；_apply_card_choice 自然累计。
        self._card_offer_now = self.card_sys.generate_offer(
            weapon_stack=[w.weapon_id for w in self.weapon_sys.stack],
            active_weapon_id=self.weapon_sys.active.weapon_id if self.weapon_sys.active else None,
            weapon_levels={w.weapon_id: w.level for w in self.weapon_sys.stack},
            rng=self.context.rng.get("card_rng"),
        )
        self._card_offer_now.cost = 0
        self.event_bus.publish(self._e("boss_reward_granted", {
            "index": se.index_in_run,
            "reward": "card_offer",
        }))
        self.state_machine.request(CARD_SELECT)

    def _apply_contact_damage(self, dt: float) -> None:
        if self.player.status != PlayerStatus.ACTIVE:
            return
        for e in self.spawn_director.enemies:
            if e.state in (EnemyState.DYING, EnemyState.DEAD):
                continue
            # 普通近战只有在前摇完成、攻击真正落下的那个短窗口才造成接触
            # 伤害；不能只要模型重叠就每 0.8 秒自动扣血。远程伤害由弹体结算。
            if e.is_super or e.projectile_speed > 0 or e.drops_bomb:
                continue
            if e.last_attack_time <= 0 or self.timer.run_time - e.last_attack_time > max(0.08, dt * 2):
                continue
            d = math.hypot(e.position[0] - self.player.position[0], e.position[1] - self.player.position[1])
            if d < e.collision_radius + 22:
                if self.timer.run_time >= e.contact_cooldown_until:
                    e.contact_cooldown_until = self.timer.run_time + 0.8
                    # 应用伤害
                    dmg = e.contact_damage
                    self._damage_player(dmg, source_id=e.entity_id)
        # 超级怪兽接触
        if self.super_director.active and self.super_director.active.enemy.state not in (EnemyState.DYING, EnemyState.DEAD):
            e = self.super_director.active.enemy
            d = math.hypot(e.position[0] - self.player.position[0], e.position[1] - self.player.position[1])
            if d < e.collision_radius + 22 and self.timer.run_time >= e.contact_cooldown_until:
                e.contact_cooldown_until = self.timer.run_time + 0.8
                self._damage_player(e.contact_damage, source_id=e.entity_id)

    def _damage_player(self, raw_damage: float, *, source_id: str) -> None:
        if self.player.invuln_left > 0 or self.player.status != PlayerStatus.ACTIVE:
            return
        hp_lost, absorbed = apply_player_damage(
            self.player, raw_damage=raw_damage, source_id=source_id, now=self.timer.run_time,
        )
        self.context.no_damage_time = 0.0  # 重置无伤计时
        self.event_bus.publish(self._e("damage_applied", {
            "to_player": True,
            "source_id": source_id,
            "raw": raw_damage, "absorbed": absorbed, "hp_lost": hp_lost,
            "shield_left": self.player.current_shield, "hp_left": self.player.current_hp,
        }))
        self._submit_achievement_event("damage_applied", {"to_player": True})

    def _try_activate_skill(self, action: InputAction) -> None:
        if self.active_skill_cd_left > 0 or self.player.status in (PlayerStatus.DYING, PlayerStatus.DEAD):
            return
        cfg = ACTIVE_SKILLS.get(self.active_skill_id, ACTIVE_SKILLS["bomb_trap"])
        self.active_skill_cd_left = float(cfg["cooldown"])
        self.active_skill_left = float(cfg["duration"])
        self.active_skill_tick_left = 0.0
        self.active_skill_uses += 1
        if self.active_skill_id == "bomb_trap":
            self._place_player_bombs()
        elif self.active_skill_id == "roll":
            for ch in self.run_challenges:
                if ch.get("type") == "no_roll_time" and not ch.get("completed"):
                    ch["failed"] = True
                    self.event_bus.publish(self._e("challenge_failed", {"id": ch["id"], "name": ch["name"]}))
            dx, dy = normalize_move(action.move_x, action.move_y)
            if dx == 0 and dy == 0:
                dx, dy = math.cos(self.player.facing), math.sin(self.player.facing)
            dist = float(cfg.get("distance", 260.0))
            self.roll_start_pos = self.player.position
            self.roll_target_pos = clamp_to_playable_bounds(
                (self.player.position[0] + dx * dist, self.player.position[1] + dy * dist),
                self.bounds,
                radius=22.0,
            )
            self.roll_duration = max(0.08, float(cfg["duration"]))
            self.roll_left = self.roll_duration
            self.player.invuln_left = max(self.player.invuln_left, float(cfg["duration"]))
        self.event_bus.publish(self._e("active_skill_used", {
            "skill_id": self.active_skill_id,
            "cooldown": self.active_skill_cd_left,
        }))

    def _step_active_skill(self, dt: float, action: InputAction) -> None:
        if self.active_skill_cd_left > 0:
            self.active_skill_cd_left = max(0.0, self.active_skill_cd_left - dt)
        if self.active_skill_left <= 0:
            return
        self.active_skill_left = max(0.0, self.active_skill_left - dt)
        if self.active_skill_id == "axe_orbit":
            self.player.invuln_left = max(self.player.invuln_left, 0.08)
            self._block_enemy_projectiles_with_axes()
            self.active_skill_tick_left -= dt
            if self.active_skill_tick_left <= 0:
                self.active_skill_tick_left = 0.20
                self._apply_axe_orbit_damage()
        elif self.active_skill_id == "roll" and self.roll_left > 0 and self.roll_start_pos and self.roll_target_pos:
            self.roll_left = max(0.0, self.roll_left - dt)
            t = 1.0 - self.roll_left / max(0.001, self.roll_duration)
            eased = 1.0 - (1.0 - t) * (1.0 - t)
            sx, sy = self.roll_start_pos
            tx, ty = self.roll_target_pos
            self.player.position = (sx + (tx - sx) * eased, sy + (ty - sy) * eased)
            self.player.invuln_left = max(self.player.invuln_left, 0.04)
            if self.roll_left <= 0:
                self.player.position = self.roll_target_pos
                self.last_roll_finished_at = self.timer.run_time
                self.last_roll_finished_pos = self.roll_target_pos

    def _apply_axe_orbit_damage(self) -> None:
        cfg = ACTIVE_SKILLS["axe_orbit"]
        px, py = self.player.position
        for e in self.spawn_director.enemies:
            if e.state in (EnemyState.DYING, EnemyState.DEAD) or e.current_hp <= 0:
                continue
            d = math.hypot(e.position[0] - px, e.position[1] - py)
            if d <= float(cfg.get("radius", 170.0)) + e.collision_radius:
                e.current_hp -= float(cfg["damage"])
                self.event_bus.publish(self._e("damage_applied", {
                    "source_id": "skill_axe_orbit",
                    "target_id": e.entity_id,
                    "raw": cfg["damage"],
                    "final": cfg["damage"],
                    "overflow": 0,
                    "crit": False,
                    "is_super": e.is_super,
                }))

    def _block_enemy_projectiles_with_axes(self) -> None:
        px, py = self.player.position
        radius = float(ACTIVE_SKILLS["axe_orbit"].get("radius", 170.0))
        blocked = 0
        for p in self.projectile_sys.projectiles:
            if not p.alive or p.faction != "enemy":
                continue
            d = math.hypot(p.position[0] - px, p.position[1] - py)
            if d <= radius + p.radius:
                p.alive = False
                blocked += 1
        if blocked:
            self.event_bus.publish(self._e("projectiles_blocked", {
                "source_id": "skill_axe_orbit",
                "count": blocked,
            }))

    def _place_player_bombs(self) -> None:
        px, py = self.player.position
        cfg = ACTIVE_SKILLS["bomb_trap"]
        distance = 128.0
        for i, angle in enumerate((0.0, math.pi * 0.5, math.pi, math.pi * 1.5)):
            pos = clamp_to_playable_bounds(
                (px + math.cos(angle) * distance, py + math.sin(angle) * distance),
                self.bounds,
                radius=24.0,
            )
            bomb = HazardBomb(
                entity_id=f"player_bomb_{self.active_skill_uses}_{i}_{int(self.timer.run_time * 1000)}",
                position=pos,
                radius=float(cfg["radius"]),
                base_damage=float(cfg["damage"]),
                spawn_time=self.timer.run_time,
                arm_delay=0.25,
                armed_at=self.timer.run_time + 0.25,
                lifetime=1.9,
                icon="bomb",
                faction="player",
                harmless_to_player=True,
            )
            self.drop_sys.bombs.append(bomb)
        self.event_bus.publish(self._e("player_bombs_placed", {"count": 4}))

    def _step_spawning(self) -> None:
        if self.stage_lockdown:
            return
        # 选关
        if self.context.mode == RunMode.ENDLESS:
            stage_cfg = self.bundle.stages["endless"]
        else:
            stage_cfg = self.bundle.stages.get(f"stage_{self.context.stage_index}", self.bundle.stages["stage_1"])
        spawn_cfg = SpawnConfig(
            enemy_pool=stage_cfg["enemy_pool"],
            enemy_weights=stage_cfg["enemy_weights"],
            spawn_budget_base=1.0,
            elite_base_chance=stage_cfg.get("elite_base_chance", 0.02),
            max_elite_chance=stage_cfg.get("max_elite_chance", 0.25),
        )
        spawn_cfg.min_player_distance = 480
        mods = stage_modifiers(
            stage_index=self.context.stage_index,
            endless_cycle=self.context.endless_cycle,
            elapsed_minutes=int(self.timer.stage_time // 60),
            stage_cfg=stage_cfg,
        )
        # 修改视觉层级
        self.context.visual_difficulty_tier = mods.visual_tier

        def _on_enemy_spawn(chosen_id, pos, is_elite, tf, sector_deg, rc):
            cfg = self.bundle.enemies.get(chosen_id)
            if cfg is None:
                return
            e = spawn_enemy(
                config=cfg,
                position=pos,
                rng=rc.rng.get("enemy_spawn_rng"),
                time_form=tf,
                is_elite=is_elite,
                hp_multiplier=mods.hp_multiplier,
                damage_multiplier=mods.damage_multiplier,
                armor_bonus=mods.armor_bonus,
                elapsed_min=int(self.timer.stage_time // 60),
                endless_cycle=self.context.endless_cycle,
                now=self.timer.run_time,
            )
            self._apply_enemy_affixes(e)
            self.spawn_director.enemies.append(e)
            self.event_bus.publish(self._e("enemy_spawned", {
                "enemy_id": e.entity_id, "config_id": e.config_id,
                "position": list(e.position), "sector_deg": sector_deg,
                "is_elite": e.is_elite, "time_form": e.time_form,
                "max_hp": e.max_hp, "damage": e.contact_damage,
                "affixes": list(e.elite_affixes),
            }))

        # 每关保证展示一次新远程兵，避免随机权重让玩家整局都碰不到。
        if not self.stage_featured_enemy_spawned and self.timer.stage_time >= 5.0:
            rng = self.context.rng.get("enemy_spawn_rng")
            sector = 45.0 * ((self.context.stage_index * 3) % 8)
            pos = self.spawn_director._spawn_position(
                sector, self.spawn_director.bounds, self.player.position, 480, rng,
            )
            if pos is not None:
                _on_enemy_spawn("crystal_sniper", pos, False, "T0", sector, self.context)
                self.stage_featured_enemy_spawned = True

        self.spawn_director.step(
            run_context=self.context,
            stage_cfg=stage_cfg,
            spawn_cfg=spawn_cfg,
            player_pos=self.player.position,
            player_alive=self.player.status == PlayerStatus.ACTIVE,
            bombs_active_count=sum(1 for b in self.drop_sys.bombs if not b.resolved),
            on_enemy_spawn=_on_enemy_spawn,
        )

        self._check_score_boss_trigger()

    def _check_score_boss_trigger(self) -> None:
        if self.context.mode == RunMode.ENDLESS:
            threshold = (self.context.endless_cycle + 1) * 3200
        else:
            threshold = STAGE_BOSS_THRESHOLDS.get(self.context.stage_index, STAGE_BOSS_THRESHOLDS[MAX_CAMPAIGN_STAGE])
        if self.stage_boss_queued or self.stage_boss_defeated:
            return
        if self.super_director.active is not None or self.super_director.queued > 0:
            return
        if self.context.stage_score >= threshold:
            self.stage_boss_queued = True
            self.super_director.queued += 1
            self.context.super_queued = self.super_director.queued
            self.event_bus.publish(self._e("score_boss_queued", {
                "stage": self.context.stage_index,
                "stage_score": self.context.stage_score,
                "threshold": threshold,
            }))

    def _spawn_drops_for(self, enemy: Enemy, *, super_drop: bool = False) -> None:
        spawn_drops_on_enemy_defeated(
            self.drop_sys,
            run_context=self.context,
            enemy=enemy,
            drop_tables=self.bundle.drop_tables,
            player_pos=self.player.position,
            player_current_hp=self.player.current_hp,
            player_max_hp=effective_stats(self.player)["max_hp"],
            player_alive=self.player.status == PlayerStatus.ACTIVE,
            table_id="super_drops" if super_drop else None,
        )

    def _step_drops(self, dt: float) -> None:
        eff = effective_stats(self.player)
        pickup_r = self.player.base_pickup_radius * (1.0 + self.player.growth.pickup_radius_pct)
        # magnetize & pickup
        if dt > 0:
            for p in self.drop_sys.pickups:
                if p.resolved:
                    continue
                d = math.hypot(p.position[0] - self.player.position[0], p.position[1] - self.player.position[1])
                if d <= pickup_r and self.player.status == PlayerStatus.ACTIVE:
                    self._on_pickup_collected(p)
                    p.resolved = True
            # 推进炸弹检测（玩家在危险圈内、爆炸时已离开 = dodge）
            for b in self.drop_sys.bombs:
                if b.resolved:
                    continue
                armed = self.timer.run_time >= b.armed_at
                if armed:
                    in_zone = math.hypot(b.position[0] - self.player.position[0], b.position[1] - self.player.position[1]) <= b.radius
                    self.bomb_player_within_armed[b.entity_id] = in_zone
            # 炸弹爆炸处理
            for b in list(self.drop_sys.bombs):
                if b.resolved:
                    continue
                armed = self.timer.run_time >= b.armed_at
                if not armed:
                    continue
                # 触发时间 = armed_at + 剩余寿命
                trigger_at = b.armed_at + max(0.0, b.lifetime - b.arm_delay - 0.0001)
                if self.timer.run_time >= trigger_at:
                    b.resolved = True
                    if getattr(b, "faction", "enemy") == "player" or getattr(b, "harmless_to_player", False):
                        self._explode_player_bomb(b)
                        self.bomb_player_within_armed.pop(b.entity_id, None)
                        self.event_bus.publish(self._e("player_bomb_triggered", {
                            "position": list(b.position), "radius": b.radius, "damage": b.base_damage,
                        }))
                        continue
                    # 伤害玩家
                    in_zone_now = math.hypot(b.position[0] - self.player.position[0], b.position[1] - self.player.position[1]) <= b.radius
                    was_in = self.bomb_player_within_armed.get(b.entity_id, False)
                    if in_zone_now and self.player.status == PlayerStatus.ACTIVE:
                        self._damage_player(b.base_damage * b.damage_multiplier, source_id=b.entity_id)
                    elif was_in and not in_zone_now and self.player.status == PlayerStatus.ACTIVE:
                        # 躲避成功
                        self.context.bomb_dodges_run += 1
                        self.event_bus.publish(self._e("hazard_drop_dodged", {"bomb_id": b.entity_id}))
                        self._submit_achievement_event("hazard_drop_dodged", {})
                    self.bomb_player_within_armed.pop(b.entity_id, None)
                    self.event_bus.publish(self._e("hazard_drop_triggered", {
                        "position": list(b.position), "radius": b.radius, "damage": b.base_damage,
                    }))
            # 到期回收
            self.drop_sys.pickups = [p for p in self.drop_sys.pickups if not p.resolved and (self.timer.run_time - p.spawn_time) < p.lifetime]
            self.drop_sys.bombs = [b for b in self.drop_sys.bombs if not b.resolved and (self.timer.run_time - b.spawn_time) < b.lifetime]

    def _explode_player_bomb(self, bomb: HazardBomb) -> None:
        kill_candidates = 0
        for e in self.spawn_director.enemies:
            if e.state in (EnemyState.DYING, EnemyState.DEAD) or e.current_hp <= 0:
                continue
            d = math.hypot(e.position[0] - bomb.position[0], e.position[1] - bomb.position[1])
            if d <= bomb.radius + e.collision_radius:
                damage = bomb.base_damage * bomb.damage_multiplier
                e.current_hp -= damage
                if e.current_hp <= 0:
                    kill_candidates += 1
                self.event_bus.publish(self._e("damage_applied", {
                    "source_id": bomb.entity_id,
                    "target_id": e.entity_id,
                    "raw": damage,
                    "final": damage,
                    "overflow": 0,
                    "crit": False,
                    "is_super": e.is_super,
                }))
        if kill_candidates:
            for ch in self.run_challenges:
                if ch.get("type") == "bomb_multikill" and not ch.get("completed") and not ch.get("failed"):
                    ch["progress"] = max(int(ch.get("progress", 0)), kill_candidates)
                    if kill_candidates >= ch["target"]:
                        self._complete_challenge(ch)

    def _grant_temp_buff(self, buff: str | None, duration: float) -> bool:
        if buff not in TEMP_BUFF_EFFECTS or duration <= 0:
            return False
        expires = max(self.timer.run_time, self.temp_buff_until.get(buff, 0.0)) + duration
        self.temp_buff_until[buff] = expires
        return True

    def _on_pickup_collected(self, p: Pickup) -> None:
        if p.kind == "xp_small" or p.kind == "xp_large" or p.kind == "xp":
            amount = max(1, int(round(float(p.amount) * self._active_event_multiplier("xp"))))
            self.level_sys.add_xp(amount)
            self.event_bus.publish(self._e("pickup_collected", {"kind": p.kind, "amount": amount}))
        elif p.kind == "heal":
            self._stage_heal_pickups += 1
            for ch in self.run_challenges:
                if ch.get("type") == "no_heal_stage" and not ch.get("completed"):
                    ch["failed"] = True
                    self.event_bus.publish(self._e("challenge_failed", {"id": ch["id"], "name": ch["name"]}))
            eff = effective_stats(self.player)
            healed = heal_player(self.player, amount=max(p.amount, eff["max_hp"] * 0.12))
            self.event_bus.publish(self._e("pickup_collected", {"kind": p.kind, "amount": healed}))
        elif p.kind == "shield_restore":
            self.player.current_shield = min(self.player.max_shield + self.player.growth.max_shield_extra, self.player.current_shield + p.amount)
            self.event_bus.publish(self._e("pickup_collected", {"kind": p.kind, "amount": p.amount}))
        elif p.kind == "armor":
            self.player.base_armor += p.amount
            self.player.current_armor = self.player.base_armor
            self.event_bus.publish(self._e("pickup_collected", {"kind": p.kind, "amount": p.amount}))
        elif p.kind == "coin":
            amount = int(p.amount)
            self._grant_gold(amount, source="drop")
            self.event_bus.publish(self._e("pickup_collected", {"kind": p.kind, "amount": amount}))
        elif p.kind == "skill_charge":
            before = self.active_skill_cd_left
            self.active_skill_cd_left = max(0.0, before - max(0.0, p.amount))
            reduced = before - self.active_skill_cd_left
            bonus_buff = p.buff if reduced <= 0 and self._grant_temp_buff(p.buff, p.buff_duration) else None
            self.event_bus.publish(self._e("pickup_collected", {
                "kind": p.kind, "amount": reduced, "bonus_buff": bonus_buff,
            }))
        elif p.kind == "temp_buff":
            applied = self._grant_temp_buff(p.buff, p.buff_duration)
            self.event_bus.publish(self._e("pickup_collected", {
                "kind": p.kind, "buff": p.buff if applied else None,
                "duration": p.buff_duration if applied else 0.0,
            }))

    def _check_stage_progression(self, action: InputAction) -> None:
        if self.context.mode == RunMode.ENDLESS:
            if self.context.stage_score >= (self.context.endless_cycle + 1) * 5000:
                self.context.endless_cycle += 1
                self.event_bus.publish(self._e("endless_cycle_completed", {"cycle": self.context.endless_cycle}))
                # 无尽循环不重置 stage_score，按规则
            return
        # 分数仅触发关底封锁：停止继续刷新，玩家要清掉场上存量怪。
        # 本关 Boss 被击杀时则立即满足通关条件。
        thresholds = STAGE_CLEAR_THRESHOLDS
        if self.stage_boss_defeated:
            if self._card_offer_now is not None or self.context.pending_cards > 0:
                return
            self._trigger_stage_clear()
            return
        threshold = thresholds[self.context.stage_index]
        if not self.stage_lockdown and self.context.stage_score >= threshold:
            self.stage_lockdown = True
            self.event_bus.publish(self._e("stage_lockdown_started", {
                "stage": self.context.stage_index,
                "remaining": len(self.spawn_director.enemies),
            }))
        if self.stage_lockdown:
            living = [
                e for e in self.spawn_director.enemies
                if e.state not in (EnemyState.DYING, EnemyState.DEAD) and e.current_hp > 0
            ]
            if not living and self.super_director.active is None:
                self._trigger_stage_clear()

    def _trigger_stage_clear(self) -> None:
        for ch in self.run_challenges:
            if ch.get("type") == "no_heal_stage" and not ch.get("completed") and not ch.get("failed"):
                self._complete_challenge(ch)
        self.event_bus.publish(self._e("stage_cleared", {
            "stage": self.context.stage_index,
            "stage_score": self.context.stage_score,
            "run_score": self.context.run_score,
            "run_time": self.timer.run_time,
        }))
        self._submit_achievement_event("stage_cleared", {"stage": self.context.stage_index})
        # 恢复生命 35% 最大值
        eff = effective_stats(self.player)
        heal_amount = eff["max_hp"] * 0.35
        self.player.current_hp = min(eff["max_hp"], self.player.current_hp + heal_amount)
        if self.context.stage_index >= MAX_CAMPAIGN_STAGE:
            # RUNNING 不能直接跳 RESULT，必须经 ENDING 完成本局收尾。
            self.profile.campaign_cleared = True
            self._ending_result = "victory"
            self._ending_left = 0.65
            self.event_bus.publish(self._e("run_ended", {"result": "victory"}))
            self.state_machine.request(ENDING)
        else:
            self.state_machine.request(STAGE_CLEAR)

    def _advance_stage(self) -> None:
        self.context.stage_index = min(MAX_CAMPAIGN_STAGE, self.context.stage_index + 1)
        self.context.stage_score = 0
        self.context.enter_stage(self.context.stage_index)
        self.timer.reset_stage()
        # 换关时清场，确保新背景对应的新怪物池和新贴图立即生效。
        self.spawn_director.reset()
        self.projectile_sys.reset()
        self.drop_sys.reset()
        self.super_director.reset()
        if self.active_random_event and self.active_random_event.get("unique_stage_event"):
            self.active_random_event = None
        if self._has_pending_stage_environment_event():
            self.next_random_event_at = self.timer.run_time + 10.0
        self.stage_lockdown = False
        self.stage_boss_defeated = False
        self.stage_boss_queued = False
        self.stage_featured_enemy_spawned = False
        self.state_machine.request(RUNNING)

    def _check_levelup_queue(self) -> None:
        if self.input_provider is None:
            return
        if self.level_sys.pending_choices > 0 and self._level_offer_now is None:
            self.state_machine.request(LEVEL_UP)
            self._generate_level_offers()

    def _generate_level_offers(self) -> None:
        # 简单的升级候选：3 个不同类型
        pool = [
            ("c_atk_plus", "攻击强化 +15%"),
            ("c_hp_plus", "最大生命 +20"),
            ("c_speed_plus", "攻击速度 +12%"),
            ("c_armor_plus", "护甲 +4"),
            ("c_pickup_plus", "拾取范围 +25%"),
        ]
        # 排除已唯一 / 不可叠加限制
        # 简化：从池子里随机抽 3 个不同条目
        seen = set()
        offers = []
        rng = self.context.rng.get("card_rng")
        cands = list(pool)
        rng.shuffle(cands)
        for cid, name in cands:
            if cid in seen:
                continue
            seen.add(cid)
            offers.append({"card_id": cid, "name_zh": name})
            if len(offers) >= 3:
                break
        self._level_offer_now = offers

    def _apply_level_choice(self, entry: dict) -> None:
        # 与 _apply_card_choice 类似，但把 is_card_offer=False
        card_id = entry["card_id"]
        cfg = self.bundle.cards.get(card_id)
        if cfg is None:
            return
        self._apply_card_effect(card_id, cfg)

    def _check_card_queue(self, action: InputAction) -> None:
        if self.input_provider is None:
            return
        if self._card_offer_now is not None:
            return
        cost = 800 if self.context.mode == RunMode.ENDLESS else self._next_card_cost()
        if self.context.card_score < cost:
            return
        # 评分达到明确门槛才抽卡；未达到时不会产生任何弹窗。
        self.context.card_score -= cost
        self.context.pending_cards = 1
        self._card_offer_now = self.card_sys.generate_offer(
            weapon_stack=[w.weapon_id for w in self.weapon_sys.stack],
            active_weapon_id=self.weapon_sys.active.weapon_id if self.weapon_sys.active else None,
            weapon_levels={w.weapon_id: w.level for w in self.weapon_sys.stack},
            rng=self.context.rng.get("card_rng"),
        )
        self._card_offer_now.cost = cost
        self.state_machine.request(CARD_SELECT)

    def _next_card_cost(self) -> int:
        from .cards.cards import campaign_card_cost
        # next_offer_seq 就是下一次正式抽卡的序号。旧代码减一会令前两次
        # 抽卡都按第一次价格结算。
        n = max(1, self.card_sys.next_offer_seq)
        return campaign_card_cost(n)

    def _apply_card_choice(self, offer, idx: int) -> None:
        if offer is None or idx >= len(offer.cards):
            return
        card = offer.cards[idx]
        cfg = self.bundle.cards.get(card.card_id, {})
        if not cfg:
            return
        self.card_sys.resolve(
            offer,
            idx,
            weapon_stack=[w.weapon_id for w in self.weapon_sys.stack],
            active_weapon_id=self.weapon_sys.active.weapon_id if self.weapon_sys.active else None,
            weapon_levels={w.weapon_id: w.level for w in self.weapon_sys.stack},
            apply_card_effect=lambda c: self._apply_card_effect(c.card_id, cfg),
            on_new_weapon=lambda: None,
            on_weapon_discarded=lambda: None,
            on_weapon_upgrade=lambda: None,
            on_attack_capped=lambda: None,
            rng=self.context.rng.get("card_rng"),
        )
        self.context.cards_run += 1
        self._submit_achievement_event("card_resolved", {"card_id": card.card_id, "tier": card.tier})
        self._record_card_combo(card.card_id)

    def _record_card_combo(self, card_id: str) -> None:
        for combo_id, cfg in CARD_COMBO_SETS.items():
            if card_id not in cfg["cards"]:
                continue
            self.card_combo_counts[combo_id] = self.card_combo_counts.get(combo_id, 0) + 1
            if self.card_combo_counts[combo_id] >= 3 and combo_id not in self.card_combo_unlocked:
                self.card_combo_unlocked.add(combo_id)
                self._apply_combo_bonus(combo_id, cfg)
            return

    def _apply_combo_bonus(self, combo_id: str, cfg: dict) -> None:
        effects = cfg.get("effects", {})
        if effects.get("dmg_pct"):
            value = float(effects["dmg_pct"])
            self.player.growth.dmg_pct_bonus += value
            for weapon in self.weapon_sys.stack:
                weapon.dmg_pct_bonus += value
        if effects.get("aspd_pct"):
            value = float(effects["aspd_pct"])
            self.player.growth.aspd_pct_bonus += value
            for weapon in self.weapon_sys.stack:
                weapon.aspd_pct_bonus += value
        if effects.get("move_speed_pct"):
            self.player.growth.move_speed_pct += float(effects["move_speed_pct"])
        if effects.get("max_hp_flat"):
            delta = float(effects["max_hp_flat"])
            self.player.base_max_hp += delta
            self.player.current_hp = min(self.player.base_max_hp, self.player.current_hp + delta)
        if effects.get("armor_flat"):
            self.player.base_armor += float(effects["armor_flat"])
            self.player.current_armor = self.player.base_armor
        if effects.get("range_pct"):
            value = float(effects["range_pct"])
            self.player.growth.range_pct_bonus += value
            for weapon in self.weapon_sys.stack:
                weapon.range_pct_bonus += value
        if effects.get("penetration") and self.weapon_sys.active is not None:
            self.weapon_sys.active.penetration_bonus += int(effects["penetration"])
        self.last_combo_notice = {"combo_id": combo_id, "name": cfg["name"], "bonus": cfg["bonus"], "time": self.timer.run_time}
        self.event_bus.publish(self._e("card_combo_completed", self.last_combo_notice))

    def _apply_card_effect(self, card_id: str, cfg: dict) -> None:
        """按效果配置应用到玩家/武器。"""
        if self.weapon_sys.active is None:
            return
        active = self.weapon_sys.active
        for eff in cfg.get("effects", []):
            kind = eff.get("type")
            if kind == "dmg_pct":
                if cfg.get("applies_to_weapon") == "active":
                    active.dmg_pct_bonus += float(eff["value"])
                else:
                    self.player.growth.dmg_pct_bonus += float(eff["value"])
                    for weapon in self.weapon_sys.stack:
                        weapon.dmg_pct_bonus += float(eff["value"])
            elif kind == "crit_chance_bonus":
                value = float(eff["value"])
                if cfg.get("applies_to_weapon") == "active":
                    active.crit_chance_bonus += value
                else:
                    self.player.growth.crit_chance_bonus += value
                    for weapon in self.weapon_sys.stack:
                        weapon.crit_chance_bonus += value
            elif kind == "crit_multiplier_bonus":
                value = float(eff["value"])
                if cfg.get("applies_to_weapon") == "active":
                    active.crit_multiplier_bonus += value
                else:
                    self.player.growth.crit_multiplier_bonus += value
                    for weapon in self.weapon_sys.stack:
                        weapon.crit_multiplier_bonus += value
            elif kind == "aspd_pct":
                if cfg.get("applies_to_weapon") == "active":
                    active.aspd_pct_bonus += float(eff["value"])
                else:
                    self.player.growth.aspd_pct_bonus += float(eff["value"])
                    for weapon in self.weapon_sys.stack:
                        weapon.aspd_pct_bonus += float(eff["value"])
            elif kind == "range_pct":
                if cfg.get("applies_to_weapon") == "active":
                    active.range_pct_bonus += float(eff["value"])
                else:
                    self.player.growth.range_pct_bonus += float(eff["value"])
                    for weapon in self.weapon_sys.stack:
                        weapon.range_pct_bonus += float(eff["value"])
            elif kind == "arc_deg":
                self.player.growth.arc_deg_bonus += float(eff["value"])
                for weapon in self.weapon_sys.stack:
                    weapon.arc_deg_bonus += float(eff["value"])
            elif kind == "tol_deg":
                if cfg.get("applies_to_weapon") == "active":
                    active.tol_deg_bonus += float(eff["value"])
                else:
                    self.player.growth.tol_deg_bonus += float(eff["value"])
                    for weapon in self.weapon_sys.stack:
                        weapon.tol_deg_bonus += float(eff["value"])
            elif kind == "max_hp_flat":
                eff_hp = effective_stats(self.player)
                delta = float(eff["value"])
                self.player.base_max_hp += delta
                self.player.current_hp = min(self.player.base_max_hp, self.player.current_hp + delta)
            elif kind == "current_hp_flat":
                self.player.current_hp = min(self.player.base_max_hp, self.player.current_hp + float(eff["value"]))
            elif kind == "shield_flat":
                self.player.current_shield = min(self.player.max_shield + self.player.growth.max_shield_extra, self.player.current_shield + float(eff["value"]))
            elif kind == "pickup_radius_pct":
                self.player.growth.pickup_radius_pct += float(eff["value"])
            elif kind == "armor_flat":
                self.player.base_armor += float(eff["value"])
            elif kind == "move_speed_pct":
                self.player.growth.move_speed_pct += float(eff["value"])
            elif kind == "penetration":
                active.penetration_bonus += int(eff["value"])
            elif kind == "xp_gain_pct":
                self.level_sys.xp_gain_pct += float(eff["value"])
            elif kind == "max_shield_flat":
                self.player.growth.max_shield_extra += float(eff["value"])
            elif kind == "shield_regen_unlocked":
                self.player.growth.shield_regen_rate = max(self.player.growth.shield_regen_rate, float(eff.get("rate", 6.0)))
            elif kind == "low_hp_atk_pct":
                self.player.growth.low_hp_atk_pct = max(self.player.growth.low_hp_atk_pct, float(eff["value"]))
                self.player.growth.low_hp_threshold = float(eff.get("threshold", 0.35))
            elif kind == "low_hp_move_pct":
                self.player.growth.low_hp_move_pct = max(self.player.growth.low_hp_move_pct, float(eff["value"]))
                self.player.growth.low_hp_threshold = float(eff.get("threshold", 0.35))
            elif kind == "extra_projectile":
                cap = active.extra_proj_capped_at
                n = min(cap, active.extra_projectiles + int(eff["value"]))
                extra = active.extra_projectiles + int(eff["value"]) - n
                active.extra_projectiles = n
                # 超出的层数转为攻速加成
                if extra > 0:
                    active.aspd_pct_bonus += 0.08 * extra
                active.extra_projectile_dmg_share = float(eff.get("dmg_share", 0.45))
            elif kind == "active_weapon_level_up":
                active.level = min(active.max_level, active.level + 1)
                active.base_damage_boost += 4
                if active.level >= active.max_level and not active.breakthrough_unlocked:
                    active.breakthrough_unlocked = True
                    active.base_damage_boost += 8
                    active.aspd_pct_bonus += 0.06
                    self.event_bus.publish(self._e("weapon_breakthrough", {
                        "weapon_id": active.weapon_id,
                        "level": active.level,
                        "rarity": active.rarity,
                    }))
                # 同步武器遍历
                for w in self.weapon_sys.stack:
                    if w.weapon_id == active.weapon_id:
                        w.level = active.level
                        w.base_damage_boost = active.base_damage_boost
                        w.breakthrough_unlocked = active.breakthrough_unlocked
                        w.aspd_pct_bonus = active.aspd_pct_bonus
                self._refresh_weapon_synergies()
            elif kind == "gain_random_weapon":
                # 抽一把新武器（按 LIFO）
                inventory = list(self.bundle.weapons.keys())
                # 不重复当前持有的
                cur = {w.weapon_id for w in self.weapon_sys.stack}
                cands = [w for w in inventory if w not in cur] or inventory
                self.context.rng.get("weapon_pick_rng").shuffle(cands)
                new_w_cfg = self.bundle.weapons[cands[0]]
                new_weapon, _, _ = self.weapon_sys.gain_weapon(new_w_cfg)
                self._inherit_global_weapon_growth(new_weapon)
                self._apply_weapon_metadata()
                self.event_bus.publish(self._e("weapon_added", {"weapon_id": new_w_cfg["id"]}))
            elif kind == "gain_weapon":
                weapon_id = eff.get("weapon_id")
                new_w_cfg = self.bundle.weapons.get(weapon_id)
                if new_w_cfg is not None:
                    new_weapon, _, _ = self.weapon_sys.gain_weapon(new_w_cfg)
                    self._inherit_global_weapon_growth(new_weapon)
                    self._apply_weapon_metadata()
                    self.event_bus.publish(self._e("weapon_added", {"weapon_id": weapon_id}))
            elif kind == "prism_flare":
                self.player.growth.prism_flare += int(eff.get("count", 2))
                self.player.growth.prism_flare_dmg_share = float(eff["value"])
            elif kind == "turn_speed_pct":
                self.player.growth.move_speed_pct += float(eff["value"])  # 没有专门的转向
            elif kind == "break_invuln":
                self.player.growth.break_invuln_duration = float(eff["duration"])
                self.player.growth.break_invuln_cooldown = float(eff["cooldown"])
            elif kind == "max_hp_pct":
                self.player.extra_max_hp_pct += float(eff["value"])

    def _inherit_global_weapon_growth(self, weapon) -> None:
        """让新武器继承此前获得的全局攻击、攻速、射程与暴击成长。"""
        weapon.dmg_pct_bonus += self.player.growth.dmg_pct_bonus
        weapon.aspd_pct_bonus += self.player.growth.aspd_pct_bonus
        weapon.range_pct_bonus += self.player.growth.range_pct_bonus
        weapon.arc_deg_bonus += self.player.growth.arc_deg_bonus
        weapon.tol_deg_bonus += self.player.growth.tol_deg_bonus
        weapon.crit_chance_bonus += self.player.growth.crit_chance_bonus
        weapon.crit_multiplier_bonus += self.player.growth.crit_multiplier_bonus

    def _apply_passive_growth(self) -> None:
        # 每整分钟应用一次被动成长
        minute = int(self.timer.run_time // 60)
        if minute > self.context.last_passive_minute:
            for _ in range(minute - self.context.last_passive_minute):
                self._apply_one_passive_minute()
            self.context.last_passive_minute = minute

    def _apply_one_passive_minute(self) -> None:
        """每整分钟玩家被动成长：

        - 最大生命 ×1.02；
        - 攻击倍率 ×1.015；
        - 护甲 +0.5。
        """
        eff = effective_stats(self.player)
        old_hp = eff["max_hp"]
        self.player.base_max_hp = self.player.base_max_hp * 1.02
        delta = self.player.base_max_hp - old_hp
        self.player.current_hp = min(self.player.base_max_hp, self.player.current_hp + delta)
        self.player.base_armor += 0.5
        # 仅作用基础值；具体卡牌加成仍由卡牌结算

    # ========================================================================
    # 超级怪兽
    # ========================================================================

    def _step_super_warning(self, dt: float) -> None:
        if self.super_director.warning_left > 0:
            self.super_director.warning_left -= dt
            if self.super_director.warning_left <= 0:
                # 转换为实际生成
                self._spawn_super_enemy_now()
                self.state_machine.request(RUNNING)

    def _spawn_super_enemy_now(self) -> None:
        # 选用最近一个普通敌人原型的当前快照
        ref_cfg = self.bundle.enemies["spinner_chaser"]
        # 取 mods
        if self.context.mode == RunMode.ENDLESS:
            stage_cfg = self.bundle.stages["endless"]
        else:
            stage_cfg = self.bundle.stages.get(f"stage_{self.context.stage_index}", self.bundle.stages["stage_1"])
        mods = stage_modifiers(
            stage_index=self.context.stage_index,
            endless_cycle=self.context.endless_cycle,
            elapsed_minutes=int(self.timer.stage_time // 60),
            stage_cfg=stage_cfg,
        )
        snap = enemy_spawned_snapshot(ref_cfg, mods)
        # 找位置：8 扇区边缘，距玩家至少 650
        pos = self._pick_super_spawn_position()
        if pos is None:
            self.super_director.queued += 1
            return
        self.super_director.spawn(
            run_context=self.context,
            reference_enemy_cfg=ref_cfg,
            reference_snapshot=snap,
            reference_archetype=ref_cfg["archetype"],
            position=pos,
        )
        se = self.super_director.active
        if se is not None:
            # 加入 spawn_director.enemies 用于渲染与命中
            self.spawn_director.enemies.append(se.enemy)

    def _pick_super_spawn_position(self) -> tuple[float, float] | None:
        # 8 扇区
        dirs = [(0,1), (1,1), (1,0), (1,-1), (0,-1), (-1,-1), (-1,0), (-1,1)]
        rng = self.context.rng.get("super_rng")
        rng.shuffle(dirs)
        for dx, dy in dirs:
            for t in (640, 720, 800):
                x = self.player.position[0] + dx * t
                y = self.player.position[1] + dy * t
                x = max(self.bounds.min_x + 24, min(self.bounds.max_x - 24, x))
                y = max(self.bounds.min_y + 24, min(self.bounds.max_y - 24, y))
                if math.hypot(x - self.player.position[0], y - self.player.position[1]) >= 650:
                    return (x, y)
        return None

    def _step_super_enemy(self, dt: float, candidates: list[TargetCandidate]) -> None:
        # 每个 RUNNING tick 推进一次：在世界清理过敌人、检查警告触发后调用
        if not (self.state_machine.current == RUNNING):
            return
        sd = self.super_director
        if sd.cooldown > 0:
            sd.cooldown -= dt
        if sd.can_warn(self.context) and sd.queued > 0:
            sd.start_warning(duration=1.0)
            self.event_bus.publish(self._e("super_warning_started", {"queued": sd.queued}))
            self.state_machine.request(SUPER_WARNING)
            return
        if sd.active is not None:
            se = sd.active
            e = se.enemy
            if e.current_hp <= 0:
                return
            if se.broken_left > 0:
                se.broken_left = max(0.0, se.broken_left - dt)
            hp_ratio = e.current_hp / max(1.0, e.max_hp)
            new_phase = 3 if hp_ratio <= 0.33 else 2 if hp_ratio <= 0.66 else 1
            if new_phase != se.phase:
                se.phase = new_phase
                se.weakpoint_angle = self.context.rng.get("super_rng").uniform(0, math.tau)
                self.event_bus.publish(self._e("boss_phase_changed", {"phase": se.phase, "hp_ratio": hp_ratio}))
            if not se.enraged and e.current_hp <= e.max_hp * 0.5:
                se.enraged = True
                self.event_bus.publish(self._e("super_enraged", {"hp": e.current_hp, "max_hp": e.max_hp}))
            if se.skill_windup_left <= 0 and se.skill_active_left <= 0 and se.skill_recovery_left <= 0:
                # 选择下一个技能
                chosen = sd.choose_next_skill(se, self.context.rng.get("super_rng"))
                se.current_skill = chosen
                se.skill_fired = False
                se.skill_wave_index = 0
                se.skill_wave_timer = 0.0
                se.skill_aim_angle = math.atan2(
                    self.player.position[1] - e.position[1],
                    self.player.position[0] - e.position[0],
                )
                # 取基准 windup，但不低于 0.6
                base_wu = 0.9 if chosen == SuperSkill.FIVE_FAN else \
                          1.1 if chosen == SuperSkill.THREE_BOMB else \
                          1.0 if chosen == SuperSkill.GAP_RING else \
                          0.8 if chosen == SuperSkill.LOCKED_DASH else \
                          1.18 if chosen == SuperSkill.TRI_LASER else \
                          1.0 if chosen == SuperSkill.VOID_TIDAL else 1.2
                se.skill_windup_left = max(0.45 if se.enraged else 0.6, base_wu * (0.68 if se.enraged else 1.0))
                self.event_bus.publish(self._e("super_skill_started", {"skill": chosen.value, "windup": se.skill_windup_left}))
            elif se.skill_windup_left > 0:
                # 锁定方位 / 圆心
                se.skill_windup_left -= dt
                # 暂停期内 process 不打伤害
                if se.skill_windup_left <= 0:
                    # 跳到 active
                    se.skill_active_left = {
                        SuperSkill.FIVE_FAN: 1.05,
                        SuperSkill.GAP_RING: 1.15,
                        SuperSkill.EXPAND_RING: 1.35,
                        SuperSkill.THREE_BOMB: 0.55,
                        SuperSkill.LOCKED_DASH: 0.72,
                        SuperSkill.TRI_LASER: 0.90,
                        SuperSkill.VOID_TIDAL: 1.18,
                    }.get(se.current_skill, 0.7)
                    self._fire_super_skill(se)
            elif se.skill_active_left > 0:
                if se.current_skill == SuperSkill.LOCKED_DASH:
                    dx, dy = se.dash_direction
                    e.position = clamp_to_playable_bounds(
                        (e.position[0] + dx * (980 if se.enraged else 820) * dt,
                         e.position[1] + dy * (980 if se.enraged else 820) * dt),
                        self.bounds, radius=e.collision_radius,
                    )
                elif se.current_skill in (SuperSkill.FIVE_FAN, SuperSkill.GAP_RING, SuperSkill.EXPAND_RING, SuperSkill.TRI_LASER, SuperSkill.VOID_TIDAL):
                    se.skill_wave_timer -= dt
                    if se.skill_wave_timer <= 0:
                        limits = {
                            SuperSkill.FIVE_FAN: 5 if se.enraged else 4,
                            SuperSkill.GAP_RING: 3 if se.enraged else 2,
                            SuperSkill.EXPAND_RING: 4 if se.enraged else 3,
                            SuperSkill.TRI_LASER: 3 if se.enraged else 2,
                            SuperSkill.VOID_TIDAL: 4 if se.enraged else 3,
                        }
                        if se.skill_wave_index < limits[se.current_skill]:
                            self._fire_super_skill_wave(se)
                se.skill_active_left -= dt
                if se.skill_active_left <= 0:
                    sd.on_skill_used(se, se.current_skill or SuperSkill.FIVE_FAN)
                    se.skill_recovery_left = 0.30 if se.enraged else 0.55
                    se.current_skill = None
            elif se.skill_recovery_left > 0:
                se.skill_recovery_left = max(0.0, se.skill_recovery_left - dt)
                if se.broken_left <= 0 and self.player.status == PlayerStatus.ACTIVE:
                    dx = self.player.position[0] - e.position[0]
                    dy = self.player.position[1] - e.position[1]
                    distance = math.hypot(dx, dy)
                    if distance > 260.0:
                        travel = min(e.move_speed * dt, distance - 260.0)
                        e.position = clamp_to_playable_bounds(
                            (e.position[0] + dx / distance * travel,
                             e.position[1] + dy / distance * travel),
                            self.bounds, radius=e.collision_radius,
                        )
            # 出生保护
            if se.spawn_protect_left > 0:
                se.spawn_protect_left = max(0, se.spawn_protect_left - dt)

    def _emit_super_bullet(
        self, e: Enemy, angle: float, *, speed: float, radius: float,
        damage_scale: float = 0.55, visual_kind: str = "boss_orb",
    ) -> None:
        target = (e.position[0] + math.cos(angle) * 500, e.position[1] + math.sin(angle) * 500)
        self.projectile_sys.emit(
            owner=e.entity_id, faction="enemy", origin=e.position, target_pos=target,
            damage=e.contact_damage * damage_scale, radius=radius, speed=speed,
            lifetime=3.2, penetration=1, crit_chance=0, crit_multiplier=1,
            crit_roll=0, weapon_id=None, source_id=e.entity_id, now=self.timer.run_time,
            attack_angle=angle, visual_kind=visual_kind,
        )

    def _fire_super_skill(self, se: SuperEnemy) -> None:
        """前摇结束后启动技能；弹幕技能会在 active 阶段连续释放多波。"""
        if se.skill_fired or se.current_skill is None:
            return
        se.skill_fired = True
        e = se.enemy
        aim = math.atan2(self.player.position[1] - e.position[1], self.player.position[0] - e.position[0])
        skill = se.current_skill
        if skill in (SuperSkill.FIVE_FAN, SuperSkill.GAP_RING, SuperSkill.EXPAND_RING, SuperSkill.TRI_LASER, SuperSkill.VOID_TIDAL):
            self._fire_super_skill_wave(se)
        elif skill == SuperSkill.THREE_BOMB:
            for offset in (-150, 0, 150):
                perp = aim + math.pi / 2
                pos = (
                    self.player.position[0] + math.cos(perp) * offset,
                    self.player.position[1] + math.sin(perp) * offset,
                )
                self.drop_sys.bombs.append(HazardBomb(
                    entity_id=f"boss_bomb_{len(self.drop_sys.bombs)}_{int(self.timer.run_time*1000)}",
                    position=clamp_to_playable_bounds(pos, self.bounds, 24), radius=145,
                    base_damage=e.contact_damage * 0.8, spawn_time=self.timer.run_time,
                    arm_delay=0.55, armed_at=self.timer.run_time + 0.55, lifetime=2.2,
                ))
        elif skill == SuperSkill.LOCKED_DASH:
            d = math.hypot(self.player.position[0] - e.position[0], self.player.position[1] - e.position[1]) or 1
            se.dash_direction = (
                (self.player.position[0] - e.position[0]) / d,
                (self.player.position[1] - e.position[1]) / d,
            )

    def _fire_super_skill_wave(self, se: SuperEnemy) -> None:
        """释放一波弹幕；每波重新取玩家方位，但每颗子弹发射后均不追踪。"""
        if se.current_skill is None:
            return
        e = se.enemy
        aim = math.atan2(self.player.position[1] - e.position[1], self.player.position[0] - e.position[0])
        wave = se.skill_wave_index
        speed_mul = 1.22 if se.enraged else 1.0
        if se.current_skill == SuperSkill.FIVE_FAN:
            count = 15 if se.enraged else 13
            spread = 100
            for i in range(count):
                offset = -spread / 2 + spread * i / max(1, count - 1)
                self._emit_super_bullet(e, aim + math.radians(offset), speed=430 * speed_mul, radius=9)
            se.skill_wave_timer = 0.18 if se.enraged else 0.24
        elif se.current_skill == SuperSkill.GAP_RING:
            count = 34 if se.enraged else 30
            phase = wave * math.radians(7)
            for i in range(count):
                a = math.tau * i / count + phase
                diff = (a - aim + math.pi) % math.tau - math.pi
                if abs(diff) < math.radians(17):
                    continue
                self._emit_super_bullet(e, a, speed=345 * speed_mul, radius=8, damage_scale=0.48)
            se.skill_wave_timer = 0.30 if se.enraged else 0.42
        elif se.current_skill == SuperSkill.EXPAND_RING:
            count = 38 if se.enraged else 32
            phase = wave * math.pi / count
            for i in range(count):
                self._emit_super_bullet(
                    e, math.tau * i / count + phase,
                    speed=(245 + wave * 28) * speed_mul, radius=10, damage_scale=0.42,
                )
            se.skill_wave_timer = 0.27 if se.enraged else 0.38
        elif se.current_skill == SuperSkill.TRI_LASER:
            # Three predictable energy lanes. Each volley adds a slight rotation,
            # leaving a readable dodge gap while preventing stationary camping.
            spread = 24 if se.enraged else 17
            count = 5 if se.enraged and se.phase >= 3 else 3
            rotation = math.radians((wave - 0.5) * (7 if se.enraged else 5))
            offsets = [
                -spread + 2 * spread * i / max(1, count - 1)
                for i in range(count)
            ]
            for offset in offsets:
                self._emit_super_bullet(
                    e, se.skill_aim_angle + rotation + math.radians(offset),
                    speed=(600 if se.enraged else 520), radius=11,
                    damage_scale=0.36 if se.enraged else 0.32,
                    visual_kind="boss_lattice",
                )
            se.skill_wave_timer = 0.30 if se.enraged else 0.38
        elif se.current_skill == SuperSkill.VOID_TIDAL:
            # 弹幕围绕中心向外扩散，每波旋转安全缺口；预警角度与实弹采用同一算法。
            count = 32 if se.enraged else 28
            gap_center = se.skill_aim_angle + math.radians(wave * (18 if se.enraged else 24))
            gap_half_angle = math.radians(24 if se.enraged else 29)
            phase = wave * math.pi / count
            for i in range(count):
                angle = math.tau * i / count + phase
                difference = (angle - gap_center + math.pi) % math.tau - math.pi
                if abs(difference) <= gap_half_angle:
                    continue
                self._emit_super_bullet(
                    e, angle, speed=(320 if se.enraged else 290) * speed_mul,
                    radius=8, damage_scale=0.36, visual_kind="boss_tidal",
                )
            se.skill_wave_timer = 0.28 if se.enraged else 0.36
        se.skill_wave_index += 1

    # ========================================================================
    # 投射物碰撞
    # ========================================================================

    def _projectile_collisions(self) -> None:
        # 子报告 P1-3：把 O(P×E) 嵌套降到 P + E；
        # 用 cell hash：每个 enemy 落到 (x//CELL) (y//CELL) 索引，projectile 只查所在 cell + 8 邻居。
        enemies = self.spawn_director.enemies
        if not enemies:
            # 无敌人也得跑 enemy->player 检测
            self._projectile_collision_player_collision([])
            return
        cell_size = max(64.0, max(e.collision_radius for e in enemies) * 2.0)
        cells: dict[tuple[int, int], list] = {}
        for e in enemies:
            if e.state in (EnemyState.DYING, EnemyState.DEAD):
                continue
            key = (int(e.position[0] // cell_size), int(e.position[1] // cell_size))
            cells.setdefault(key, []).append(e)
        # 玩家投射物 -> 敌人
        for p in list(self.projectile_sys.projectiles):
            if not p.alive or p.faction != "player":
                continue
            # 命中半径
            hit_radius = p.splash_radius if p.is_melee and p.splash_radius > 0 else p.radius
            scan = hit_radius + max(0.0, cell_size)
            cx = int(p.position[0] // cell_size)
            cy = int(p.position[1] // cell_size)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    cell = cells.get((cx + dx, cy + dy))
                    if cell is None:
                        continue
                    for e in cell:
                        if e.entity_id in p.targets_hit:
                            continue
                        edx = e.position[0] - p.position[0]
                        edy = e.position[1] - p.position[1]
                        d = math.hypot(edx, edy)
                        in_arc = True
                        if p.is_melee and p.attack_arc_deg < 359:
                            target_angle = math.atan2(edy, edx)
                            adiff = (target_angle - p.attack_angle + math.pi) % (2 * math.pi) - math.pi
                            in_arc = abs(math.degrees(adiff)) <= p.attack_arc_deg * 0.5
                        if d < e.collision_radius + hit_radius and in_arc:
                            self._resolve_projectile_hit(p, e, d)
                            if not p.is_melee:
                                break
                    if not p.is_melee and not p.alive:
                        break
        self._projectile_collision_player_collision(enemies)

    def _resolve_projectile_hit(self, p, e, _d_unused: float = 0.0) -> None:
        cap = self._reference_monster_capped_damage()
        cap_active = True
        target_vuln = self._boss_vulnerability_pct(e, p)
        res, _ = self.projectile_sys.apply_to_target(
            p,
            target_id=e.entity_id,
            target_max_shield=0,
            target_current_shield=0,
            target_alive=True,
            target_faction="enemy",
            target_armor=e.armor,
            target_vuln_pct=target_vuln,
            target_max_hp=e.max_hp,
            attack_cap=cap,
            attack_cap_active=cap_active,
        )
        e.current_hp -= res.hp_damage
        p.targets_hit.add(e.entity_id)
        if e.entity_id in p.targets_hit and p.penetration_left <= 1:
            p.alive = False
        else:
            p.penetration_left = max(0, p.penetration_left - 1)
        self.event_bus.publish(self._e("damage_applied", {
            "source_id": p.entity_id,
            "target_id": e.entity_id,
            "raw": p.damage,
            "final": res.final_damage,
            "overflow": res.overflow,
            "crit": res.crit,
            "is_super": e.is_super,
            "weakpoint": target_vuln > 0,
        }))
        self.last_damage_numbers.append({
            "amount": res.final_damage,
            "crit": res.crit,
            "position": list(e.position),
            "time": self.timer.run_time,
        })
        self.last_damage_numbers = self.last_damage_numbers[-32:]
        e.last_hit_weapon_id = p.weapon_id
        e.last_hit_source_id = p.source_id
        self._apply_on_hit_affix_feedback(e, p, res.final_damage)
        self._trigger_weapon_synergies_on_hit(p, e, res.final_damage)

    def _projectile_collision_player_collision(self, _enemies_unused) -> None:
        # 敌人投射物 → 玩家
        for p in list(self.projectile_sys.projectiles):
            if not p.alive or p.faction != "enemy":
                continue
            d = math.hypot(self.player.position[0] - p.position[0], self.player.position[1] - p.position[1])
            if d < 22 + p.radius:
                self._damage_player(p.damage, source_id=p.entity_id)
                p.alive = False

    def _boss_vulnerability_pct(self, e: Enemy, p) -> float:
        if not e.is_super or self.super_director.active is None or self.super_director.active.enemy is not e:
            return 0.0
        se = self.super_director.active
        if se.broken_left > 0:
            return 0.45
        dx = p.position[0] - e.position[0]
        dy = p.position[1] - e.position[1]
        hit_angle = math.atan2(dy, dx)
        diff = (hit_angle - se.weakpoint_angle + math.pi) % math.tau - math.pi
        if abs(diff) <= math.radians(36):
            se.break_gauge += 18.0
            if se.break_gauge >= se.break_gauge_max:
                se.break_gauge = 0.0
                se.broken_left = 3.0
                self.event_bus.publish(self._e("boss_broken", {"duration": se.broken_left}))
            return 0.25
        return 0.0

    def _apply_on_hit_affix_feedback(self, e: Enemy, p, final_damage: float) -> None:
        if "reflect" in e.elite_affixes and not p.is_melee:
            reflected = max(1.0, final_damage * 0.06)
            self._damage_player(reflected, source_id=f"reflect:{e.entity_id}")
        if "ice_armor" in e.elite_affixes:
            self.player.growth.move_speed_pct = max(self.player.growth.move_speed_pct - 0.004, -0.22)

    def _trigger_weapon_synergies_on_hit(self, p, e: Enemy, final_damage: float) -> None:
        wid = p.weapon_id or ""
        rng = self.context.rng.get("crit_rng")
        if "steam_burst" in self.weapon_synergies_active and wid in WEAPON_SYNERGIES["steam_burst"]["weapons"]:
            if rng.chance(0.24):
                self._deal_area_damage(e.position, radius=115, damage=max(12.0, final_damage * 0.48), source_id="combo:steam_burst")
        if "thunder_chain" in self.weapon_synergies_active and wid in WEAPON_SYNERGIES["thunder_chain"]["weapons"]:
            if rng.chance(0.30):
                self._deal_chain_damage(e, jumps=3, radius=260, damage=max(8.0, final_damage * 0.42), source_id="combo:thunder_chain")
        if "focused_lattice" in self.weapon_synergies_active and wid in WEAPON_SYNERGIES["focused_lattice"]["weapons"]:
            st = self.weapon_synergy_state.setdefault("focused_lattice", {"target": None, "stacks": 0})
            if st.get("target") == e.entity_id:
                st["stacks"] = min(6, int(st.get("stacks", 0)) + 1)
            else:
                st["target"] = e.entity_id
                st["stacks"] = 1
            bonus = final_damage * 0.10 * int(st["stacks"])
            if bonus > 0:
                e.current_hp -= bonus
                self.event_bus.publish(self._e("weapon_synergy_triggered", {
                    "combo_id": "focused_lattice", "name": "聚焦光网", "target_id": e.entity_id, "damage": bonus, "stacks": st["stacks"],
                }))
        if "earth_shock" in self.weapon_synergies_active and wid in WEAPON_SYNERGIES["earth_shock"]["weapons"]:
            if p.is_melee and rng.chance(0.28):
                self._deal_area_damage(e.position, radius=165, damage=max(16.0, final_damage * 0.36), source_id="combo:earth_shock")

    def _deal_area_damage(self, center: tuple[float, float], *, radius: float, damage: float, source_id: str) -> int:
        hit = 0
        for other in self.spawn_director.enemies:
            if other.state in (EnemyState.DYING, EnemyState.DEAD) or other.current_hp <= 0:
                continue
            if math.hypot(other.position[0] - center[0], other.position[1] - center[1]) <= radius + other.collision_radius:
                other.current_hp -= damage
                hit += 1
                self.event_bus.publish(self._e("damage_applied", {
                    "source_id": source_id, "target_id": other.entity_id, "raw": damage, "final": damage,
                    "overflow": 0, "crit": False, "is_super": other.is_super,
                }))
        if hit:
            self.event_bus.publish(self._e("weapon_synergy_triggered", {
                "combo_id": source_id.split(":", 1)[-1], "hit": hit, "damage": damage, "position": list(center),
            }))
        return hit

    def _deal_chain_damage(self, first: Enemy, *, jumps: int, radius: float, damage: float, source_id: str) -> int:
        hit_ids = {first.entity_id}
        current = first
        hit = 0
        for _ in range(jumps):
            candidates = [
                e for e in self.spawn_director.enemies
                if e.entity_id not in hit_ids and e.state not in (EnemyState.DYING, EnemyState.DEAD)
                and e.current_hp > 0 and math.hypot(e.position[0] - current.position[0], e.position[1] - current.position[1]) <= radius
            ]
            if not candidates:
                break
            candidates.sort(key=lambda x: math.hypot(x.position[0] - current.position[0], x.position[1] - current.position[1]))
            current = candidates[0]
            current.current_hp -= damage
            hit_ids.add(current.entity_id)
            hit += 1
            self.event_bus.publish(self._e("damage_applied", {
                "source_id": source_id, "target_id": current.entity_id, "raw": damage, "final": damage,
                "overflow": 0, "crit": False, "is_super": current.is_super,
            }))
        if hit:
            self.event_bus.publish(self._e("weapon_synergy_triggered", {
                "combo_id": "thunder_chain", "name": "雷链", "jumps": hit, "damage": damage,
            }))
        return hit

    def _on_damage_applied_for_overflow(self, event) -> None:
        """累积玩家攻击被 50% 上限夹紧后的溢出，下一次攻击时加成回去。

        区分逻辑：
        - ``to_player=True`` 是敌人攻击玩家的伤害事件，不累计。
        - 其余视为玩家攻击事件，按 ``overflow`` 字段累加。
        """
        try:
            payload = event.payload
        except AttributeError:
            return
        if payload.get("to_player"):
            return
        overflow = float(payload.get("overflow", 0) or 0)
        if overflow > 0:
            self.card_sys.attack_overflow += overflow
            self.player.overflow_attack_power += overflow

    def _reference_monster_capped_damage(self) -> float:
        """参考怪兽当前有效生命 × 0.5，按《抽卡系统》§9。"""
        if self.context.mode == RunMode.ENDLESS:
            stage_cfg = self.bundle.stages["endless"]
        else:
            stage_cfg = self.bundle.stages.get(f"stage_{self.context.stage_index}", self.bundle.stages["stage_1"])
        mods = stage_modifiers(
            stage_index=self.context.stage_index,
            endless_cycle=self.context.endless_cycle,
            elapsed_minutes=int(self.timer.stage_time // 60),
            stage_cfg=stage_cfg,
        )
        snap = enemy_spawned_snapshot(self.reference_monster_def, mods)
        eff_hp = snap["max_hp"] * (1.0 + snap["armor"] / 100.0)
        return eff_hp * 0.5

    # ========================================================================
    # 提交成就事件 + 持久化
    # ========================================================================

    def _submit_achievement_event(self, event_type: str, payload: dict) -> None:
        self.ach_sys.submit_event(event_type=event_type, payload=payload)

    def _e(self, type_: str, payload: dict):
        from .core.event_bus import Event
        return Event(
            id=f"{type_}-{self.timer.run_time}-{len(self.event_bus._history)}",
            type=type_,
            payload=payload,
            timestamp=self.timer.run_time,
        )

    def _persist_profile(self) -> None:
        if self.profile_path is None:
            return
        # 累计统计写到 profile
        self.profile.updated_at = time.time()
        self.profile.unlocked_achievements = dict(self.ach_sys.unlocked)
        # 累计统计从 lifetime 字段
        self.profile.lifetime_score = int(self.ach_sys.stats_lifetime.get("lifetime_score", 0))
        self.profile.lifetime_kills = int(self.ach_sys.stats_lifetime.get("lifetime_kills", 0))
        self.profile.super_kills = int(self.ach_sys.stats_lifetime.get("super_kills_lifetime", 0))
        self.profile.bomb_dodges = int(self.ach_sys.stats_lifetime.get("bomb_dodges_lifetime", 0))
        self.profile.endless_max_cycle = max(self.profile.endless_max_cycle, self.context.endless_cycle)
        self.profile.last_preset_id = self.context.preset_id
        self.profile.account_name = getattr(self.profile, "account_name", self.profile.profile_id)
        self.profile.selected_permanent_weapon = self.selected_starting_weapon_id
        self.profile.selected_starting_weapons = list(self.selected_starting_weapon_ids)
        self.profile.selected_equipment = list(self.selected_equipment_ids)
        save_profile(self.profile, self.profile_path)

    def _record_run_summary(self, result: str) -> None:
        if self._run_recorded:
            return
        self._run_recorded = True
        skill_name = ACTIVE_SKILLS.get(self.active_skill_id, ACTIVE_SKILLS["bomb_trap"])["name"]
        preset_name = " + ".join(
            self.bundle.weapons.get(wid, {}).get("display_name", wid)
            for wid in self.selected_starting_weapon_ids
        ) or "默认武器"
        unlocked = [
            k for k, v in self.ach_sys.unlocked.items()
            if bool(v)
        ]
        summary = {
            "ended_at": time.time(),
            "result": result,
            "mode": self.context.mode,
            "preset": preset_name,
            "skill": skill_name,
            "kills": int(self.context.kills_run),
            "score": int(self.context.run_score),
            "duration": float(self.timer.run_time),
            "cards": int(self.context.cards_run),
            "super_kills": int(self.context.super_kills_run),
            "achievements": unlocked[-8:],
            "skill_uses": int(self.active_skill_uses),
            "gold": int(self.run_gold_earned),
            "combos": list(self.card_combo_unlocked),
            "equipment": list(self.selected_equipment_ids),
        }
        runs = list(getattr(self.profile, "recent_runs_summary", []) or [])
        runs.insert(0, summary)
        self.profile.recent_runs_summary = runs[:30]

    # ========================================================================
    # 提示事件总线：UI 通知
    # ========================================================================

    def bus_publish_state_change(self, s) -> None:
        pass

    def submit_state_change_to_main_menu(self) -> None:
        self.state_machine.request(MAIN_MENU)
