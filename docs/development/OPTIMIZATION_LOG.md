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
