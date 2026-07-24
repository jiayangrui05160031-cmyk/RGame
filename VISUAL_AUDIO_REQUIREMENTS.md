# 视觉 / UI / 音频需求清单（武器组合与局内变化版本）

日期：2026-07-14  
用途：配合已落地的武器组合技、随机事件、首领阶段、敌人词缀、局内挑战和战斗反馈。

## 保存目录总表

项目素材根目录：

`D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2`

请按下面目录保存。文件名尽量完全照清单写，后续接入代码会轻松很多。

| 素材类型 | 保存目录 |
|---|---|
| 武器组合技图标 | `D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\icons\combos` |
| 敌人词缀图标 | `D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\icons\affixes` |
| 随机事件图标 | `D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\icons\events` |
| 首领专属素材 | `D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\boss` |
| 首领 UI / 弱点 / 破防条 | `D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\ui\boss` |
| 宝箱和奖励素材 | `D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\chests` |
| 战斗反馈素材 | `D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\effects` |
| 可平铺背景 | `D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\backgrounds` |
| 场景装饰 | `D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\props` |
| UI 面板 / 横幅 / 图标 | `D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\ui` |
| 音效 | `D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\audio\sfx` |
| 背景音乐 | `D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\audio\music` |

## 统一素材要求

- PNG 必须是真 RGBA 透明背景。
- 禁止棋盘格背景、灰底、黑底、白底、渐变底板、文字、水印和杂色。
- 主体完整居中，四周保留约 10% 透明边距。
- 风格统一：科幻火星战斗、清晰黑/深色描边、高饱和发光点缀。
- 图标需在 32x32、64x64、128x128 下仍可辨认。

## 1. 武器组合技图标

保存目录：`D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\icons\combos`

尺寸：128x128，透明背景。

| 机制 | 文件建议名 | 视觉要点 |
|---|---|---|
| 雷链 | `icon_combo_thunder_chain.png` | 闪电在多个节点之间弹跳 |
| 蒸汽爆裂 | `icon_combo_steam_burst.png` | 冰蓝与赤焰碰撞产生白色蒸汽爆炸 |
| 腐血 | `icon_combo_corrupt_blood.png` | 绿色毒雾 + 深红血滴回流 |
| 聚焦光网 | `icon_combo_focused_lattice.png` | 多束激光聚焦成网格 |
| 震地 | `icon_combo_earth_shock.png` | 裂地冲击波、岩块飞散 |

## 2. 敌人词缀图标

保存目录：`D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\icons\affixes`

尺寸：64x64，透明背景，不要文字。

| 词缀 | 文件建议名 | 视觉要点 |
|---|---|---|
| 冰甲 | `icon_affix_ice_armor.png` | 蓝色冰甲/雪flake 轮廓 |
| 分裂 | `icon_affix_split.png` | 一个核心分成两个小核心 |
| 吸血 | `icon_affix_lifesteal.png` | 红色尖牙/血滴 |
| 反射 | `icon_affix_reflect.png` | 镜面盾牌反弹弹丸 |
| 爆燃 | `icon_affix_volatile.png` | 橙红爆炸火苗 |
| 迅捷 | `icon_affix_swift.png` | 绿色速度线/翅刃 |
| 召唤 | `icon_affix_summoner.png` | 紫色传送门召出小怪 |

## 3. 随机事件图标

保存目录：`D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\icons\events`

尺寸：128x128，透明背景，颜色区分明显。

| 事件 | 文件建议名 | 视觉要点 |
|---|---|---|
| 补给舱 | `icon_event_supply_pod.png` | 降落舱、医疗十字、护盾蓝光 |
| 黑市商人 | `icon_event_black_market.png` | 神秘商人/斗篷/红色交易芯片 |
| 外星遗迹 | `icon_event_alien_relic.png` | 古代火星遗迹、绿色符文 |
| 失控能源 | `icon_event_unstable_energy.png` | 过载反应堆、黄色电弧 |
| 救援信标 | `icon_event_rescue_beacon.png` | 蓝色信标塔、保护圈 |
| 陨石雨 | `icon_event_meteor_rain.png` | 多颗陨石坠落、橙色尾焰 |

## 4. 首领专属素材

动作帧保存目录：`D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\boss`

首领 UI / 弱点 / 破防条保存目录：`D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\ui\boss`

建议每个首领至少 4 帧，256x256 或 384x384，透明背景。

- 待机帧：`boss_<id>_idle_01..04.png`
- 攻击帧：`boss_<id>_attack_01..04.png`
- 第二阶段场地变化帧：`boss_<id>_phase2_01..04.png`
- 狂暴帧：`boss_<id>_enraged_01..04.png`
- 死亡爆炸帧：`boss_<id>_death_01..06.png`
- 弱点图标：`icon_boss_weakpoint.png`
- 破防条装饰：`ui_boss_break_gauge.png`
- 技能预警圈：`fx_boss_warning_circle.png`
- 屏幕边缘警告：`fx_screen_edge_warning.png`

