"""资产装载(bpy): SKU 烟盒登记表 + 货架加载/生成。

约定:
  - 每个 SKU 是 data/yanhe/<名>.blend, 内含一个网格对象(名字可含中文)。
  - SKU 模板 append 进隐藏集合, 命名 SKU__<名>; 每次摆放由模板复制实例。
  - 货架: 若 shelf_blend 存在则 append 其全部对象; 否则(允许时)用 build_shelf 参数化生成。
"""

import glob
import os

import bpy

_TEMPLATE_PREFIX = "SKU__"
_HIDDEN_COLL = "SKU_Templates"


def _hidden_collection():
    coll = bpy.data.collections.get(_HIDDEN_COLL)
    if coll is None:
        coll = bpy.data.collections.new(_HIDDEN_COLL)
        bpy.context.scene.collection.children.link(coll)
    return coll


def scan_skus(sku_dir):
    """返回 {sku_name: blend_path}, sku_name = 文件名(去扩展名)。"""
    out = {}
    for path in sorted(glob.glob(os.path.join(sku_dir, "*.blend"))):
        name = os.path.splitext(os.path.basename(path))[0]
        out[name] = path
    return out


def _append_largest_mesh(path):
    before = set(bpy.data.objects)
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = list(src.objects)
    linked = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in linked if o.type == "MESH"]
    if not meshes:
        # 清理误入对象
        for o in linked:
            bpy.data.objects.remove(o, do_unlink=True)
        raise RuntimeError(f"{path} 内无 MESH 对象")
    template = max(meshes, key=lambda o: o.dimensions.x * o.dimensions.y * o.dimensions.z)
    for o in linked:
        if o is not template:
            bpy.data.objects.remove(o, do_unlink=True)
    return template


def build_registry(sku_dir):
    """append 每个 SKU 模板并读取底面尺寸, 返回登记表。"""
    coll = _hidden_collection()
    registry = {}
    for name, path in scan_skus(sku_dir).items():
        tmpl = _append_largest_mesh(path)
        tmpl.name = _TEMPLATE_PREFIX + name
        for c in list(tmpl.users_collection):
            c.objects.unlink(tmpl)
        coll.objects.link(tmpl)
        tmpl.hide_render = True
        tmpl.hide_set(True)
        d = tmpl.dimensions
        registry[name] = {"path": path, "object": tmpl.name,
                          "length_x": d.x, "width_y": d.y, "height_z": d.z}
    return registry


def instance_sku(registry, name):
    """由模板复制一个可摆放实例(共享网格数据), 链接到主集合并可见。"""
    tmpl = bpy.data.objects.get(registry[name]["object"])
    if tmpl is None:
        raise RuntimeError(f"SKU 模板缺失: {name}")
    obj = tmpl.copy()                       # 复制对象(共享 mesh data, 省内存)
    obj.name = f"pack_{name}"
    bpy.context.scene.collection.objects.link(obj)
    obj.hide_render = False
    obj.hide_set(False)
    return obj


def clear_instances():
    for o in list(bpy.data.objects):
        if o.name.startswith("pack_"):
            bpy.data.objects.remove(o, do_unlink=True)


def load_shelf(shelf_path, generate_cfg=None):
    """加载货架: 存在则 append; 否则用 build_shelf 生成(需 generate_cfg)。"""
    if shelf_path and os.path.exists(shelf_path):
        before = set(bpy.data.objects)
        with bpy.data.libraries.load(shelf_path, link=False) as (src, dst):
            dst.objects = list(src.objects)
        linked = [o for o in bpy.data.objects if o not in before]
        for o in linked:
            if not o.users_collection:
                bpy.context.scene.collection.objects.link(o)
        return "appended"
    if generate_cfg is None:
        raise RuntimeError(f"货架不存在且未提供生成参数: {shelf_path}")
    import argparse
    import build_shelf                       # src/blender/build_shelf.py (env 已加路径)
    args = argparse.Namespace(
        out="", preview="",
        width=generate_cfg["width"], depth=generate_cfg["depth"],
        height=generate_cfg["height"], shelves=generate_cfg["shelves"],
        post=0.04, board=0.025, beam=0.03, base_gap=0.12,
        skip_board_layers=generate_cfg.get("skip_board_layers", []),
    )
    build_shelf.build(args)
    return "generated"


def get_boards(prefix="Shelf_Board_"):
    return sorted([o for o in bpy.data.objects if o.name.startswith(prefix)],
                  key=lambda o: o.location.z)
