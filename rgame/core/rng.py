"""命名随机流。

按《游戏总体流程》§3 与《数据与配置契约》§6：

- 每局持有 ``run_seed``；
- 多个命名流互不干扰：``enemy_spawn_rng``、``drop_rng``、``card_rng``、
  ``super_rng``、``crit_rng``、``weapon_pick_rng``；
- 同 seed + 同输入序列可复现关键事件。

实现：Mulberry32 32-bit，确定性、低占用、不依赖外部库。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Sequence

from .event_bus import EventBus, Event


def _mulberry32(seed: int) -> random.Random:
    """Mulberry32：32-bit 周期、确定性、无第三方依赖。"""
    state = [seed & 0xFFFFFFFF]

    def next_u32() -> int:
        """标准 Mulberry32 混合步骤；必须覆盖完整 32-bit 输出空间。"""
        state[0] = (state[0] + 0x6D2B79F5) & 0xFFFFFFFF
        t = state[0]
        t = (t ^ (t >> 15)) * (t | 1) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return (t ^ (t >> 14)) & 0xFFFFFFFF

    def randbits(k: int) -> int:
        if k <= 0:
            return 0
        value = 0
        produced = 0
        while produced < k:
            value |= next_u32() << produced
            produced += 32
        return value & ((1 << k) - 1)

    rng = random.Random()
    rng.setstate(
        (
            3,
            tuple([seed & 0xFFFFFFFF] + [0] * 624),
            None,
        )
    )
    # 我们不直接用 Random；只是为了分享 API。
    rng.random()  # 预热，保证 Random 状态不再依赖外部熵

    # 真正的核心：基于 Mulberry32 的生成器。
    def rand_int() -> int:
        return next_u32()

    # 通过匿名对象暴露 randint/random API。
    class _Mul:
        def random(self) -> float:
            return rand_int() / 0xFFFFFFFF

        def randint(self, a: int, b: int) -> int:
            return a + rand_int() % (b - a + 1)

        def uniform(self, a: float, b: float) -> float:
            return a + (b - a) * (rand_int() / 0xFFFFFFFF)

        def choice(self, seq: Sequence) -> object:
            return seq[rand_int() % len(seq)]

        def choices(self, population, weights=None, k: int = 1) -> list:
            n = len(population)
            if weights is None:
                return [population[rand_int() % n] for _ in range(k)]
            total = sum(weights)
            results: list = []
            cum = 0.0
            cs: list[float] = []
            for w in weights:
                cum += w
                cs.append(cum / total)
            for _ in range(k):
                r = rand_int() / 0xFFFFFFFF
                for i, c in enumerate(cs):
                    if r <= c:
                        results.append(population[i])
                        break
            return results

        def sample(self, population: Sequence, k: int) -> list:
            n = len(population)
            if k > n:
                raise ValueError("sample larger than population")
            pool = list(range(n))
            chosen: list = []
            for _ in range(k):
                j = rand_int() % len(pool)
                chosen.append(population[pool.pop(j)])
            return chosen

        def shuffle(self, x: list) -> None:
            for i in range(len(x) - 1, 0, -1):
                j = rand_int() % (i + 1)
                x[i], x[j] = x[j], x[i]

        def getrandbits(self, k: int) -> int:
            return randbits(k)

    return _Mul()  # type: ignore[return-value]


# 预定义随机流名（按《数据与配置契约》§6）。
ENEMY_SPAWN = "enemy_spawn_rng"
DROP = "drop_rng"
CARD = "card_rng"
SUPER = "super_rng"
CRIT = "crit_rng"
WEAPON_PICK = "weapon_pick_rng"

DEFAULT_STREAMS: tuple[str, ...] = (ENEMY_SPAWN, DROP, CARD, SUPER, CRIT, WEAPON_PICK)


def _seed_for(base_seed: int, stream: str) -> int:
    """派生各流的种子（FNV-1a 64-bit -> 取低 32-bit）。"""
    h = 0xCBF29CE484222325  # 14695981039346656037
    b = base_seed & 0xFFFFFFFF
    for ch in stream.encode("utf-8"):
        h ^= ch
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    h ^= b
    return h & 0xFFFFFFFF


@dataclass
class RngStream:
    """单个命名随机流。"""

    name: str
    seed: int
    inner: object  # _Mul 实例

    def random(self) -> float:
        return self.inner.random()  # type: ignore[attr-defined]

    def chance(self, p: float) -> bool:
        """按 0–1 概率判定。"""
        return self.random() < p

    def randint(self, a: int, b: int) -> int:
        return self.inner.randint(a, b)  # type: ignore[attr-defined]

    def uniform(self, a: float, b: float) -> float:
        return self.inner.uniform(a, b)  # type: ignore[attr-defined]

    def weighted(self, items: Iterable, weights: Iterable[float]) -> object | None:
        items = list(items)
        weights = list(weights)
        if not items:
            return None
        picked = self.inner.choices(items, weights=weights, k=1)  # type: ignore[attr-defined]
        return picked[0]

    def choice(self, items: Sequence) -> object:
        return self.inner.choice(items)  # type: ignore[attr-defined]

    def range(self, stop: int) -> int:
        return self.randint(0, max(0, stop - 1))

    def choices(self, population, weights=None, k: int = 1) -> list:
        return self.inner.choices(population, weights=weights, k=k)  # type: ignore[attr-defined]

    def sample(self, population: Sequence, k: int) -> list:
        return self.inner.sample(population, k)  # type: ignore[attr-defined]

    def shuffle(self, x: list) -> None:
        self.inner.shuffle(x)  # type: ignore[attr-defined]

    def getrandbits(self, k: int) -> int:
        return self.inner.getrandbits(k)  # type: ignore[attr-defined]  # noqa


class NameRng:
    """多命名流集合；每个流独立且同 seed 可复现。"""

    def __init__(self, base_seed: int, streams: Iterable[str] = DEFAULT_STREAMS) -> None:
        self.base_seed = base_seed & 0xFFFFFFFF
        self.streams: dict[str, RngStream] = {}
        for s in streams:
            seed = _seed_for(self.base_seed, s)
            self.streams[s] = RngStream(name=s, seed=seed, inner=_mulberry32(seed))

    def get(self, name: str) -> RngStream:
        try:
            return self.streams[name]
        except KeyError as exc:
            raise KeyError(f"未知随机流：{name!r}，已注册：{sorted(self.streams)}") from exc

    def reseed(self, base_seed: int) -> None:
        self.__init__(base_seed, self.streams.keys())

    def stats(self) -> dict[str, dict]:
        return {n: {"seed": s.seed} for n, s in self.streams.items()}


def make_rng_streams(base_seed: int) -> NameRng:
    """便捷构造。"""
    return NameRng(base_seed)
