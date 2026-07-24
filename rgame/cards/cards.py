"""抽卡系统。

按《抽卡系统》：

- 三关费用按递增公式；
- 无尽模式 800 分一次；
- 三选一 + 唯一刷新；
- 银 / 金 / 彩；
- 武器 LIFO；
- 满级武器 / 互斥 / 唯一过滤；
- 攻击 50% 上限追踪。
"""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..core.event_bus import Event, EventBus


# 抽卡费用公式（《抽卡系统》§2 常规关模式）
def campaign_card_cost(n: int) -> int:
    """第 n 次抽卡的费用（n 从 1 起）。"""
    if n <= 0:
        return 0
    return min(600 + 200 * (n - 1), 1400)


def endless_card_cost() -> int:
    return 800


class CardTier:
    SILVER = "silver"
    GOLD = "gold"
    COLOR = "color"


class CardRarity:
    BRONZE = "铜"
    SILVER = "银"
    GOLD = "金"


@dataclass
class Card:
    """一张卡的数据。"""

    card_id: str
    config: dict
    tier: str
    weight: float
    stackable: bool
    unique_per_run: bool
    applies_to_weapon: str | None = None  # None / "active" / "*" / 具体 id
    rarity_zh: str = "银"
    name_zh: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    effects: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "tier": self.tier,
            "rarity_zh": self.rarity_zh,
            "name_zh": self.name_zh,
            "tags": list(self.tags),
            "effects": list(self.effects),
            "stackable": self.stackable,
            "unique_per_run": self.unique_per_run,
            "applies_to_weapon": self.applies_to_weapon,
            "weight": self.weight,
        }


@dataclass
class CardOffer:
    """一次抽卡界面提供的 3 张卡。"""
    offer_seq: int
    cost: int
    cards: list[Card]
    refreshed: bool = False


class RarityFilter:
    ALL = "all"
    NO_COLOR = "no_color"


