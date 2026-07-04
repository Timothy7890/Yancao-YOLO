"""入口(Blender): 烘"基础场景" —— 确定货架板长宽 + 默认相机, 存成 base_scene.blend。

这是需要"手工确认"的两处的落盘工具: 板长宽 与 相机默认位姿(取自 config/camera.json 安装角)。
若 data/jiazi 没有货架, 会用 shelf.generate 参数生成并存到 shelf_blend。

用法:
    /Applications/Blender.app/Contents/MacOS/Blender --background --python \
        pipeline/runners/make_base_scene.py -- [--config pipeline/config/dataset.json] [--preview out.png]
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from pipeline.blender import env                      # noqa: E402

env.bootstrap()

import bpy                                            # noqa: E402

from pipeline.blender import scene as sc              # noqa: E402
from pipeline.core import config                      # noqa: E402


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=config.DEFAULT_CONFIG)
    ap.add_argument("--preview", default="", help="可选: 存一张预览 png")
    return ap.parse_args(argv)


def main():
    args = parse_args()
    cfg = config.load(args.config)
    paths = config.resolved_paths(cfg)

    info = sc.build_base(cfg, paths)

    if info["generated"]:
        shelf_out = paths["shelf_blend"]
        os.makedirs(os.path.dirname(shelf_out), exist_ok=True)
        # 只存货架(当前场景含相机/灯, 也一并存, 作为可复用货架资产)
        bpy.ops.wm.save_as_mainfile(filepath=shelf_out)
        print(f"[base] 货架已生成并存 -> {shelf_out}")

    base_out = paths["base_scene"]
    os.makedirs(os.path.dirname(base_out), exist_ok=True)
    try:
        bpy.ops.file.pack_all()
    except RuntimeError as e:
        print(f"[warn] pack_all: {e}")
    bpy.ops.wm.save_as_mainfile(filepath=base_out)
    print(f"[base] 基础场景 -> {base_out}  (shelf_mode={info['shelf_mode']})")

    if args.preview:
        out = os.path.abspath(args.preview)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        bpy.context.scene.render.filepath = out
        bpy.context.scene.render.image_settings.file_format = "PNG"
        bpy.ops.render.render(write_still=True)
        print(f"[base] 预览 -> {out}")


if __name__ == "__main__":
    main()
