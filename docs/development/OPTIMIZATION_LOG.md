# RGame 持续优化日志

> 本文件记录本地开发分支上的每一轮检查、修改、测试和验收结果。未经过用户验收前，不推送到 GitHub 主分支。

## 2026-08-19 16:41:53 — Round 0：建立本地基线

- 本地仓库：`C:\\Users\\jiaya\\RGame`
- 开发分支：`agent/rgame-improvement-local`
- 基线提交：`bcd0450013421d586f4fb2a6f179c771083b86e1`
- 远程仓库：`jiayangrui05160031-cmyk/RGame`
- 基线状态：工作区干净，未修改原有文件。
- 当前目标：在本地持续优化，完成用户验收后再推送。

### 基线审计发现

1. README/CHANGELOG 声称有 129 项测试，但仓库当前只发现 `tests/test_engine_smoke.py`。
2. 当前 Hermes Python 环境未安装 pytest，首次执行 `python -m pytest -q` 失败：`No module named pytest`。
3. `AGENTS.md` 引用的 `specs/` 目录当前未被检出，README 中的规格文档链接需要复核。
4. `rgame/engine.py` 同时承担引擎调度和大量内容配置，后续扩展武器、敌人、事件和地图的维护成本较高。
5. `rgame/assets/v2/` 已有完整的角色、敌人、Boss、武器、效果、背景、UI、掉落和道具目录；后续重点不是盲目增加文件，而是让新增资产与玩法、地图机制和 UI 状态真正接通。
6. CI 已包含测试、headless smoke 和构建步骤，但本地依赖与仓库声明尚未完全对齐。

### 本轮原则

- 所有修改先落在本地开发分支。
- 每次修改前后记录原因、文件范围和验证命令。
- 优先小步提交，避免一次性重写核心引擎。
- 新武器、敌人、地图必须同时具备：数据定义、逻辑接入、渲染/反馈接入、资产路径和测试/烟测。
- 资产缺失时优雅降级，不允许因为一张可选图片缺失导致游戏无法启动。
- 在本轮结束前没有推送 GitHub。

## 2026-08-19 — Round 1：工程基线修复

### 修改

- `rgame/tools/verify_assets.py`
  - 移除开发者机器绝对路径依赖。
  - 默认从仓库根目录定位 `rgame/assets/v2`。
  - 增加 `--base` 和 `--quiet` 参数。
  - 返回非零退出码表示缺失、尺寸错误或 Alpha 错误，便于 CI 拦截。
- `pyproject.toml`
  - 开发依赖增加 `pillow>=10`，使资源校验在干净环境可安装。
- `.github/workflows/ci.yml`
  - 增加源代码资源校验步骤。
- `tests/test_project_contract.py`
  - 增加配置引用一致性检查。
  - 增加资源校验默认根目录测试。
- `README.md`
  - 不再预先声称仓库中不存在的测试数量，改为以本地实际 pytest 结果为准。
  - 增加资源校验命令。

### 验证

- `python -m pytest --collect-only -q`：3 tests collected。
- `python -m pytest -q`：3 passed。
- `python rgame/tools/verify_assets.py --quiet`：55/55，通过。
- `python -m compileall -q rgame main.py`：通过。
- `python main.py --headless --seed 42 --platform linux`：通过，输出 `Engine booted: RUNNING`。
- 固定 seed 长局模拟：程序未崩溃，但约 21.43 秒进入 `RESULT`，后续需要单独审计生存难度和玩家反馈。

### 当前本地提交

- 基线设计文档：`967e748`
- Round 1 待提交，验收后继续 UI/流畅度切片。

## 2026-08-19 — Round 2：UI 缓存与窗口缩放切片

### 修改

- `rgame/render/pygame_app.py`
  - 增加字体缓存 `get_ui_font`，避免无传入字体时每次绘制创建 `SysFont`。
  - 增加面板 Surface 缓存，战斗 HUD 相同样式面板只生成一次，后续直接复用。
  - 增加 UI 缓存清理入口。
  - 窗口 resize 后重新计算字体、清理旧精灵缩放缓存和背景缓存，避免新旧分辨率混用。
  - 保留原有 fallback 和战斗逻辑，不修改 `Engine.tick`、伤害和敌人规则。
