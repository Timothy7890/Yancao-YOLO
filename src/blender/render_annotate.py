"""Phase 1: 纯背景下渲染单个烟盒 + 自动导出顶面 4 角点标注 (JSON).

在 Blender 无头模式下运行:
    blender --background data/xxx.blend --python src/blender/render_annotate.py -- \
        --out output --name demo_000 --res 1024x1024 --engine EEVEE \
        --azimuth 35 --elevation 30 --bg grey

核心机制:
  1) 在烟盒的"局部坐标系"里锁定顶面(lid)的 4 个角点 —— 长轴 + 端的 4 个 bbox 角,
     并按剩余两轴的符号固定排序。这样即使以后把盒子旋转/躺下, 关键点身份也不变。
  2) 用 world_to_camera_view 把这 4 个世界坐标点投影到像素坐标。
  3) 做 in-frame / in-front / 遮挡(raycast) 判断, 得到每个点的可见性。
  4) 导出 JSON (图像尺寸 + 4 角点像素坐标 + 可见性 + 整体 2D bbox + 相机参数)。
"""

import argparse
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kp_lib import (  # noqa: E402
    KEYPOINT_ORDER, all_world_corners, ensure_light, is_occluded, place_camera,
    project, set_engine, setup_world, top_face_world_corners, world_center,
)


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="output", help="输出根目录")
    p.add_argument("--name", default="demo_000", help="输出文件基名")
    p.add_argument("--res", default="1024x1024", help="分辨率 WxH")
    p.add_argument("--engine", default="EEVEE", choices=["EEVEE", "CYCLES"])
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--pack", default="", help="烟盒对象名, 留空则自动取最大 MESH")
    p.add_argument("--azimuth", type=float, default=35.0, help="相机方位角(度)")
    p.add_argument("--elevation", type=float, default=30.0, help="相机仰角(度)")
    p.add_argument("--distance", type=float, default=0.0, help="相机距离(m), 0=按物体尺寸自动")
    p.add_argument("--lens", type=float, default=50.0, help="镜头焦距(mm)")
    p.add_argument("--bg", default="grey", choices=["grey", "white", "transparent"])
    p.add_argument("--topface", default="face", choices=["face", "aabb"],
                   help="顶面取点方式: face=真实顶盖多边形(默认), aabb=旧版包围盒(汇报对照)")
    return p.parse_args(argv)


def find_pack(name):
    if name:
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise SystemExit(f"[ERR] 找不到对象 {name!r}")
        return obj
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("[ERR] 场景里没有 MESH 对象")
    # 取体积最大的那个当烟盒
    def vol(o):
        d = o.dimensions
        return d.x * d.y * d.z
    return max(meshes, key=vol)


def main():
    args = parse_args()
    rx, ry = (int(v) for v in args.res.lower().split("x"))
    out_root = os.path.abspath(args.out)
    img_path = os.path.join(out_root, "images", f"{args.name}.png")
    lbl_path = os.path.join(out_root, "labels", f"{args.name}.json")
    os.makedirs(os.path.dirname(img_path), exist_ok=True)
    os.makedirs(os.path.dirname(lbl_path), exist_ok=True)

    scene = bpy.context.scene
    scene.render.resolution_x = rx
    scene.render.resolution_y = ry
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"

    set_engine(scene, args.engine, args.samples)
    setup_world(args.bg)
    ensure_light()

    pack = find_pack(args.pack)
    print(f"[INFO] pack = {pack.name!r} dims={tuple(round(d,4) for d in pack.dimensions)}")

    center = world_center(pack)
    max_dim = max(pack.dimensions)
    distance = args.distance if args.distance > 0 else max_dim * 4.0
    cam = place_camera(center, args.azimuth, args.elevation, distance, args.lens)

    # 渲染
    scene.render.filepath = img_path
    bpy.ops.render.render(write_still=True)
    print(f"[INFO] rendered -> {img_path}")

    # 顶面 4 角点(世界坐标)
    top_world = top_face_world_corners(pack, method=args.topface)
    print(f"[INFO] topface method = {args.topface}")

    depsgraph = bpy.context.evaluated_depsgraph_get()
    keypoints = []
    for i, wp in enumerate(top_world):
        px, py, depth, in_frame = project(scene, cam, wp, rx, ry)
        occ = is_occluded(depsgraph, scene, cam.location, wp)
        visible = bool(in_frame and not occ)
        keypoints.append({
            "id": i,
            "x": round(px, 2),
            "y": round(py, 2),
            "in_frame": in_frame,
            "occluded": occ,
            "visible": visible,
            "world": [round(v, 5) for v in wp],
        })

    # 整体 2D 包围盒(所有 8 个角投影)
    xs, ys = [], []
    for wp in all_world_corners(pack):
        px, py, _d, _f = project(scene, cam, wp, rx, ry)
        xs.append(px)
        ys.append(py)
    bbox = {
        "x_min": round(min(xs), 2), "y_min": round(min(ys), 2),
        "x_max": round(max(xs), 2), "y_max": round(max(ys), 2),
    }

    data = {
        "image": os.path.relpath(img_path, out_root),
        "width": rx,
        "height": ry,
        "pack": pack.name,
        "keypoint_order": KEYPOINT_ORDER,
        "top_face_keypoints": keypoints,
        "bbox_2d": bbox,
        "camera": {
            "location": [round(v, 5) for v in cam.location],
            "lens_mm": cam.data.lens,
            "azimuth": args.azimuth,
            "elevation": args.elevation,
            "distance": round(distance, 5),
        },
    }
    with open(lbl_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[INFO] labels  -> {lbl_path}")
    print("[INFO] top-face keypoints (px):")
    for kp in keypoints:
        print(f"    #{kp['id']} ({kp['x']:.1f}, {kp['y']:.1f}) visible={kp['visible']}")


if __name__ == "__main__":
    main()
