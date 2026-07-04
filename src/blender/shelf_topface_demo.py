"""货架场景 + 俯视机位: 条烟绕 Z 轴多角度(底面贴板), 每帧渲染并导出顶面四点标注。

在已含条烟的合并货架上运行:
    blender --background data/shelf_with_carton.blend \
        --python src/blender/shelf_topface_demo.py -- \
        --layer 2 --out output --prefix shelf_kp \
        --az -90 --el 60 --dist 0.55 --lens 35 --res 1024x1024 \
        --yaws 0 22 45 68 90 113 135

输出: 每个偏航角一张 images/<prefix>_<i>.png + labels/<prefix>_<i>.json
(单目标 schema, 可直接喂 src/verify/draw_labels.py 画 mask 叠加图)。
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime

import bpy
from mathutils import Vector

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "config"))
import camera_config as cc  # noqa: E402
from kp_lib import (  # noqa: E402
    KEYPOINT_ORDER, all_world_corners, is_occluded, place_camera,
    project, top_face_world_corners,
)


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--layer", type=int, default=2, help="条烟所在层(0=最底层)")
    p.add_argument("--out", default="output")
    p.add_argument("--prefix", default="shelf_kp")
    p.add_argument("--no-stamp", action="store_true",
                   help="关闭文件名时间戳(默认带 年月日-时分秒, 防止覆盖历史结果)")
    p.add_argument("--res", default="1024x1024")
    p.add_argument("--az", type=float, default=-90.0, help="相机方位角(度), -90=正前(-Y)")
    p.add_argument("--el", type=float, default=60.0, help="相机仰角(度), 越大越俯视")
    p.add_argument("--dist", type=float, default=0.55, help="相机到目标距离(m)")
    p.add_argument("--lens", type=float, default=35.0)
    p.add_argument("--camera-config", default="",
                   help="相机配置 json; 给定则用其分辨率/FOV/安装角(覆盖 --res/--el/--lens)")
    p.add_argument("--overscan", type=int, default=0,
                   help="每边多渲的像素数(需配合 camera-config); 加畸变后裁回, 消除边角黑边")
    p.add_argument("--yaws", type=float, nargs="*",
                   default=[0, 22, 45, 68, 90, 113, 135], help="条烟绕 Z 的偏航角列表(度)")
    return p.parse_args(argv)


def find_carton():
    cs = [o for o in bpy.data.objects
          if o.type == "MESH" and ("liqun" in o.name.lower() or "carton" in o.name.lower())]
    if not cs:
        raise SystemExit("[ERR] 场景里没找到条烟")
    return cs[0]


def board_top_center(layer):
    boards = sorted([o for o in bpy.data.objects if o.name.startswith("Shelf_Board_")],
                    key=lambda o: o.location.z)
    layer = max(0, min(layer, len(boards) - 1))
    bd = boards[layer]
    cs = [bd.matrix_world @ Vector(c) for c in bd.bound_box]
    return (sum(c.x for c in cs) / 8.0, sum(c.y for c in cs) / 8.0, max(c.z for c in cs))


def set_yaw_on_board(obj, yaw_deg, cx, cy, top_z):
    """只绕 Z 转(底面保持贴板), 再把包围盒中心对准板心、底面落到板面。"""
    obj.rotation_euler = (0.0, 0.0, math.radians(yaw_deg))
    bpy.context.view_layer.update()
    cs = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    cxw = sum(c.x for c in cs) / 8.0
    cyw = sum(c.y for c in cs) / 8.0
    zmin = min(c.z for c in cs)
    obj.location.x += cx - cxw
    obj.location.y += cy - cyw
    obj.location.z += top_z - zmin
    bpy.context.view_layer.update()


def annotate(scene, cam, obj, rx, ry):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    kps = []
    for i, wp in enumerate(top_face_world_corners(obj, method="up")):
        px, py, _d, in_frame = project(scene, cam, wp, rx, ry)
        occ = is_occluded(depsgraph, scene, cam.location, wp)
        kps.append({"id": i, "x": round(px, 2), "y": round(py, 2),
                    "in_frame": in_frame, "occluded": occ,
                    "visible": bool(in_frame and not occ),
                    "world": [round(v, 5) for v in wp]})
    xs, ys = [], []
    for wp in all_world_corners(obj):
        px, py, _dd, _f = project(scene, cam, wp, rx, ry)
        xs.append(px)
        ys.append(py)
    bbox = {"x_min": round(min(xs), 2), "y_min": round(min(ys), 2),
            "x_max": round(max(xs), 2), "y_max": round(max(ys), 2)}
    return kps, bbox


def main():
    args = parse_args()
    out_root = os.path.abspath(args.out)
    os.makedirs(os.path.join(out_root, "images"), exist_ok=True)
    os.makedirs(os.path.join(out_root, "labels"), exist_ok=True)

    scene = bpy.context.scene
    scene.render.image_settings.file_format = "PNG"

    stamp = "" if args.no_stamp else datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = args.prefix if args.no_stamp else f"{args.prefix}_{stamp}"

    carton = find_carton()
    cx, cy, top_z = board_top_center(args.layer)
    target = Vector((cx, cy, top_z + 0.03))

    if args.camera_config:
        cfg = cc.load(os.path.abspath(args.camera_config))
        base_w, base_h = cc.resolution(cfg)
        render_cfg = cc.overscanned(cfg, args.overscan)   # 外扩渲染(margin=0 时原样)
        rx, ry = cc.resolution(render_cfg)
        cam = next((o for o in bpy.data.objects if o.type == "CAMERA"), None)
        if cam is None:
            cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
            bpy.context.collection.objects.link(cam)
        cc.place_camera_from_config(cam, render_cfg, target, args.dist)
        print(f"[INFO] camera from config: base={base_w}x{base_h} render={rx}x{ry} "
              f"overscan={args.overscan} from {args.camera_config}")
    else:
        rx, ry = (int(v) for v in args.res.lower().split("x"))
        scene.render.resolution_x, scene.render.resolution_y = rx, ry
        scene.render.resolution_percentage = 100
        base_w, base_h = rx, ry
        cam = place_camera(target, args.az, args.el, args.dist, args.lens)

    names = []
    for i, yaw in enumerate(args.yaws):
        set_yaw_on_board(carton, yaw, cx, cy, top_z)
        name = f"{prefix}_{i:02d}"
        names.append(name)
        img_rel = os.path.join("images", f"{name}.png")
        scene.render.filepath = os.path.join(out_root, img_rel)
        bpy.ops.render.render(write_still=True)

        kps, bbox = annotate(scene, cam, carton, rx, ry)
        data = {
            "image": img_rel, "width": rx, "height": ry, "pack": carton.name,
            "overscan_margin": args.overscan, "base_width": base_w, "base_height": base_h,
            "yaw_deg": yaw, "keypoint_order": KEYPOINT_ORDER,
            "top_face_keypoints": kps, "bbox_2d": bbox,
            "camera": {"location": [round(v, 5) for v in cam.location],
                       "az": args.az, "el": args.el, "dist": args.dist, "lens": args.lens},
        }
        with open(os.path.join(out_root, "labels", f"{name}.json"), "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        vis = sum(1 for k in kps if k["visible"])
        print(f"[INFO] {name}: yaw={yaw:.0f} visible={vis}/4 -> {img_rel}")

    cfg_arg = args.camera_config or "config/camera.json"
    print("\n[NEXT] 本轮生成 (时间戳=%s):" % (stamp or "无"))
    for n in names:
        print(f"  python3 src/verify/apply_distortion.py --config {cfg_arg} --out {args.out} --name {n}")
        print(f"  python3 src/verify/draw_labels.py --out {args.out} --name {n}_dist")
        if args.overscan > 0:
            print(f"  python3 src/verify/draw_labels.py --out {args.out} --name {n}_ideal   # 640x480无畸变原图")


if __name__ == "__main__":
    main()
