"""导入一个 glb 并渲染预览图, 用于快速验证外观。

    blender --background --python scripts/preview_glb.py -- --glb data/liqun/liqun.glb \
        --out output/debug/liqun_preview.png --az 40 --el 25
"""
import argparse
import os
import sys

import bpy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "blender"))
from kp_lib import (  # noqa: E402
    all_world_corners, ensure_light, place_camera, set_engine, setup_world, world_center,
)
import mathutils  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--glb", required=True)
    p.add_argument("--out", default="output/debug/glb_preview.png")
    p.add_argument("--az", type=float, default=40.0)
    p.add_argument("--el", type=float, default=25.0)
    p.add_argument("--res", default="1024x1024")
    return p.parse_args(argv)


def main():
    args = parse_args()
    rx, ry = (int(v) for v in args.res.lower().split("x"))

    # 清空默认场景
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(args.glb))

    bpy.context.view_layer.update()
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    print(f"[PREVIEW] 导入网格数 = {len(meshes)}: {[o.name for o in meshes]}")
    if not meshes:
        raise SystemExit("[PREVIEW] glb 里没有网格")
    for o in meshes:
        wc = all_world_corners(o)
        xs2 = [p.x for p in wc]; ys2 = [p.y for p in wc]; zs2 = [p.z for p in wc]
        print(f"[PREVIEW]   {o.name} world bbox x[{min(xs2):.3f},{max(xs2):.3f}] "
              f"y[{min(ys2):.3f},{max(ys2):.3f}] z[{min(zs2):.3f},{max(zs2):.3f}] "
              f"scale={tuple(round(s,4) for s in o.matrix_world.to_scale())}")

    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = rx, ry
    scene.render.image_settings.file_format = "PNG"
    set_engine(scene, "EEVEE")
    setup_world("grey")
    ensure_light(energy=40.0, location=(0.4, -0.4, 0.6), size=0.6)

    allc = [c for o in meshes for c in all_world_corners(o)]
    xs = [p.x for p in allc]; ys = [p.y for p in allc]; zs = [p.z for p in allc]
    center = mathutils.Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2))
    extent = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    cam = place_camera(center, args.az, args.el, extent * 2.2, lens=50.0)
    cam.data.clip_end = max(1000.0, extent * 100)
    print(f"[PREVIEW] center={tuple(round(v,3) for v in center)} extent={extent:.3f} "
          f"cam={tuple(round(v,3) for v in cam.location)}")

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print(f"[PREVIEW] 渲染 -> {out}")


if __name__ == "__main__":
    main()