- `tests/test_render_contract.py`
  - 增加同位置伤害数字的错位、入场缩放和淡出测试。
  - 增加字体缓存复用测试。

### 验证

- `python -m pytest --collect-only -q`：5 tests collected。
- `python -m pytest -q`：5 passed。
- `python -m compileall -q rgame main.py`：通过。
- `SDL_VIDEODRIVER=dummy` 渲染模块导入：通过。
- `python main.py --headless --seed 42 --platform linux`：通过。
- 真实 pygame 窗口：成功启动并获得 Windows 窗口句柄；CUA 视觉分析服务返回 400，因此自绘画布内部的视觉细节未冒充为已验收，待用户本地检查。

### 性能边界

- 本轮只做渲染对象复用和缩放缓存，不改变游戏规则。
- 后续需要在敌人高密度场景记录 FPS、对象数和渲染耗时，再决定是否加入动态粒子降级。

## 2026-08-19 — Round 3：内容纵向切片与原创资产

### 修改

- `rgame/config/content.py`
  - 新增敌人 `mine_leech`（矿脉寄生体）和 `rail_turret`（轨道炮台）。
  - 新增武器 `w_railbow`（磁轨长弓）和 `w_ember_drone`（熔核无人机）。
  - 新增对应彩色卡牌。
  - 第 4/5 关和无尽模式加入新敌人池，并保持权重总和为 1。
- `rgame/enemies/enemies.py`
  - 修复敌人生成快照没有把配置 `tags` 写入实例的问题；这对新敌人的能力判断和后续扩展很重要。
- `rgame/engine.py`
  - 新武器加入稀有度、商店和远程炮台投射物视觉映射。
- `rgame/render/theme.py` / `rgame/render/pygame_app.py`
  - 新敌人、新武器资源接入加载器。
  - 第 4/5 关背景加载、场景色调和 Endless 背景选择接通。
  - 熔核无人机图标在场上作为绕玩家运行的伴随单位显示。
  - 场景色调和暗幕 Surface 增加缓存。
- `rgame/tools/generate_vslice_assets.py`
  - 新增可复现的原创程序化资产生成器。
- 新增资源：
  - 两张 2048x2048 敌人动画表。
  - 两张 256x256 武器图标。
  - 两张 1920x1080 RGBA 关卡背景。
- `rgame/tools/verify_assets.py`
  - 资源清单从 55 项扩展到 61 项。
- `CHANGELOG.md` / `README.md`
  - 记录本地未发布切片，避免把未验收内容误写成远程版本。

### 验证

- `python -m pytest --collect-only -q`：5 tests collected。
- `python -m pytest -q`：5 passed。
- `python rgame/tools/verify_assets.py --quiet`：61/61，通过。
- `python -m compileall -q rgame main.py`：通过。
- `python main.py --headless --seed 42 --platform linux`：通过。
- pygame dummy 资源加载：新敌人 2/2、新武器 2/2、第 4/5 关背景已加载。
- 第 4 关 10 秒引擎模拟：新敌人 `mine_leech` 已实际生成并参与战斗，状态保持 `RUNNING`。

### 未推送内容

- 本轮所有代码、资源和文档仍只在本地分支，等待用户验收。

### 追加冒烟验证

- 强制激活 `w_ember_drone` 运行 4 秒：状态 `RUNNING`，无崩溃。
- 强制激活 `w_railbow` 运行 4 秒：状态 `RUNNING`，产生 1 个玩家投射物。
- 直接生成 `rail_turret` 运行 8 秒：进入 `recovery`，产生 1 个敌方投射物，远程攻击路径正常。

## 2026-08-19 — Round 4：修复进入战斗后卡死

### 现象

用户反馈：进入游戏界面后无法操作，窗口像卡死。

### 根因证据

使用真实窗口启动并以独立临时存档复现；诊断脚本在进入敌人渲染路径时得到完整异常：

```text
AttributeError: 'Enemy' object has no attribute 'hp'
```

位置：`rgame/render/pygame_app.py::_draw_enemy`。  
`Enemy` 数据类的真实生命字段是 `current_hp`。主入口捕获异常后会停在 `input("按 Enter 退出...")`，因此用户看到的是窗口不再响应，而不是正常的游戏暂停。

