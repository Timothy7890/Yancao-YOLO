"""Phase 2: 多条烟摆放到货架面 + 随机扰动 + 多目标顶面关键点 + 多目标遮挡 + YOLO 导出.

在 Blender 无头模式下运行:
    blender --background data/xxx.blend --python src/blender/render_scene.py -- \
        --out output --name scene_000 --rows 3 --cols 4 --seed 0 \
        --azimuth 25 --elevation 22 --engine EEVEE

要点 (相对 Phase 1 新增):
  - 由模板盒复制出 rows×cols 个实例, 网格摆放 + 位置/朝向随机扰动 + 部分倾倒;
  - 逐实例导出顶面 4 关键点, 遮挡检测针对**整个场景**(邻居/自身都算), 验证多目标可见性;
  - 输出 JSON(多目标) + YOLO-pose txt(归一化 bbox + 4 关键点可见性)。
"""

import argparse
import json
import math
import os
import random
import sys

import bpy
import mathutils

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kp_lib import (  # noqa: E402
    KEYPOINT_ORDER, all_world_corners, ensure_light, is_occluded, place_camera,
    project, set_engine, setup_world, top_face_world_corners, world_center,
)


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="output")
    p.add_argument("--name", default="scene_000")
    p.add_argument("--res", default="1280x960")
    p.add_argument("--engine", default="EEVEE", choices=["EEVEE", "CYCLES"])
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--pack", default="")
    p.add_argument("--rows", type=int, default=3, help="纵深方向行数")
    p.add_argument("--cols", type=int, default=4, help="横向列数")
    p.add_argument("--gap", type=float, default=0.12, help="相对间距(占盒尺寸比例)")
    p.add_argument("--pos-jitter", type=float, default=0.18, help="位置抖动(占盒尺寸比例)")
    p.add_argument("--yaw-jitter", type=float, default=12.0, help="偏航抖动(度)")
    p.add_argument("--knock", type=float, default=0.12, help="倾倒比例[0,1]")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--azimuth", type=float, default=25.0)
    p.add_argument("--elevation", type=float, default=22.0)
    p.add_argument("--distance", type=float, default=0.0)
    p.add_argument("--lens", type=float, default=50.0)
    p.add_argument("--bg", default="grey", choices=["grey", "white", "transparent"])
    p.add_argument("--topface", default="face", choices=["face", "aabb"])
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
    return max(meshes, key=lambda o: o.dimensions.x * o.dimensions.y * o.dimensions.z)


