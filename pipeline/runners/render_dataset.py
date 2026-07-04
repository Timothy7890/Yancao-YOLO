"""入口(Blender): 无头批量渲染。

每帧: 采样 SceneSpec -> 实现场景 -> 渲染(外扩)理想图 -> 取几何标注 -> 写 frame_%06d.{png,json}。
图像畸变与 YOLO 导出、train/val 划分交给 build_labels.py(系统 Python)后处理。

用法:
    /Applications/Blender.app/Contents/MacOS/Blender --background --python \
        pipeline/runners/render_dataset.py -- [--config ...] [--num 20] [--start 0]
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from pipeline.blender import env                      # noqa: E402

env.bootstrap()

import bpy                                            # noqa: E402

from pipeline.blender import annotate, assets, realize, scene as sc   # noqa: E402
from pipeline.core import camera as cammod            # noqa: E402
from pipeline.core import config, randomize           # noqa: E402


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=config.DEFAULT_CONFIG)
    ap.add_argument("--num", type=int, default=-1, help="渲染帧数, 默认取配置 dataset.num_frames")
    ap.add_argument("--start", type=int, default=0, help="起始 frame_id(便于断点续跑)")
    return ap.parse_args(argv)


def prepare(cfg, paths):
    """有 base_scene 就打开, 否则现搭。之后 append SKU 模板并返回登记表。"""
    base = paths["base_scene"]
    if os.path.exists(base):
        bpy.ops.wm.open_mainfile(filepath=base)
        # 清掉可能存在的历史实例
        assets.clear_instances()
    else:
        sc.build_base(cfg, paths)
    return assets.build_registry(paths["sku_dir"])


def main():
    args = parse_args()
    cfg = config.load(args.config)
    paths = config.resolved_paths(cfg)
    num = args.num if args.num >= 0 else cfg["dataset"]["num_frames"]

    registry = prepare(cfg, paths)
    if not registry:
        raise SystemExit(f"[render] 没有找到 SKU: {paths['sku_dir']}")
    print(f"[render] SKU 登记: {list(registry.keys())}")

    frames_dir = os.path.join(paths["out_dir"], "frames")
    os.makedirs(frames_dir, exist_ok=True)

    shelf = cfg["shelf"]
    board_l, board_w = shelf["board_length_x"], shelf["board_width_y"]
    base_cam_cfg = cammod.load(paths["camera_config"])   # 基础(未外扩)内参+畸变, 供后处理

    scene = bpy.context.scene
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"

    for i in range(args.start, args.start + num):
        spec = randomize.sample_scene(cfg, i, registry, board_l, board_w)
        placed, cam, base_wh, render_wh = realize.realize(cfg, spec, registry, paths["camera_config"])

        img_name = f"frame_{i:06d}.png"
        scene.render.filepath = os.path.join(frames_dir, img_name)
        bpy.ops.render.render(write_still=True)

        objs = annotate.annotate_frame(cfg, placed, cam, render_wh)
        meta = {
            "frame_id": i,
            "seed": spec.seed,
            "layer": spec.layer,
            "image": img_name,
            "base_width": base_wh[0], "base_height": base_wh[1],
            "render_width": render_wh[0], "render_height": render_wh[1],
            "overscan_margin": cfg["camera"]["overscan"],
            "camera": base_cam_cfg,
            "spec": spec.to_dict(),
            "objects": objs,
        }
        with open(os.path.join(frames_dir, f"frame_{i:06d}.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"[render] frame {i}: {len(objs)} packs -> {img_name}")

    print(f"[render] 完成 {num} 帧 -> {frames_dir}")


if __name__ == "__main__":
    main()
