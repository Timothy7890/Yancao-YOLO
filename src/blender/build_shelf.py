"""参数化生成仓储货架 (轻型冲孔立柱 + 多层隔板), 保存 .blend 并渲染预览。

对标现场照片 picture/IMG_8602.PNG: 4 根浅灰钢立柱 + N 层水平隔板。

用法:
    blender --background --python src/blender/build_shelf.py -- \
        --out data/shelf.blend --preview output/images/shelf_preview.png \
        --width 1.2 --depth 0.5 --height 2.0 --shelves 5

设计:
  - 坐标: 货架底面在 z=0, 沿 +z 向上; 宽 = X, 深 = Y。
  - 立柱: 4 角的方钢, 截面 post×post。
  - 隔板: 每层一整块板 (W×D×board_t), 高度从 base_gap 到 height 均匀分布。
  - 横梁: 每层板下方前后两根横梁, 增强"货架感"并承托隔板。
  - 隔板对象单独命名 Shelf_Board_0..N-1, 便于后续查询板面高度往上码放条烟。
"""

import argparse
import os
import sys

import bpy


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/shelf.blend", help="输出 .blend 路径")
    p.add_argument("--preview", default="output/images/shelf_preview.png",
                   help="预览渲染输出 png; 留空则不渲染")
    p.add_argument("--width", type=float, default=1.2, help="货架宽度 X (m)")
    p.add_argument("--depth", type=float, default=0.5, help="货架深度 Y (m)")
    p.add_argument("--height", type=float, default=2.0, help="货架总高 Z (m)")
    p.add_argument("--shelves", type=int, default=5, help="隔板层数")
    p.add_argument("--post", type=float, default=0.04, help="立柱方钢截面边长 (m)")
    p.add_argument("--board", type=float, default=0.025, help="隔板厚度 (m)")
    p.add_argument("--beam", type=float, default=0.03, help="横梁截面 (m)")
    p.add_argument("--base-gap", type=float, default=0.12, help="最底层板离地高度 (m)")
    p.add_argument("--skip-board-layers", type=int, nargs="*", default=[],
                   help="跳过这些层的隔板+横梁(层号从0计, 保留立柱)")
    return p.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for coll in (bpy.data.meshes, bpy.data.materials):
        for block in list(coll):
            if block.users == 0:
                coll.remove(block)


def make_box(name, size, location):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (size[0], size[1], size[2])
    bpy.ops.object.transform_apply(scale=True)
    return obj


def steel_material(name="ShelfSteel", color=(0.78, 0.79, 0.80, 1.0)):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = 0.25
        bsdf.inputs["Roughness"].default_value = 0.5
    return mat


def shelf_heights(n, base_gap, height, board_t):
    """N 层板的板面高度: 从 base_gap 到 (height - 顶部余量) 均匀分布。"""
    top = height - board_t
    if n == 1:
        return [base_gap]
    step = (top - base_gap) / (n - 1)
    return [base_gap + i * step for i in range(n)]


def build(args):
    clear_scene()
    W, D, H = args.width, args.depth, args.height
    post, board, beam = args.post, args.board, args.beam
    mat = steel_material()

    parts = []
    # 4 根立柱 (角上)
    px = W / 2 - post / 2
    py = D / 2 - post / 2
    for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (1, 1), (-1, 1)]):
        p = make_box(f"Shelf_Post_{i}", (post, post, H), (sx * px, sy * py, H / 2))
        parts.append(p)

    skip = set(args.skip_board_layers)
    boards = []
    for i, z in enumerate(shelf_heights(args.shelves, args.base_gap, H, board)):
        if i in skip:                        # 该层不生成隔板与横梁, 只留立柱
            continue
        # 前后两根横梁 (沿 X), 位于板底
        for sy in (-1, 1):
            b = make_box(f"Shelf_Beam_{i}_{'f' if sy < 0 else 'b'}",
                         (W - 2 * post, beam, beam),
                         (0.0, sy * (D / 2 - post - beam / 2), z - board / 2 - beam / 2))
            parts.append(b)
        # 隔板
        bd = make_box(f"Shelf_Board_{i}", (W - 2 * post, D, board), (0.0, 0.0, z + board / 2))
        boards.append(bd)

    # 合并框架 (立柱+横梁) 成一个对象, 隔板保持独立便于码放查询
    for o in bpy.data.objects:
        o.select_set(False)
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    frame = bpy.context.active_object
    frame.name = "Shelf_Frame"

    for o in [frame] + boards:
        o.data.materials.clear()
        o.data.materials.append(mat)

    print(f"[INFO] shelf built: {W}x{D}x{H}m, {args.shelves} boards")
    print("[INFO] board top heights (m):",
          [round(z + board, 3) for z in shelf_heights(args.shelves, args.base_gap, H, board)])
    return frame, boards


def render_preview(path, W, H):
    from mathutils import Vector

    scene = bpy.context.scene
    scene.render.resolution_x = 900
    scene.render.resolution_y = 1200
    scene.render.image_settings.file_format = "PNG"
    for ident in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = ident
            break
        except TypeError:
            continue

    world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.2, 0.21, 0.24, 1.0)
        bg.inputs["Strength"].default_value = 0.6

    ld = bpy.data.lights.new("Sun", type="SUN")
    ld.energy = 2.5
    sun = bpy.data.objects.new("Sun", ld)
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = (0.6, 0.2, 0.3)

    # 地面, 便于判断货架站位
    bpy.ops.mesh.primitive_plane_add(size=6.0, location=(0, 0, 0))
    floor = bpy.context.active_object
    fmat = bpy.data.materials.new("Floor")
    fmat.use_nodes = True
    fb = next((n for n in fmat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if fb:
        fb.inputs["Base Color"].default_value = (0.32, 0.33, 0.35, 1.0)
        fb.inputs["Roughness"].default_value = 0.8
    floor.data.materials.append(fmat)

    target = Vector((0, 0, H * 0.5))
    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = Vector((W * 1.3, -H * 1.1, H * 0.7))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam_data.lens = 35
    scene.camera = cam

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    scene.render.filepath = os.path.abspath(path)
    bpy.ops.render.render(write_still=True)
    print(f"[INFO] preview -> {path}")


def main():
    args = parse_args()
    build(args)
    if args.preview:
        render_preview(args.preview, args.width, args.height)
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"[INFO] saved -> {out}")


if __name__ == "__main__":
    main()
