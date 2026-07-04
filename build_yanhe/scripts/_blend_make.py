"""在 Blender 内运行 (bpy): 按 box_model.json 建带贴图的长方体并保存 .blend。

由 blender_build.py 通过
    blender --background --python _blend_make.py -- --model ... --textures ... --out ...
调用。--textures 目录里是已"烘焙好朝向"(翻转+顺时针旋转)的每面纹理 <face>.png。

坐标: JSON 的盒内坐标单位为 mm, 这里按 ×0.001 缩放到米。
UV: 贴图左上(0,0)映射到该面 TL, 因此 Blender UV 用 TL=(0,1) (V 轴向上, 顶部=1)。
"""

import json
import os
import sys

import bpy
from mathutils import Vector

FACE_ORDER = ["front", "back", "left", "right", "top", "bottom"]
SCALE = 0.001  # mm -> m


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--textures", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="黄金叶")
    return ap.parse_args(argv)


def make_material(name, tex_path):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    # 按类型找 Principled BSDF (节点名可能被本地化/改名, 不能靠 name)
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
        if out:
            nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.6
    if tex_path and os.path.exists(tex_path):
        tex = nt.nodes.new("ShaderNodeTexImage")
        img = bpy.data.images.load(tex_path)
        img.name = os.path.basename(tex_path)
        tex.image = img
        tex.location = (-400, 200)
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    elif bsdf:
        bsdf.inputs["Base Color"].default_value = (0.75, 0.75, 0.78, 1.0)
    return mat


def main():
    args = parse_args()
    with open(args.model, "r", encoding="utf-8") as f:
        model = json.load(f)
    faces = model["faces"]

    bpy.ops.wm.read_factory_settings(use_empty=True)

    # 归一化到"原点=底面中心": 把所有坐标平移使最低点 z=0 (XY 已居中)。
    # 对新版 (已底面中心) JSON 为无操作; 对旧版 (几何中心) JSON 会整体上移。
    all_z = [v[2] * SCALE for face in FACE_ORDER if face in faces
             for v in faces[face]["corners_box_coords"].values()]
    z_off = -min(all_z) if all_z else 0.0

    verts, polys, uvs, face_keys = [], [], [], []
    for face in FACE_ORDER:
        if face not in faces:
            continue
        fd = faces[face]
        cm = fd["corners_box_coords"]
        corners = [(cm[k][0] * SCALE, cm[k][1] * SCALE, cm[k][2] * SCALE + z_off)
                   for k in ("TL", "TR", "BR", "BL")]
        uv_base = [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]  # TL,TR,BR,BL
        idx = [0, 1, 2, 3]
        # 让面法线朝外 (与 JSON normal 同向), 否则反转顶点绕序 (UV 随之反转, 保证每个顶点 UV 不变)
        v0, v1, v2 = (Vector(corners[i]) for i in (0, 1, 2))
        nrm = (v1 - v0).cross(v2 - v0)
        if nrm.dot(Vector(fd["normal"])) < 0:
            idx = idx[::-1]
            uv_base = uv_base[::-1]
        base = len(verts)
        for i in idx:
            verts.append(corners[i])
        polys.append(tuple(range(base, base + 4)))
        uvs.extend(uv_base)
        face_keys.append(face)

    mesh = bpy.data.meshes.new(args.name)
    mesh.from_pydata(verts, [], polys)
    mesh.update()

    uvl = mesh.uv_layers.new(name="UVMap")
    for li in range(len(mesh.loops)):
        uvl.data[li].uv = uvs[li]

    obj = bpy.data.objects.new(args.name, mesh)
    bpy.context.scene.collection.objects.link(obj)

    for pi, face in enumerate(face_keys):
        tex_path = os.path.join(args.textures, f"{face}.png")
        mat = make_material(f"{args.name}_{face}", tex_path)
        mesh.materials.append(mat)
        mesh.polygons[pi].material_index = pi
    mesh.update()

    # 计量单位设为毫米, 方便查看真实尺寸
    us = bpy.context.scene.unit_settings
    us.system = "METRIC"
    us.length_unit = "MILLIMETERS"

    # 把纹理打包进 .blend, 使文件自包含
    try:
        bpy.ops.file.pack_all()
    except Exception as e:  # noqa: BLE001
        print("[warn] pack_all failed:", e)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=args.out)
    print(f"[ok] saved {args.out}  ({len(face_keys)} faces)")


if __name__ == "__main__":
    main()