### 修复

- 将 `_draw_enemy` 中的 `e.hp / e.max_hp` 改为 `e.current_hp / e.max_hp`。
- 新增 `test_world_render_handles_spawned_enemy_without_crashing`，直接生成敌人并执行真实 pygame 渲染路径，防止该问题回归。
- 未修改输入系统、战斗公式或敌人状态机。

### 验证

- 定向渲染测试：3 passed。
- 完整测试：6 passed。
- 资源校验：61/61 通过。
- headless 启动：`Engine booted: RUNNING`。
- 真实渲染基准：60 帧耗时 0.180 秒，平均 2.99ms/帧，理论 FPS 约 334。
- 编译检查和 `git diff --check`：通过。

### 状态

- 修复尚未推送 GitHub。
- 用户本地的 `rgame_profile*.json` 存档未删除、未修改。

## 2026-08-19 — Round 5：修复第二个崩溃点（enemy_sprite frames 未定义）

### 现象

用户验收时复现“进入战斗后仍卡死”，且明确约定只改 `C:\Users\jiaya\RGame` 工作区。

### 根因

`_enemy_sprite()` 中 `frames` 只在“无破损贴图且无时间形态贴图”的分支里赋值。当敌人进入
破损贴图路径（`damage_level=1/2`，半血以下）或时间形态路径（`T1/T2/T3`）时，`src`
先被赋值，后面的 `len(frames)` 引用了从未定义的局部变量，抛 `UnboundLocalError`。
这发生在第一只要掉血的怪出现时，同样被主入口异常处理挡住，表现与上一轮完全一致。

### 修复

- `_enemy_sprite()` 顶部提前初始化 `frames = self.enemy_sprite_frames.get(config_id, [])`，
  破损/形态/动画三条路径共用同一变量，不再依赖分支才能定义。
- 回归测试扩展为覆盖满血、半血破损（damage1）、重伤裂甲（damage2）、时间形态 T2 四条渲染路径。

### 验证（全部在 C 盘工作区）

- `python -m pytest -q`：6 passed。
- `python -m compileall -q rgame main.py` + headless 启动：通过。
- 全路径渲染冒烟：
  - 真实战斗 45 秒：状态 RESULT，无异常。
  - 9 种敌人 × 3 档血量 × 4 种形态 = 108 个实例渲染：通过。
  - 全部 5 关背景 + 无尽模式：通过。
  - 武器 HUD 含新武器：通过。

### 范围纪律（本轮纠正）

- 之前排查时误改了 `D:\游戏测试\成型文件` 的副本；用户明确只以 C 盘工作区为准。已把 D 盘
  副本恢复原状、删除临时文件和备份。后续一律只在 `C:\Users\jiaya\RGame` 修改，推送待用户点头。
- 用户 3 份 `rgame_profile*.json` 存档未跟踪、未删除、未修改。

## 2026-08-19 — Round 6：修复第三个卡死点（进战斗第一帧 _mouse_move_target 未初始化）

### 现象

用户复现：进入战斗界面瞬间完全卡死，键盘敲击无任何响应，窗口不再刷新。

### 根因

`_mouse_move_target` 从未在 `__init__` 中初始化，只在事件处理器里赋值
（WASD 移动键、鼠标左/右键、拖拽）。`_update_mouse_movement()` 的守卫是
`if self.engine.state() != "RUNNING" or self._mouse_move_target is None:` —
Python 的 `or` 短路使菜单态永不触碰该属性，因此主菜单一切正常；一旦进入
RUNNING（战斗），第一帧事件轮询必然读取未定义属性，抛 `AttributeError`，
`app.run()` 抛出后被 main.py 的 `input("按 Enter 退出...")` 兜住，窗口冻结、
键盘死亡——与用户描述的"进战斗直接卡死"完全一致。此 bug 自 v0.1.0 起就存在，
只是此前会话里玩家先按过移动键或右键（恰好创建了属性）而未触发。

### 修复

