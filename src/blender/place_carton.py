"""把一条(或后续多条)烟躺放到货架指定层板上并渲染预览。

用法 (货架场景已含相机/灯/地面):
    blender --background data/shelf.blend --python src/blender/place_carton.py -- \
        --carton data/liqun_carton.blend --layer 2 \
        --out output/images/shelf_one_carton.png

约定:
  - --layer 从 0 计, 0=最底层; "第三层" => --layer 2。
  - 条烟躺放: 最短局部轴竖直(最大面贴板), 长轴沿货架宽度(X)摆放, 顶面朝上。
"""

import argparse
import math
import os
import sys

import bpy
from mathutils import Vector


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--carton", default="data/liqun_carton.blend", help="条烟 .blend")
    p.add_argument("--layer", type=int, default=2, help="放到第几层板(0=最底层)")
    p.add_argument("--out", default="output/images/shelf_one_carton.png")
    p.add_argument("--yoff", type=float, default=-0.12, help="沿深度方向偏移(相机在 -Y, 负值靠前)")
    p.add_argument("--save", default="", help="另存合并后的 .blend 路径(留空则不存)")
    return p.parse_args(argv)


def append_carton(path):
    path = os.path.abspath(path)
    before = set(bpy.data.objects)
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = [n for n in src.objects if "liqun" in n.lower() or "carton" in n.lower()]
        if not dst.objects:
            dst.objects = list(src.objects)
    linked = [o for o in bpy.data.objects if o not in before]
    for o in linked:
        bpy.context.collection.objects.link(o)
    mesh = [o for o in linked if o.type == "MESH"]
    if not mesh:
        raise SystemExit("[ERR] 条烟文件里没找到 MESH")
    return max(mesh, key=lambda o: o.dimensions.x * o.dimensions.y * o.dimensions.z)


def lay_flat_along_width(obj):
    """最短轴竖直(大面贴板) + 长轴沿世界 X(货架宽度)。"""
    dims = list(obj.dimensions)
    short = min(range(3), key=lambda i: dims[i])
    if short == 0:
        rx, ry = 0.0, math.radians(90)
    elif short == 1:
        rx, ry = math.radians(90), 0.0
    else:
        rx, ry = 0.0, 0.0
    obj.rotation_euler = (rx, ry, 0.0)
    bpy.context.view_layer.update()
    # 躺平后, 让最长的水平边沿 X: 若当前 Y 跨度 > X 跨度, 再绕 Z 转 90°
    d = obj.dimensions
    if d.y > d.x:
        obj.rotation_euler = (rx, ry, math.radians(90))
        bpy.context.view_layer.update()


def board_top_center(layer):
    boards = sorted([o for o in bpy.data.objects if o.name.startswith("Shelf_Board_")],
                    key=lambda o: o.location.z)
    if not boards:
        raise SystemExit("[ERR] 场景里没有 Shelf_Board_* 隔板")
    layer = max(0, min(layer, len(boards) - 1))
    bd = boards[layer]
    corners = [bd.matrix_world @ Vector(c) for c in bd.bound_box]
    top_z = max(c.z for c in corners)
    cx = sum(c.x for c in corners) / 8.0
    cy = sum(c.y for c in corners) / 8.0
    return bd, cx, cy, top_z


def place_on_board(obj, cx, cy, top_z, yoff):
    zmin = min((obj.matrix_world @ Vector(c)).z for c in obj.bound_box)
    obj.location.x += cx - obj.location.x
    obj.location.y += cy + yoff - obj.location.y
    obj.location.z += (top_z - zmin)
    bpy.context.view_layer.update()


def main():
    args = parse_args()
    carton = append_carton(args.carton)
    lay_flat_along_width(carton)
    bd, cx, cy, top_z = board_top_center(args.layer)
    place_on_board(carton, cx, cy, top_z, args.yoff)
    print(f"[INFO] carton {carton.name!r} on {bd.name!r} top_z={top_z:.3f} "
          f"loc={tuple(round(v,3) for v in carton.location)} "
          f"dims={tuple(round(d,3) for d in carton.dimensions)}")

    scene = bpy.context.scene
    if scene.camera is None:
        raise SystemExit("[ERR] 场景没有相机")
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    scene.render.filepath = out
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print(f"[INFO] rendered -> {out}")

    if args.save:
        save = os.path.abspath(args.save)
        os.makedirs(os.path.dirname(save), exist_ok=True)
        try:
            bpy.ops.file.pack_all()          # 贴图打包进 blend, 自包含
        except RuntimeError as e:
            print(f"[WARN] pack_all: {e}")
        bpy.ops.wm.save_as_mainfile(filepath=save)
        print(f"[INFO] merged blend -> {save}")


if __name__ == "__main__":
    main()