def world_footprint(obj):
    c = all_world_corners(obj)
    xs, ys, zs = [p.x for p in c], [p.y for p in c], [p.z for p in c]
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def add_ground(z=0.0, size=2.0):
    me = bpy.data.meshes.new("Ground")
    verts = [(-size, -size, z), (size, -size, z), (size, size, z), (-size, size, z)]
    me.from_pydata(verts, [], [(0, 1, 2, 3)])
    me.update()
    obj = bpy.data.objects.new("Ground", me)
    mat = bpy.data.materials.new("GroundMat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.32, 0.32, 0.34, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.85
    obj.data.materials.append(mat)
    bpy.context.collection.objects.link(obj)
    return obj


def place_instance(inst, tx, ty, base_quat, yaw_rad, knocked, ground_z):
    """把实例几何中心对齐到 (tx,ty), 底面落到 ground_z; 叠加偏航与可选倾倒。"""
    q = mathutils.Quaternion((0, 0, 1), yaw_rad) @ base_quat
    if knocked:
        axis = random.choice([(1, 0, 0), (0, 1, 0)])
        q = mathutils.Quaternion(axis, math.radians(random.choice([-90, 90]))) @ q
    inst.rotation_mode = "QUATERNION"
    inst.rotation_quaternion = q
    bpy.context.view_layer.update()

    c = world_center(inst)
    inst.location.x += tx - c.x
    inst.location.y += ty - c.y
    bpy.context.view_layer.update()
    zmin = min(p.z for p in all_world_corners(inst))
    inst.location.z += ground_z - zmin
    bpy.context.view_layer.update()


def build_layout(template, args):
    random.seed(args.seed)
    fx, fy, _fz = world_footprint(template)
    sx = fx * (1.0 + args.gap)
    sy = fy * (1.0 + args.gap)
    base_quat = template.matrix_world.to_quaternion()

    instances = []
    x0 = -(args.cols - 1) * sx / 2.0
    y0 = -(args.rows - 1) * sy / 2.0
    for r in range(args.rows):
        for c in range(args.cols):
            inst = template if (r == 0 and c == 0) else template.copy()
            if inst is not template:
                bpy.context.collection.objects.link(inst)
            tx = x0 + c * sx + random.uniform(-1, 1) * args.pos_jitter * fx
            ty = y0 + r * sy + random.uniform(-1, 1) * args.pos_jitter * fy
            yaw = math.radians(random.uniform(-1, 1) * args.yaw_jitter)
            knocked = random.random() < args.knock
            place_instance(inst, tx, ty, base_quat, yaw, knocked, ground_z=0.0)
            instances.append(inst)
    return instances


def annotate_instance(inst, scene, cam, depsgraph, rx, ry, method):
    top_world = top_face_world_corners(inst, method=method)
    kps = []
    for i, wp in enumerate(top_world):
        px, py, _d, in_frame = project(scene, cam, wp, rx, ry)
        occ = is_occluded(depsgraph, scene, cam.location, wp)
        kps.append({
            "id": i, "x": round(px, 2), "y": round(py, 2),
            "in_frame": in_frame, "occluded": occ,
            "visible": bool(in_frame and not occ),
        })
    xs, ys, any_front = [], [], False
    for wp in all_world_corners(inst):
        px, py, depth, _f = project(scene, cam, wp, rx, ry)
        xs.append(px)
        ys.append(py)
        any_front = any_front or depth > 0.0
    bbox = {"x_min": round(min(xs), 2), "y_min": round(min(ys), 2),
            "x_max": round(max(xs), 2), "y_max": round(max(ys), 2)}
    return kps, bbox, any_front


def to_yolo_pose(kps, bbox, rx, ry, cls=0):
    """Ultralytics pose 行: cls cx cy w h (kx ky v)*4, 归一化; v: 2可见/1遮挡/0出画。"""
    x0 = max(0.0, min(bbox["x_min"], rx))
    x1 = max(0.0, min(bbox["x_max"], rx))
    y0 = max(0.0, min(bbox["y_min"], ry))
    y1 = max(0.0, min(bbox["y_max"], ry))
    w, h = x1 - x0, y1 - y0
    if w <= 1.0 or h <= 1.0:
        return None
    cx, cy = (x0 + x1) / 2.0 / rx, (y0 + y1) / 2.0 / ry
    vals = [cls, cx, cy, w / rx, h / ry]
    for kp in kps:
        if not kp["in_frame"]:
            v = 0
            kx = ky = 0.0
        else:
            v = 2 if kp["visible"] else 1
            kx = min(max(kp["x"], 0.0), rx) / rx
            ky = min(max(kp["y"], 0.0), ry) / ry
        vals += [kx, ky, v]
    return " ".join(f"{v:.6f}" if isinstance(v, float) else str(v) for v in vals)


def main():
    args = parse_args()
    rx, ry = (int(v) for v in args.res.lower().split("x"))
    out_root = os.path.abspath(args.out)
    img_path = os.path.join(out_root, "images", f"{args.name}.png")
    json_path = os.path.join(out_root, "labels", f"{args.name}.json")
    txt_path = os.path.join(out_root, "labels", f"{args.name}.txt")
    for pth in (img_path, json_path):
        os.makedirs(os.path.dirname(pth), exist_ok=True)

    scene = bpy.context.scene
    scene.render.resolution_x = rx
    scene.render.resolution_y = ry
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"

    set_engine(scene, args.engine, args.samples)
    setup_world(args.bg)

    template = find_pack(args.pack)
    instances = build_layout(template, args)
    print(f"[INFO] instances = {len(instances)}")

    add_ground(z=0.0)

    # 灯光对准阵列上方
    ensure_light(energy=60.0, location=(0.0, -0.2, 0.8), size=1.0)

    # 相机框住整个阵列
    allc = [c for inst in instances for c in all_world_corners(inst)]
    xs = [p.x for p in allc]; ys = [p.y for p in allc]; zs = [p.z for p in allc]
    center = mathutils.Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2))
    extent = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    distance = args.distance if args.distance > 0 else extent * 1.9
    cam = place_camera(center, args.azimuth, args.elevation, distance, args.lens)

    scene.render.filepath = img_path
    bpy.ops.render.render(write_still=True)
    print(f"[INFO] rendered -> {img_path}")

    depsgraph = bpy.context.evaluated_depsgraph_get()
    objects, yolo_lines = [], []
    for idx, inst in enumerate(instances):
        kps, bbox, any_front = annotate_instance(inst, scene, cam, depsgraph, rx, ry, args.topface)
        in_img = any(k["in_frame"] for k in kps) or (
            bbox["x_max"] > 0 and bbox["x_min"] < rx and bbox["y_max"] > 0 and bbox["y_min"] < ry and any_front)
        if not in_img:
            continue
        objects.append({"id": idx, "name": inst.name,
                        "top_face_keypoints": kps, "bbox_2d": bbox,
                        "n_visible_kp": sum(k["visible"] for k in kps)})
        line = to_yolo_pose(kps, bbox, rx, ry)
        if line:
            yolo_lines.append(line)

    data = {
        "image": os.path.relpath(img_path, out_root),
        "width": rx, "height": ry,
        "keypoint_order": KEYPOINT_ORDER,
        "n_objects": len(objects),
        "objects": objects,
        "camera": {"location": [round(v, 5) for v in cam.location],
                   "azimuth": args.azimuth, "elevation": args.elevation,
                   "distance": round(distance, 5), "lens_mm": cam.data.lens},
    }
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    with open(txt_path, "w") as f:
        f.write("\n".join(yolo_lines) + ("\n" if yolo_lines else ""))

    n_occ = sum(1 for o in objects for k in o["top_face_keypoints"] if k["occluded"])
    print(f"[INFO] labels(json) -> {json_path}  objects={len(objects)}")
    print(f"[INFO] labels(yolo) -> {txt_path}  lines={len(yolo_lines)}")
    print(f"[INFO] 被遮挡的关键点数 = {n_occ} (验证多目标遮挡判断)")


if __name__ == "__main__":
    main()
