"""
校验脚本：检查所有需要的图是否就位、尺寸是否对、是否有alpha通道
"""
import argparse
import sys
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = REPO_ROOT / "rgame" / "assets" / "v2"


CHECKS = [
    # (relative path, expected size WxH, 描述)
    # === P1 敌人时间形态 ===
    ("enemies/spinner_chaser_t1.png", "1024x1024", "旋刃追击者 T1 强化"),
    ("enemies/spinner_chaser_t2.png", "1024x1024", "旋刃追击者 T2 武装"),
    ("enemies/spinner_chaser_t3.png", "1024x1024", "旋刃追击者 T3 过载"),
    ("enemies/wingblade_sprinter_t1.png", "1024x1024", "翼刃突袭者 T1"),
    ("enemies/wingblade_sprinter_t2.png", "1024x1024", "翼刃突袭者 T2"),
    ("enemies/wingblade_sprinter_t3.png", "1024x1024", "翼刃突袭者 T3"),
    ("enemies/shellguard_heavy_t1.png", "1024x1024", "重甲龟卫 T1"),
    ("enemies/shellguard_heavy_t2.png", "1024x1024", "重甲龟卫 T2"),
    ("enemies/shellguard_heavy_t3.png", "1024x1024", "重甲龟卫 T3"),
    ("enemies/lantern_shooter_t1.png", "1024x1024", "提灯法师 T1"),
    ("enemies/lantern_shooter_t2.png", "1024x1024", "提灯法师 T2"),
    ("enemies/lantern_shooter_t3.png", "1024x1024", "提灯法师 T3"),
    ("enemies/multinode_spreader_t1.png", "1024x1024", "多节点散射体 T1"),
    ("enemies/multinode_spreader_t2.png", "1024x1024", "多节点散射体 T2"),
    ("enemies/multinode_spreader_t3.png", "1024x1024", "多节点散射体 T3"),
    ("enemies/minelayer_bomber_t1.png", "1024x1024", "爆破哥布林 T1"),
    ("enemies/minelayer_bomber_t2.png", "1024x1024", "爆破哥布林 T2"),
    ("enemies/minelayer_bomber_t3.png", "1024x1024", "爆破哥布林 T3"),
    ("enemies/crystal_sniper_t1.png", "1024x1024", "水晶狙击兵 T1"),
    ("enemies/crystal_sniper_t2.png", "1024x1024", "水晶狙击兵 T2"),
    ("enemies/crystal_sniper_t3.png", "1024x1024", "水晶狙击兵 T3"),
    # === P1 敌人破损 ===
    ("enemies/spinner_chaser_damage1.png", "1024x1024", "旋刃追击者 dmg1"),
    ("enemies/spinner_chaser_damage2.png", "1024x1024", "旋刃追击者 dmg2"),
    ("enemies/wingblade_sprinter_damage1.png", "1024x1024", "翼刃突袭者 dmg1"),
    ("enemies/wingblade_sprinter_damage2.png", "1024x1024", "翼刃突袭者 dmg2"),
    ("enemies/shellguard_heavy_damage1.png", "1024x1024", "重甲龟卫 dmg1"),
    ("enemies/shellguard_heavy_damage2.png", "1024x1024", "重甲龟卫 dmg2"),
    ("enemies/lantern_shooter_damage1.png", "1024x1024", "提灯法师 dmg1"),
    ("enemies/lantern_shooter_damage2.png", "1024x1024", "提灯法师 dmg2"),
    ("enemies/multinode_spreader_damage1.png", "1024x1024", "多节点散射体 dmg1"),
    ("enemies/multinode_spreader_damage2.png", "1024x1024", "多节点散射体 dmg2"),
    ("enemies/minelayer_bomber_damage1.png", "1024x1024", "爆破哥布林 dmg1"),
    ("enemies/minelayer_bomber_damage2.png", "1024x1024", "爆破哥布林 dmg2"),
    ("enemies/crystal_sniper_damage1.png", "1024x1024", "水晶狙击兵 dmg1"),
    ("enemies/crystal_sniper_damage2.png", "1024x1024", "水晶狙击兵 dmg2"),
    # === P2 玩家形态 ===
    ("player/player_nimble_sheet.png", "2048x2048", "玩家轻捷形态"),
    ("player/player_heavy_sheet.png", "2048x2048", "玩家重装形态"),
    # === P2 成就徽章 ===
    ("icons/achievements/ach_runscore.png", "64x64", "成就-单局分"),
    ("icons/achievements/ach_totalscore.png", "64x64", "成就-累计分"),
    ("icons/achievements/ach_runkill.png", "64x64", "成就-击杀数"),
    ("icons/achievements/ach_super.png", "64x64", "成就-超级猎手"),
    ("icons/achievements/ach_stage.png", "64x64", "成就-关卡通关"),
    ("icons/achievements/ach_nohit.png", "64x64", "成就-无伤"),
    ("icons/achievements/ach_bomb.png", "64x64", "成就-炸弹躲避"),
    ("icons/achievements/ach_card.png", "64x64", "成就-卡组成长"),
    # === P3 场景装饰 ===
    ("props/prop_mars_crystal.png", "128x128", "火星水晶"),
    ("props/prop_dead_robot.png", "160x160", "废弃机器人"),
    ("props/prop_energy_barrel.png", "128x128", "能源桶"),
    ("props/prop_satellite_dish.png", "192x128", "卫星接收器"),
    ("props/prop_broken_turret.png", "160x160", "损坏炮塔"),
    ("props/prop_ancient_glyph.png", "256x256", "地面符文"),
    # === P3 小投射物 ===
    ("effects/projectile_enemy_arcane_small.png", "128x128", "投射物-奥术"),
    ("effects/projectile_enemy_shard_small.png", "64x128", "投射物-晶片"),
    ("effects/projectile_enemy_rail_small.png", "32x128", "投射物-光束"),
    ("effects/projectile_boss_orb_small.png", "128x128", "投射物-Boss弹"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 RGame V2 资源")
    parser.add_argument(
        "--base",
        type=Path,
        default=DEFAULT_BASE,
        help="资源根目录，默认使用当前仓库的 rgame/assets/v2",
    )
    parser.add_argument("--quiet", action="store_true", help="只输出汇总")
    args = parser.parse_args(argv)
    base = args.base.expanduser().resolve()

    ok = 0
    miss = 0
    bad_size = 0
    no_alpha = 0
    if not args.quiet:
        print(f"资源根目录: {base}")
        print(f"{'状态':<4} {'尺寸':<11} {'Alpha':<6} {'文件':<50} 描述")
        print("-" * 110)
    for rel, expected_size, desc in CHECKS:
        p = base / rel
        if not p.exists():
            if not args.quiet:
                print(f"{'缺':<4} {'-':<11} {'-':<6} {rel:<50} {desc}")
            miss += 1
            continue
        try:
            img = Image.open(p)
            size = f"{img.width}x{img.height}"
            has_alpha = "RGBA" if img.mode == "RGBA" else f"!!{img.mode}"
            size_ok = size == expected_size
            mark = "OK" if size_ok and img.mode == "RGBA" else "!!"
            if not size_ok:
                bad_size += 1
            if img.mode != "RGBA":
                no_alpha += 1
            if size_ok and img.mode == "RGBA":
                ok += 1
            if not args.quiet:
                print(f"{mark:<4} {size:<11} {has_alpha:<6} {rel:<50} {desc}")
        except Exception as exc:
            if not args.quiet:
                print(f"??   error     -       {rel:<50} {exc}")
    if not args.quiet:
        print("-" * 110)
    print(f"OK: {ok}  缺失: {miss}  尺寸不对: {bad_size}  无Alpha: {no_alpha}  总: {len(CHECKS)}")
    return 0 if miss == 0 and bad_size == 0 and no_alpha == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