@dataclass
class CardSystem:
    """抽卡系统。

    持有权重表 / 卡池 / 已拥有的唯一卡集合。
    """

    bus: EventBus
    cards: dict[str, dict]            # 全部卡片配置（来自 cfg.cards）
    unlock_unique: set[str] = field(default_factory=set)
    owned_inventory: Counter = field(default_factory=Counter)
    pending_offers: int = 0
    offer_history: list[CardOffer] = field(default_factory=list)
    next_offer_seq: int = 1
    no_gold_or_color_offers_in_a_row: int = 0
    attack_overflow: float = 0.0
    overflow_history: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------------
    # 候选生成
    # ------------------------------------------------------------------
    def _normalize_weights(self, pool: list[Card]) -> list[float]:
        return [c.weight for c in pool]

    def _legal_pool(
        self,
        *,
        weapon_stack: list[str],
        active_weapon_id: str,
        weapon_levels: dict[str, int],
        active_weapon_max_level: int,
        filter: str = RarityFilter.ALL,
    ) -> list[Card]:
        """过滤非法候选。

        非法：
        - 满级武器升级；
        - 已拥有的唯一卡；
        - 互斥：备用 here 不展开；
        - 不可叠加且不可与已有同 ID：保留在池（金色 c_active_weapon_levelup 可叠加）；
        - 应用"无视关卡"过窄时由 filter 控制。
        """
        out: list[Card] = []
        for cid, cfg in self.cards.items():
            tier = cfg.get("tier", "silver")
            if filter == RarityFilter.NO_COLOR and tier == CardTier.COLOR:
                continue
            if cfg.get("unique_per_run") and cid in self.unlock_unique:
                continue
            # 武器升级针对激活武器满级
            if cid == "c_active_weapon_levelup":
                if (weapon_levels.get(active_weapon_id, 1) >= active_weapon_max_level):
                    continue
            out.append(Card(
                card_id=cid,
                config=cfg,
                tier=tier,
                weight=float(cfg.get("weight", 1)),
                stackable=bool(cfg.get("stackable", True)),
                unique_per_run=bool(cfg.get("unique_per_run", False)),
                applies_to_weapon=cfg.get("applies_to_weapon"),
                rarity_zh={CardTier.SILVER: "铜", CardTier.GOLD: "银", CardTier.COLOR: "金"}.get(tier, "铜"),
                name_zh=cfg.get("name_zh", cid),
                tags=tuple(cfg.get("tags", [])),
                effects=list(cfg.get("effects", [])),
            ))
        return out

    def generate_offer(
        self,
        *,
        weapon_stack: list[str],
        active_weapon_id: str,
        weapon_levels: dict[str, int],
        active_weapon_max_level: int = 8,
        rng=None,
        n: int = 3,
        filter: str = RarityFilter.ALL,
    ) -> CardOffer:
        pool = self._legal_pool(
            weapon_stack=weapon_stack,
            active_weapon_id=active_weapon_id,
            weapon_levels=weapon_levels,
            active_weapon_max_level=active_weapon_max_level,
            filter=filter,
        )
        if not pool:
            # 兜底：使用 filler
            pool = [
                Card(
                    card_id="c_filler_atk",
                    config=self.cards["c_filler_atk"],
                    tier="silver",
                    weight=1,
                    stackable=True,
                    unique_per_run=False,
                    rarity_zh="铜",
                    name_zh="细微改良",
                )
            ]
        # 加权不放回抽样：每次从临时池中按权重选 1 张，移除后再选，
        # 保证同一 offer 内 card_id 互不重复（CRD-001）。
        # 当 pool 不足 n 张时用 filler 兜底，且允许重复填补到 n。
        picks: list[Card] = []
        # 保底：连续 5 次都无金/彩 → 第 6 次至少 1 金或彩
        force_gold_or_color = self.no_gold_or_color_offers_in_a_row >= 5
        if len(pool) >= n:
            # 临时池：用索引访问，不修改原 pool
            tmp_pool = list(pool)
            tmp_weights = [c.weight for c in tmp_pool]
            for _ in range(n):
                if rng is None:
                    idx = random.choices(range(len(tmp_pool)), weights=tmp_weights, k=1)[0]
                else:
                    # 加权不放回：使用 RngStream.choices 单次抽样，然后从池移除
                    idx = rng.choices(range(len(tmp_pool)), weights=tmp_weights, k=1)[0]
                pick = tmp_pool.pop(idx)
                tmp_weights.pop(idx)
                picks.append(pick)
        else:
            # pool 不足 n 张：先取全部 pool，再用 filler 兜底到 n 张
            # 为保证兜底卡不与 pool 重复，先把 pool 加进去，再补 filler
            picks = list(pool)
            filler_id = "c_filler_atk"
            filler_cfg = self.cards.get(filler_id)
            while len(picks) < n:
                picks.append(Card(
                    card_id=filler_id,
                    config=filler_cfg or {},
                    tier="silver",
                    weight=1,
                    stackable=True,
                    unique_per_run=False,
                    rarity_zh="铜",
                    name_zh="细微改良",
                ))
        # 保底补一张金或彩
        if force_gold_or_color:
            gold_or_color = sorted(
                (c for c in pool if c.tier in (CardTier.GOLD, CardTier.COLOR)),
                key=lambda c: 0 if c.tier == CardTier.COLOR else 1,
            )
            if gold_or_color:
                # 替换其中一张非金/彩
                replaced = False
                for i, c in enumerate(picks):
                    if c.tier == CardTier.SILVER:
                        picks[i] = gold_or_color[0]
                        replaced = True
                        break
                if not replaced:
                    picks[-1] = gold_or_color[0]

        offer = CardOffer(
            offer_seq=self.next_offer_seq,
            cost=campaign_card_cost(self.next_offer_seq),  # 战斗期为 0；由调用方覆盖
            cards=picks,
        )
        self.next_offer_seq += 1
        self.offer_history.append(offer)
        # 更新连续无金彩
        has_premium = any(c.tier in (CardTier.GOLD, CardTier.COLOR) for c in picks)
        if has_premium:
            self.no_gold_or_color_offers_in_a_row = 0
        else:
            self.no_gold_or_color_offers_in_a_row += 1
        return offer

    # ------------------------------------------------------------------
    # 选择与结算
    # ------------------------------------------------------------------
    def resolve(
        self,
        offer: CardOffer,
        chosen_index: int,
        *,
        weapon_stack: list[str],
        active_weapon_id: str,
        weapon_levels: dict[str, int],
        apply_card_effect,
        on_new_weapon,
        on_weapon_discarded,
        on_weapon_upgrade,
        on_attack_capped,
        rng=None,
    ) -> Card:
        """选择 + 应用 + 事件。

        ``apply_card_effect(card, player, weapon_system, context)`` 由调用方注入。
        """
        card = offer.cards[chosen_index]
        # 防御：所选卡必须在 offer 里
        if card is None or chosen_index < 0 or chosen_index >= len(offer.cards):
            raise ValueError("invalid offer index")
        self.unlock_unique.add(card.card_id)
        self.owned_inventory[card.card_id] += 1
        apply_card_effect(card)
        # 事件
        self.bus.publish(Event(
            id=f"{card.card_id}-res-{offer.offer_seq}",
            type="card_resolved",
            payload={
                "card_id": card.card_id,
                "tier": card.tier,
                "offer_seq": offer.offer_seq,
            },
            tick=0,
        ))
        return card

    # ------------------------------------------------------------------
    # 攻击上限追踪（溢出攻击）
    # ------------------------------------------------------------------
    def record_capped_damage(self, raw: float, effective: float, *, monster_hp: float, monster_armor: float, tick: int = 0) -> None:
        """记录单次伤害的溢出。"""
        overflow = max(0.0, raw - effective)
        self.attack_overflow += overflow
        # 完成后会立即清零；如果不限该次独立，本次先不强制写回 total
        self.overflow_history.append({
            "raw": raw,
            "eff": effective,
            "monster_hp": monster_hp,
            "monster_armor": monster_armor,
            "overflow": overflow,
        })


def create_card_system(bus: EventBus, cards_cfg: dict) -> CardSystem:
    return CardSystem(bus=bus, cards=cards_cfg)


def card_resolved_event(card: Card, *, offer_seq: int, extra: dict | None = None) -> Event:
    payload = {
        "card_id": card.card_id,
        "tier": card.tier,
        "offer_seq": offer_seq,
    }
    if extra:
        payload.update(extra)
    return Event(
        id=f"card-{card.card_id}-{offer_seq}",
        type="card_resolved",
        payload=payload,
    )