## 5. 宝箱和奖励素材

保存目录：`D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\chests`

尺寸：160x160，透明背景。

每种宝箱三状态：

- 普通宝箱：`chest_common_closed.png` / `chest_common_opening.png` / `chest_common_open.png`
- 稀有宝箱：`chest_rare_closed.png` / `chest_rare_opening.png` / `chest_rare_open.png`
- 史诗宝箱：`chest_epic_closed.png` / `chest_epic_opening.png` / `chest_epic_open.png`
- 传说宝箱：`chest_legendary_closed.png` / `chest_legendary_opening.png` / `chest_legendary_open.png`

## 6. 战斗反馈素材

保存目录：`D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\effects`

尺寸：128x128 或 256x256，透明背景。

| 效果 | 文件建议名 |
|---|---|
| 暴击闪光 | `fx_crit_flash.png` |
| 敌人碎裂 | `fx_enemy_shatter.png` |
| 燃烧 | `fx_burning.png` |
| 冰冻 | `fx_freeze.png` |
| 毒雾 | `fx_poison_cloud.png` |
| 雷电残留 | `fx_thunder_residue.png` |
| 护盾破裂 | `fx_shield_break.png` |
| 蒸汽爆裂 | `fx_steam_burst.png` |
| 雷链跳跃 | `fx_thunder_chain_arc.png` |
| 地震冲击波 | `fx_earth_shockwave.png` |
| 聚焦光网 | `fx_focused_lattice.png` |
| 腐血治疗回流 | `fx_corrupt_blood_heal.png` |

## 7. 背景和场景素材

背景保存目录：`D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\backgrounds`

场景装饰保存目录：`D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\props`

可平铺背景：1024x1024。

- 火星沙地：`bg_mars_sand_tile.png`
- 陨石坑：`bg_crater_tile.png`
- 废弃基地：`bg_abandoned_base_tile.png`
- 能源矿区：`bg_energy_mine_tile.png`
- 外星遗迹：`bg_alien_ruins_tile.png`

场景装饰建议 3–5 个一组，透明背景，避免遮挡战斗视线：

- 小型岩石、破碎天线、废弃补给箱、裂开的能源管线、远景遗迹柱。

## 8. UI 需求

保存目录：`D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\v2\ui`

- 武器组合技面板：显示 `已激活 / 未激活`、缺少武器、等级不足。
- 武器槽：显示品质颜色、等级 `Lv 当前/上限`、突破状态。
- 随机事件横幅：事件名、剩余时间、简短说明。
- 局内挑战面板：最多显示 2 条进行中挑战，完成/失败弹出提示。
- 首领 HUD：阶段、破防条、弱点图标、技能预警圈。
- 敌人词缀标识：小图标显示在敌人头顶，最多 3 个。
- 战斗反馈：伤害数字、暴击数字、连杀文字、受伤屏幕闪烁、无敌提示。

## 9. 音效需求

保存目录：`D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\audio\sfx`

格式建议：WAV 或 OGG，短音效 0.1–1.5 秒，循环音乐 OGG。

| 类别 | 文件建议名 | 说明 |
|---|---|---|
| 组合技激活 | `sfx_combo_activated.ogg` | UI 提示音，有成就感 |
| 雷链 | `sfx_thunder_chain.ogg` | 电弧跳跃 |
| 蒸汽爆裂 | `sfx_steam_burst.ogg` | 蒸汽爆炸、短促冲击 |
| 腐血治疗 | `sfx_corrupt_blood_heal.ogg` | 低沉回流 + 治疗亮音 |
| 聚焦光网 | `sfx_focused_lattice.ogg` | 激光充能叠加 |
| 震地 | `sfx_earth_shock.ogg` | 地面冲击、低频震动 |
| 随机事件出现 | `sfx_event_spawn.ogg` | 提醒但不刺耳 |
| 挑战完成 | `sfx_challenge_complete.ogg` | 短促奖励音 |
| 挑战失败 | `sfx_challenge_failed.ogg` | 低调失败提示 |
| 首领换阶段 | `sfx_boss_phase.ogg` | 压迫感增强 |
| 首领破防 | `sfx_boss_break.ogg` | 护甲破裂、清晰反馈 |
| 词缀敌人出现 | `sfx_affix_spawn.ogg` | 精英/危险提示 |

## 10. 背景音乐需求

保存目录：`D:\obsidian\oos\游戏测试\1\成型文件\rgame\assets\audio\music`

- 普通关卡 BGM：火星战斗、节奏 110–130 BPM、循环 90–150 秒。
- 随机事件 BGM Layer：可叠加紧张打击乐，事件结束淡出。
- 首领 BGM：更强低频和警报感，阶段 3 可以加速或叠加鼓组。
- 结算 BGM：短循环、轻松但有胜负区分。
