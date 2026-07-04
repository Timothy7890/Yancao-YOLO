"""随机化: 由配置的取值范围, 确定性地采样出一帧的 SceneSpec。

种子策略: rng = Random(seed * 1_000_003 + frame_id), 因此 (seed, frame_id) 唯一决定一帧,
可完全复现, 便于断点续跑与 train/val 稳定划分。
"""

import random

from .layout import grid_cells, obb_overlap
from .spec import CameraPose, Lights, Placement, SceneSpec


def _u(rng, lo, hi):
    return rng.uniform(lo, hi)


def sample_scene(cfg, frame_id, sku_registry, board_length_x, board_width_y):
    """采样一帧。

    sku_registry: {name: {"length_x": m, "width_y": m, ...}}。
    board_length_x/width_y: 最终确定的板面长宽(米)。
    """
    seed = int(cfg["dataset"]["seed"])
    rng = random.Random(seed * 1_000_003 + frame_id)

    pl = cfg["placement"]
    choices = pl["sku_choices"] or sorted(sku_registry.keys())
    choices = [c for c in choices if c in sku_registry]
    if not choices:
        raise ValueError("没有可用 SKU(sku_registry 为空或 sku_choices 不匹配)")

    max_yaw = max(abs(pl["yaw_deg"][0]), abs(pl["yaw_deg"][1]))
    # 用候选 SKU 中最大底面尺寸建格, 保证任何 SKU 都放得下
    max_lx = max(sku_registry[c]["length_x"] for c in choices)
    max_wy = max(sku_registry[c]["width_y"] for c in choices)
    cells = grid_cells(board_length_x, board_width_y, max_lx, max_wy,
                       max_yaw, pl["gap_m"], pl["edge_margin_m"])

    layer = rng.choice(pl["layers"])

    # 显式组成: {name: count} 或 [name, name, ...]; 否则回退到"随机数量+随机品种"
    comp = pl.get("composition")
    if comp:
        if isinstance(comp, dict):
            want = [n for n, c in comp.items() for _ in range(int(c)) if n in sku_registry]
        else:
            want = [n for n in comp if n in sku_registry]
        rng.shuffle(want)
        skus_for_cells = want[:len(cells)]
    else:
        lo, hi = pl["count_per_layer"]
        count = min(rng.randint(lo, hi), len(cells))
        skus_for_cells = [rng.choice(choices) for _ in range(count)]

    chosen = rng.sample(cells, len(skus_for_cells)) if skus_for_cells else []
    jit = pl["pos_jitter_m"]
    gap = pl["gap_m"]
    placements = []
    placed_obb = []  # (cx,cy,lx,ly,yaw) 已接受的烟盒, 用于碰撞检测
    for (cx, cy), sku in zip(chosen, skus_for_cells):
        lx = sku_registry[sku]["length_x"]
        wy = sku_registry[sku]["width_y"]
        # 抖动+偏航若与已放置的重叠(要求至少间隔 gap)则重试; 再不行退回格心;
        # 连格心都撞(极端偏航/格子紧)就丢弃本条 —— 宁可少放, 绝不重叠。
        best = None
        for attempt in range(24):
            if attempt < 20:
                x = cx + _u(rng, -jit, jit)
                y = cy + _u(rng, -jit, jit)
            else:
                x, y = cx, cy                          # 兜底: 回到格心
            yaw = _u(rng, pl["yaw_deg"][0], pl["yaw_deg"][1])
            cand = (x, y, lx, wy, yaw)
            if not any(obb_overlap(cand, o, margin=gap) for o in placed_obb):
                best = cand
                break
        if best is None:
            continue                                   # 放不下, 跳过这条烟盒
        placed_obb.append(best)
        placements.append(Placement(sku=sku, x=best[0], y=best[1], yaw_deg=best[4]))

    cam = cfg["camera"]
    cj = cam["jitter"]
    camera = CameraPose(
        distance=cam["distance"] + _u(rng, -cj["distance_m"], cj["distance_m"]),
        yaw_off_deg=_u(rng, -cj["yaw_deg"], cj["yaw_deg"]),
        pitch_off_deg=_u(rng, -cj["pitch_deg"], cj["pitch_deg"]),
        pos_off=(_u(rng, -cj["pos_m"], cj["pos_m"]),
                 _u(rng, -cj["pos_m"], cj["pos_m"]),
                 _u(rng, -cj["pos_m"], cj["pos_m"])),
    )

    lg = cfg["lights"]
    lights = Lights(
        top_power=_u(rng, lg["top_power"][0], lg["top_power"][1]),
        ambient=_u(rng, lg["ambient"][0], lg["ambient"][1]),
    )

    return SceneSpec(frame_id=frame_id, seed=seed, layer=layer,
                     camera=camera, lights=lights, placements=placements)