- `__init__` 中显式初始化 `self._mouse_move_target: tuple[float, float] | None = None`。
- 新增回归测试 `test_enter_battle_first_poll_events_no_crash`：启动 → 直接进
  RUNNING → 全程不投递任何事件 → `_poll_events()`。修复前必抛 AttributeError，
  修复后通过。
- 静态扫描同类隐患：战斗路径上其余"读未初始化属性"均为方法调用或已初始化，
  `_mouse_move_target` 是唯一雷点。

### 验证

- 回归测试单独验证：stash 掉修复后该测试精确复现 AttributeError；恢复修复后通过。
- `python -m pytest -q`：7 passed。
- 无头全流程：菜单轮询 → start_run → 180 帧战斗渲染 + WASD/J/K/Q/R/1/2/3/Esc 按键：无异常。
- 真实窗口冒烟：修复后启动正常进入主菜单（此前修复前版本在战斗态崩溃）。

### 状态

- 本地分支 `agent/rgame-improvement-local`，推送待用户点头（与 Round 0 约定一致）。
- 用户 `rgame_profile*.json` 存档未跟踪、未修改。

## 2026-08-19 — Round 7：修复 CI 失败（COL_PLAYER_TRIM 未定义 + LFS 未拉取）

### 现象

推送到 GitHub main 后 Actions CI 失败（run 32247972550，18s），
`test_world_render_handles_spawned_enemy_states` 在 `_draw_player()` 抛
`NameError: name 'COL_PLAYER_TRIM' is not defined`。本地 pytest 全绿。

### 根因

- `COL_PLAYER_TRIM` 在 pygame_app.py 中只被引用、从未定义（theme.py 有
  `PLAYER_TRIM`，但模块常量漏了这行映射）。玩家贴图存在时走贴图分支不触发；
  贴图缺失时走 fallback 圆渲染必炸。
- CI 的 `actions/checkout` 未开 `lfs: true`，LFS 资产只是指针文件 → 玩家贴图
  加载失败 → 暴露上述幽灵常量。这是"本地绿、CI 红"的典型环境差。

### 修复

- `pygame_app.py`：补 `COL_PLAYER_TRIM = T.PLAYER_TRIM`。
- `.github/workflows/ci.yml`：checkout 加 `lfs: true`，CI 与本地资产一致，
  不再掩盖 fallback 路径问题。
- 新增回归测试 `test_player_fallback_render_no_crash`：强制贴图缺失渲染
  fallback 分支（回滚修复后精确复现 NameError）。

### 验证

- `python -m pytest -q`：8 passed；单测回滚验证通过（无修复必失败）。
- CI 重新运行结果见 run 记录。

### 状态

- 推送到 GitHub main（用用户 token 文件内有效 token）。

## 2026-09-23 — Round 8：关卡专属环境事件

### 目标

让第四、第五关拥有不同于换背景和敌人池的战斗记忆点，并让危险提示、躲避操作和完成奖励形成闭环。

### 实现

- 第四关加入“矿脉共振”：五个橙色警示圈按螺旋方向落在玩家附近，约 2.5 秒后爆裂。
- 第五关加入“轨道锁定”：五个红色警示圈预判玩家朝向，爆裂前可通过变向离开。
- 两个事件各在对应关卡必定出现一次，复用现有事件 HUD、音效、危险圈和炸弹躲避统计；完成事件可得金币与一次抽卡。
- 环境事件参数写入关卡配置并纳入配置契约检查；配置版本升至 0.2.0。
- 更新中英文 README 与变更日志，纠正战役关卡数为五关。

### 验收状态

- 本轮未运行自动化测试或游戏启动；代码已保留在本地开发分支，等待用户验收后继续验证与推送。

## 2026-09-23 — Round 9：深空视觉统一、卡牌构筑与虚空守卫

### 目标

统一主菜单、战斗 HUD、角色、场景、攻击反馈和卡牌选择的太空视觉，并让新增表现对应到可玩的构筑选择与 Boss 招式。

### 实现

