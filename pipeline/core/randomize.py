"""随机化: 由配置的取值范围, 确定性地采样出一帧的 SceneSpec。

种子策略: rng = Random(seed * 1_000_003 + frame_id), 因此 (seed, frame_id) 唯一决定一帧,
可完全复现, 便于断点续跑与 train/val 稳定划分。
"""

import random

from .layout import grid_cells, obb_overlap
from .spec import CameraPose, Lights, Placement, SceneSpec


def _u(rng, lo, hi):
    return rng.uniform(lo, hi)


def _weighted_choice(rng, weights):
    """从 {key: 权重} 里按权重取一个 key。"""
    items = list(weights.items())
    total = sum(w for _, w in items)
    r = rng.uniform(0, total)
    acc = 0.0
    for k, w in items:
        acc += w
        if r <= acc:
            return k
    return items[-1][0]


def _palette(pl, registry):
    """把 composition/sku_choices 归一成 {sku: 权重}(作为可用品种与相对比例)。"""
    comp = pl.get("composition")
    if isinstance(comp, dict) and comp:
        pal = {n: float(c) for n, c in comp.items() if n in registry and c > 0}
        if pal:
            return pal
    if isinstance(comp, list) and comp:
        pal = {}
        for n in comp:
            if n in registry:
                pal[n] = pal.get(n, 0.0) + 1.0
        if pal:
            return pal
    choices = pl.get("sku_choices") or sorted(registry.keys())
    return {c: 1.0 for c in choices if c in registry}


def _scatter_skus(rng, pl, palette, registry, n_cells):
    """散摆模式的选品: dict 组成则按显式条数, 否则按 count_per_layer 随机数量。"""
    comp = pl.get("composition")
    if isinstance(comp, dict) and comp:
        want = [n for n, c in comp.items() for _ in range(int(c)) if n in registry]
        rng.shuffle(want)
        return want[:n_cells]
    lo, hi = pl["count_per_layer"]
    count = min(rng.randint(lo, hi), n_cells)
    return [_weighted_choice(rng, palette) for _ in range(count)]


def sample_scene(cfg, frame_id, sku_registry, board_length_x, board_width_y):
    """采样一帧。

    sku_registry: {name: {"length_x": m, "width_y": m, ...}}。
    board_length_x/width_y: 最终确定的板面长宽(米)。
    """
    seed = int(cfg["dataset"]["seed"])
    rng = random.Random(seed * 1_000_003 + frame_id)

    pl = cfg["placement"]
    palette = _palette(pl, sku_registry)                # {sku: 权重}
    if not palette:
        raise ValueError("没有可用 SKU(sku_registry 为空或 sku_choices/composition 不匹配)")
    layer = rng.choice(pl["layers"])

    # 每帧随机一种摆放风格: dense 密排对齐 / mixed 成排+离群 / scatter 大角度散摆
    arrangement = _weighted_choice(rng, pl.get("arrangements") or {"scatter": 1.0})

    max_lx = max(sku_registry[c]["length_x"] for c in palette)
    max_wy = max(sku_registry[c]["width_y"] for c in palette)
    yl, yh = pl["yaw_deg"]

    if arrangement == "scatter":
        max_yaw = max(abs(yl), abs(yh))
        gap, edge, jit = pl["gap_m"], pl["edge_margin_m"], pl["pos_jitter_m"]
        cells = grid_cells(board_length_x, board_width_y, max_lx, max_wy, max_yaw, gap, edge)
        skus_for_cells = _scatter_skus(rng, pl, palette, sku_registry, len(cells))

        def yaw_fn():
            return _u(rng, yl, yh)
    else:
        d = pl.get("dense", {})
        base_yaw = rng.choice(d.get("base_yaw_deg", [0.0]))
        jit_deg = d.get("yaw_jitter_deg", 4.0)
        gap = d.get("gap_m", 0.006)
        edge = d.get("edge_margin_m", 0.015)
        jit = d.get("pos_jitter_m", 0.004)
        # base_yaw≈±90 时长边沿 Y, 建格需交换长宽
        gl, gw = (max_wy, max_lx) if abs((base_yaw % 180) - 90) < 45 else (max_lx, max_wy)
        cells = grid_cells(board_length_x, board_width_y, gl, gw, jit_deg, gap, edge)
        lo_f, hi_f = d.get("fill_ratio", [0.6, 1.0])
        count = min(len(cells), max(1, round(_u(rng, lo_f, hi_f) * len(cells))))
        skus_for_cells = [_weighted_choice(rng, palette) for _ in range(count)]
        ofrac = d.get("outlier_frac", 0.15) if arrangement == "mixed" else 0.0

        def yaw_fn():
            if ofrac and rng.random() < ofrac:
                return _u(rng, yl, yh)                  # 少数离群: 大角度
            return base_yaw + _u(rng, -jit_deg, jit_deg)

    chosen = rng.sample(cells, len(skus_for_cells)) if skus_for_cells else []
    placements = []
    placed_obb = []  # (cx,cy,lx,ly,yaw) 已接受的烟盒, 用于碰撞检测
    for (cx, cy), sku in zip(chosen, skus_for_cells):
        lx = sku_registry[sku]["length_x"]
        wy = sku_registry[sku]["width_y"]
        # 抖动+偏航若与已放置的重叠(要求至少间隔 gap)则重试; 再不行退回格心;
        # 连格心都撞就丢弃本条 —— 宁可少放, 绝不重叠。
        best = None
        for attempt in range(24):
            if attempt < 20:
                x = cx + _u(rng, -jit, jit)
                y = cy + _u(rng, -jit, jit)
            else:
                x, y = cx, cy                          # 兜底: 回到格心
            cand = (x, y, lx, wy, yaw_fn())
            if not any(obb_overlap(cand, o, margin=gap) for o in placed_obb):
                best = cand
                break
        if best is None:
            continue
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
