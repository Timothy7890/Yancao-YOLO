"""用 liqun.obj (几何+UV) + tiaoyan.png (贴图) 组装利群条烟, 渲染预览并存为 .blend。

    blender --background --python scripts/build_liqun_blend.py

产出:
    data/liqun_carton.blend         自包含(贴图已打包)的利群条烟资产
    output/debug/liqun_built.png    预览图
"""
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "blender"))
from kp_lib import (  # noqa: E402
    all_world_corners, ensure_light, place_camera, set_engine, setup_world,
)
import mathutils  # noqa: E402

OBJ = os.path.join(ROOT, "data", "liqun", "liqun.obj")
TEX = os.path.join(ROOT, "data", "textures", "tiaoyan.png")
BLEND = os.path.join(ROOT, "data", "liqun_carton.blend")
PREVIEW = os.path.join(ROOT, "output", "debug", "liqun_built.png")


def build_material():
    mat = bpy.data.materials.new("Liqun_Carton")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None) or nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    tex = nt.nodes.new("ShaderNodeTexImage")
    img = bpy.data.images.load(TEX)
    img.colorspace_settings.name = "sRGB"
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.45
    return mat


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.obj_import(filepath=OBJ)
    bpy.context.view_layer.update()

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    print(f"[BUILD] 导入网格: {[o.name for o in meshes]}")
    obj = meshes[0]
    obj.name = "liqun_carton"
    obj.data.materials.clear()
    obj.data.materials.append(build_material())

    wc = all_world_corners(obj)
    xs = [p.x for p in wc]; ys = [p.y for p in wc]; zs = [p.z for p in wc]
    dims = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    print(f"[BUILD] 尺寸(m) = {tuple(round(d,4) for d in dims)}")

    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = 1024, 1024
    scene.render.image_settings.file_format = "PNG"
    set_engine(scene, "EEVEE")
    setup_world("grey")
    ensure_light(energy=50.0, location=(0.2, -0.2, 0.5), size=0.6)

    center = mathutils.Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2))
    extent = max(dims)
    place_camera(center, 50.0, 35.0, extent * 2.0, lens=50.0)

    os.makedirs(os.path.dirname(PREVIEW), exist_ok=True)
    scene.render.filepath = PREVIEW
    bpy.ops.render.render(write_still=True)
    print(f"[BUILD] 预览 -> {PREVIEW}")

    bpy.ops.file.pack_all()  # 把贴图打包进 .blend, 自包含
    bpy.ops.wm.save_as_mainfile(filepath=BLEND)
    print(f"[BUILD] 资产 -> {BLEND}")


if __name__ == "__main__":
    main()