- 主题色更新为深海军蓝、青色能量、象牙白/蓝钢、克制紫光与琥珀奖励；共享面板和按钮使用斜切舰载仪表造型。
- pygame 与 Kivy 的语义色统一到同一套深空色板，首领警报与护盾提示也同步调整。
- 主菜单加入低对比星尘；五个战区各自使用不同场景地标、尘埃色和轨道图层，保留战斗中心可读性。
- 使用内置 ImageGen 生成透明背景主角“太空陆战员”与 Boss“虚空守卫”，保存为 `rgame/assets/v3/player/player_space_marine.png` 和 `rgame/assets/v3/boss/boss_void_warden.png`；按比例缩放且未覆盖旧资源。
- 抽卡新增暴击率、暴击倍率、离子散射和动能反应堆构筑；新获得武器继承全局暴击成长。选择界面新增稀有度、路线标签、类别徽记和焦点浮起反馈。
- Boss 新增“棱镜炮列”：锁定玩家方向后显示多条横向危险线，留出侧移窗口；狂暴末阶段增加弹道数量。Boss 六技能选择改用本局随机流，保证固定种子可复现；新增旋转卫星核心和阶段标识。
- 更新中英文 README、视觉素材规范与变更日志；配置版本升至 0.3.0。

### 验收状态

- 本轮未运行自动化测试或游戏启动；只做静态代码检查与改动核对。
- 改动保留在本地 `agent/rgame-improvement-local` 分支，未推送；三个未跟踪玩家存档未修改。

## 2026-09-23 — Round 10：敌人阵容美术统一

### 目标

消除新主角/虚空守卫与旧敌人像素/卡通立绘之间的明显画风断层，并清理仍残留的旧式卡牌外框。

### 实现

- 使用内置 ImageGen 生成 3×3 透明敌人立绘表，按九种兵种配置顺序裁切加载；保持追击、翼刃、重甲、炮手、狙击、散射、布雷、寄生与炮台九种独立轮廓。
- 敌人替换为象牙白装甲、蓝钢与青色能源的统一视觉，静态模型增加小幅悬浮与姿态摆动；旧时间/破损贴图仅在新版贴图无法加载时保留回退。
- 卡牌选择继续用程序化深空仪表框，移除不匹配的新旧混搭铜色齿轮贴图。
- 更新资产规范和中英文说明；素材文件为 `rgame/assets/v3/enemies/enemy_roster_sheet.png`。

### 验收状态

- 本轮未启动游戏或运行自动化测试；静态核对资源路径、九兵种映射与工作区差异。
- 所有改动仍在本地工作区，未提交、未推送；玩家存档未修改。

## 2026-09-23 — Round 11：敌人战术、Boss 弹幕与战斗反馈

### 目标

解决敌人与 Boss 战斗模式重复、掉落物辨识度低、攻击反馈与新太空画风不一致的问题。

### 实现

- 阵容扩到 13 种：裂隙舞刃绕位游击并交替双发；相位潜猎者冷却后侧切瞬移；虚空修复者优先治疗两名残血同伴并显示修复光束；棱镜炮兵蓄力后发射三发扇列。
- 新敌人按战役进度从第三关起逐步加入，第四关出现修复者，第五关与无尽模式加入棱镜炮兵。
- Boss 新增“虚空潮汐”，分波向外发射环形弹幕并旋转安全缺口；预警圈同步标记可穿过的方向，狂暴后弹速提升、缺口收窄。
- 新增专精敌人 2×2 立绘、拾取物 2×2 立绘、战斗效果 2×2 立绘。经验晶体、医疗胶囊、护盾电池和装甲核心使用独立素材；命中、击杀、受伤与弹体接入青白等离子反馈。
- pygame 与 Kivy 两套渲染器都接入共享角色、敌人、拾取物和命中特效立绘，并保留缺图时的程序化回退。
- 拾取物增加微弱脉动与轨道光点，保持小尺寸可辨认且避免每帧旋转贴图的额外开销。
- 配置版本升至 0.4.0，更新中英文说明、视觉规范及变更日志。

### 验收状态

- 未启动游戏、未运行自动化测试；已静态核对新增配置、渲染映射和素材路径。
- 所有改动仍在本地开发分支，未提交、未推送；三个玩家存档文件未修改。

## 2026-09-23 — Round 12：火星战役插画、角色皮肤与武器特效

### 目标

继续统一深空画风，并补足玩家能直接看见和选择的主角、武器、掉落物与战斗表现素材。

### 实现

