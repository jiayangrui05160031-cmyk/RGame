"""rgame 项目级 Agent 开发指引。

## 项目结构

```
rgame/                 核心库（无 GUI 依赖）
├── core/              状态机、事件总线、命名随机流、单局上下文、时间
├── config/            数据契约、默认内容表（关卡/敌人/武器/卡牌/掉落/成就）
├── combat/            伤害结算、武器循环、自动索敌、投射物
├── enemies/           敌人状态机、生成导演、超级怪兽、时间强化公式
├── player/            玩家属性、移动、键鼠/触屏输入抽象
├── cards/             抽卡系统（三选一、银/金/彩、LIFO）
├── drops/             掉落系统（含炸弹、3 秒寿命、防连出）
├── level/             计分系统、关卡通关、等级
├── achievements/      24 个三级成就
├── save/              存档原子写入与版本迁移
├── log/               结构化事件日志
├── engine.py          核心引擎：把所有模块按状态机节拍调度
└── render/
    └── pygame_app.py  pygame 桌面渲染与输入适配
main.py                启动入口
tests/                 pytest 套件（规则/集成/场景/平台 四层）
specs/                 原始规格文档（已就绪）
```

## 模块依赖（核心库部分严格无 GUI）

```
core ← config ← combat / enemies / cards / drops / level / achievements
                 ↓
              engine  ← pygame 渲染器（仅这里依赖外部库）
                 ↑
               player（输入抽象，UI 与键盘只在此处注入）
```

## 启动方式

```bash
# 桌面（pygame 渲染）
python main.py

# 固定 seed
python main.py --seed 1234

# 关闭渲染、仅自检
python main.py --headless

# 运行测试
python -m pytest -q
```

## 任务类型与责任

- **规格补全**：编辑 ``specs/``，遵守总纲优先级（> 功能域入口 > 三级细节 > 示例数值）。
- **实现**：在 ``rgame/`` 对应模块中按模块要求落地，注意：
    - 不直接修改 ``Engine._init`` 之外的逻辑；
    - 改算法时同步增加 ``formula_version``，写入配置版本；
    - 数据默认值属于 ``rgame/config/content.py``，不在逻辑里散布数值。
- **测试**：编写 ``tests/`` 下文件，按规格文档中测试用例 ID 命名。
- **修复**：先在 ``rgame/log`` 启用结构化日志定位问题，再以单元测试固化。
- **审核**：重新读总纲与责任文档，输出 ``通过 / 有条件通过 / 不通过``。

## 禁止事项

- 把表现层（pygame / 颜色 / 字体）混入核心库；
- 在多层之间循环引用；
- 写浮点时间到存档（用整数或科学计数）；
- 跳过事件总线直接读写 player / weapon / drop 状态。
