"""rgame – 核心域

按《游戏项目 Harness 总纲》落地的俯视角肉鸽游戏核心库。

模块层级：

- ``rgame.core``     – 状态机 / 事件总线 / 单局上下文 / 时间 / 命名随机流；
- ``rgame.config``   – 数据契约、实体/武器/卡牌/掉落/成就内容表、加载校验；
- ``rgame.combat``   – 伤害结算管线、武器循环、投射物；
- ``rgame.enemies``  – 敌人状态机、原型、生成导演、超级怪兽；
- ``rgame.player``   – 玩家数据与成长接口；
- ``rgame.cards``    – 三选一抽卡系统；
- ``rgame.drops``    – 有利/危险掉落与炸弹；
- ``rgame.level``    – 关卡、计分、等级、阶段；
- ``rgame.achievements`` – 24 个三级成就；
- ``rgame.save``     – 存档原子写入与版本迁移；
- ``rgame.log``      – 事件日志与回放；
- ``rgame.render``   – pygame 渲染与跨平台输入适配。
"""

__version__ = "0.1.0"
APP_NAME = "rgame"

GAME_VERSION = "0.1.0"
CONFIG_VERSION = "0.5.0"
FORMULA_VERSION = "0.2.0"

__all__ = [
    "__version__",
    "APP_NAME",
    "GAME_VERSION",
    "CONFIG_VERSION",
    "FORMULA_VERSION",
]