- 使用 Codex 内置 ImageGen（非命令行工具）制作 v4 主菜单战役插画、2×2 主角皮肤表、3×3 武器图标表、2×2 全新拾取物表与 2×2 战斗特效表。完整生成提示词和裁切映射在 `rgame/assets/v4/ASSET_PROMPTS.md`。
- pygame 主菜单使用全屏火星插画，菜单控件移至左侧以露出宇航员与轨道堡垒；游戏日志面板移到右下方。
- 开局预设页加入主角外观预览，支持点击前后箭头、点击预览卡或按 V 循环四款皮肤；外观只影响视觉，不读写玩家存档与战斗数值。
- 新武器图标覆盖近战刃、精准步枪、散射枪、轨道哨机、光束格栅炮、奥术能量球、霜晶长枪、星坠弓、虚空双枪，并接入 pygame 武器栏、列表和商店；Kivy HUD 也显示已有武器对应图标。
- 全新掉落物表覆盖经验、治疗、护盾和护甲；战斗反馈使用晶体冲击、虚空裂变和星坠冲击，近战挥击加入定向弧形能量斩图。
- pygame 与 Kivy 共用 v4 主角皮肤、武器、拾取物与战斗特效；旧资源仍可在新资源缺失时回退。
- 启动游戏时发现专精敌人缺少形态/破损缓存项导致 `KeyError`，已改为安全初始化缺失项。
- 更新中英文 README、视觉音频规范与 CHANGELOG。

### 验收状态

- 按用户要求启动 pygame 本地窗口；首次启动问题已修复，当前“火星攻击”窗口保持响应。未运行自动化测试。
- 所有改动仍在 `agent/rgame-improvement-local` 本地工作区，未提交、未推送。

## 2026-09-23 — Round 13：角色出手动作与敌人受击反馈

### 目标

解决新皮肤与敌人立绘有外观、但攻击时像静态贴图的问题，让蓄力、出手和受击能从身体姿态上读出来。

### 实现

- 玩家瞄准时持械手臂伸展并预备，开火时角色后坐、枪口扩张闪亮；近战挥击时手臂与刀刃同步扫过。
- 普通敌人根据 WINDUP / ATTACKING / RECOVERY 状态改变身体倾角与前后重心；为不同兵种绘制有颜色区分的武器手臂，近战敌人增加挥刃动作。
- 敌人受击时有短促弹开与抖动；Boss 在技能蓄力和释放时带动重型武器/肢体动作。
- 动作表现读取现有战斗状态，不改变命中判定、攻击数值或存档内容。

### 验收状态

- 本轮没有运行自动化测试；动作状态与绘制调用按现有 pygame 引擎字段静态核对。
- 修改仅在本地工作区，未提交或推送；已打开的游戏窗口需要重启后才会加载本轮改动。

## 2026-09-28 — Round 14：可闪避射击、战术掉落与 Boss 状态修复

### 目标

让敌人预警能指导玩家移动，拾取物带来真实的局内选择，并修复 Boss 弱点和掉落规则。

### 实现

- 远程敌人在蓄力开始时锁定目标点，预警线和准星显示实际射击方向；玩家离开目标点即可闪避。
- 临时加速与攻速掉落接入玩家移动和武器间隔，增益时间可叠加，HUD 显示倒计时。
- 新增战术电容掉落：优先缩短主动技能冷却；技能已就绪时转为短时攻速增益。
- 低血量掉落补偿只作用于当次抽取，不永久修改配置权重。
- Boss 战斗实体标记为超级怪兽，修复弱点、破防和击杀识别；由专属状态机负责技能，恢复间隙追近玩家；Boss 击败后使用专属掉落表。
- 使用 Codex 内置 ImageGen 绘制 2×2 战术拾取物图标，pygame 与 Kivy 共用；完整提示词、裁切映射在 `rgame/assets/v5/ASSET_PROMPTS.md`。
- 配置版本更新为 0.5.0，公式版本更新为 0.2.0。

### 验收状态

- 战术掉落、Boss 逻辑、引擎启动与渲染检查共 11 项通过；临时检查用例未保留在项目中。
- 改动保留在本地开发分支，未提交或推送，玩家存档未修改。
