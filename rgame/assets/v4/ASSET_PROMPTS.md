# v4 游戏美术素材来源与裁切顺序

生成日期：2026-09-23
生成方式：Codex 内置 ImageGen 工具（非命令行图像生成器）；提示词为英文，使用项目 v3 角色/拾取物/特效作风格参考。
本批资产位于 `rgame/assets/v4/`，来源图保留在生成目录，项目副本已接入渲染器。

## 资源映射

| 文件 | 尺寸 / 格式 | 裁切顺序与用途 |
|---|---|---|
| `illustrations/main_menu_mars_keyart.png` | 1672×940，RGB | 主菜单全屏火星战役插画；左侧暗部容纳菜单，右侧呈现宇航员、轨道堡垒与敌群。 |
| `player/player_skin_roster_sheet.png` | 1254×1254，RGBA，2×2 | 苍穹先锋、赤焰彗星、星海守望、蚀月潜行者；预设页展示并可切换，选定外观进入战斗。 |
| `weapons/weapon_icon_roster_sheet.png` | 1254×1254，RGBA，3×3 | 近战刃、精准步枪、散射枪、轨道哨机、光束格栅炮、奥术能量球、霜晶长枪、星坠弓、虚空双枪；覆盖武器栏、配置列表、商店与 Kivy HUD。 |
| `pickups/pickup_roster_sheet.png` | 1254×1254，RGBA，2×2 | 经验晶体、医疗胶囊、护盾棱镜、装甲核心；覆盖战场掉落图标。 |
| `effects/combat_vfx_roster_sheet.png` | 1254×1254，RGBA，2×2 | 晶体冲击、能量斩击、虚空裂变、星坠冲击；用于近战挥击、命中、击杀和冲击反馈。 |

透明贴图表由渲染器按等分格裁切。不得给素材表加格线、文字、背景色或水印。

## 生成提示词

### 主菜单插画

> Create polished 16:9 landscape key art for a premium top-down roguelite game set on Mars and deep space. Unified visual language: dark navy and indigo, ivory white armor, restrained cyan luminous accents, subtle violet and amber highlights, painterly sci-fi illustration with crisp readable silhouettes. Scene: a small armored space marine seen from behind in the lower center-left facing a colossal alien orbital fortress and distant planets over a red Martian horizon; scattered asteroids, luminous rift, several tiny enemy silhouettes and one large boss silhouette. Cinematic layered depth, exquisite surface detail, beautiful controlled bloom, dramatic but not muddy, high contrast on the right and atmospheric negative space on the left for game menu controls. No text, no logo, no UI, no borders, no watermark. Designed to be darkened behind a menu overlay.

### 主角皮肤表

> Produce one square transparent-background game asset spritesheet in a strict 2-by-2 grid with equal cells and generous spacing. Each cell contains exactly one complete standing top-down roguelite player character, facing three-quarter upward, fully visible, same body proportions and scale. Four distinct premium space-marine skins in one coherent art direction: top-left ivory-white/cyan default astronaut with rifle; top-right crimson and graphite comet striker with angular shoulder cape and twin pistols; bottom-left teal and bone-white stellar botanist with luminous organic reactor and short staff; bottom-right midnight violet eclipse operative with hood-like helmet fins and phase blade. Rich sculpted armor details, subtle glows, crisp silhouettes, painterly game illustration, dark-navy/ivory palette with controlled accent colors. Transparent outside characters, no scenery, no shadows touching neighboring cells, no labels/text/logos/watermark. Ensure all four characters fit completely inside their own quadrant and are easy to crop by exact quarters.

### 武器图标表

> Create one square transparent-background game icon spritesheet in a strict 3 by 3 grid. Equal clear cells with generous padding and exactly one isolated weapon object centered in each cell, front/three-quarter view, consistent scale and polished premium sci-fi roguelite illustration style. Cell order left-to-right, top-to-bottom: (1) elegant ivory/cyan energy sword with long blade; (2) compact precision rifle in navy, ivory, cyan; (3) chunky double-barrel scattergun, navy/ivory with orange muzzle detail; (4) small rotating orbital sentry drone with cyan core; (5) long beam-lattice cannon, ivory with cyan emitter; (6) floating arcane plasma orb enclosed in metallic ring; (7) crystalline frost lance with cyan ice prongs; (8) starfall recurve bow with gold/cyan energy string; (9) pair of compact void pistols in midnight violet and cyan. Color palette navy blue, ivory metal, cyan luminous core, occasional restrained amber/violet. Highly detailed crisp silhouette, attractive readable inventory icon, slight soft glow contained within each cell. Transparent background, no text, no labels, no borders, no logos, no watermark. Keep every weapon entirely inside its own exact third-by-third cell, separated from neighbors by empty transparent margins.

### 战斗特效表

> Create one square transparent-background combat VFX spritesheet for a stylish top-down sci-fi roguelite. Strict 2 by 2 equal quadrants, exactly one large isolated effect centered in each cell with safe padding and no overlap. Top-left: brilliant cyan plasma impact burst with a sharp crystalline center, fragmented angular energy shards and a thin expanding ring. Top-right: broad ivory-and-hot-cyan sword slash arc sweeping diagonally, with 3 clean tapered speed trails and tiny sparks. Bottom-left: violet void-rift detonation, circular warped space lens with dark center, luminous purple rim and small particles. Bottom-right: golden starfall strike hitting the ground, bright vertical meteor core and layered hexagonal shockwave ring with cyan-white sparks. Bold readable silhouettes, elegant illustrated game VFX, high detail, controlled glow, strong contrast on transparent background, crisp edge shapes, not smoky or noisy. All content stays inside its quadrant. No scenery, text, symbols, borders, labels, logos, watermark.

### 掉落物表

> Create one square transparent-background 2-by-2 grid of collectible pickup icons for a polished sci-fi roguelite set on Mars. Four equal isolated cells, one attractive floating item centered in each with generous transparent padding: top-left a luminous teal experience crystal with three orbiting shards; top-right a compact pink-red medical canister with a clean white medical cross-shaped light, not text; bottom-left a faceted cyan shield prism with a clear hexagonal protective halo; bottom-right a pair of warm amber-white armor plates with a tiny cyan core. Unified deep-space visual direction: dark navy metal, ivory accents, cyan emission, restrained magenta/gold for rarity coding, crisp detailed hand-painted 3D game icon, readable at small size, elegant soft bloom, sharp silhouette. Transparent background only; no floor shadows, no cell backgrounds, no overlap, no labels/text, no borders, no logos, no watermark.
