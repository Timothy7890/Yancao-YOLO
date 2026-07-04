"""场景搭建(bpy): 固定板长宽 + 立柱框架适配、板面查询、默认相机、工厂LED布光、渲染引擎。"""

import bpy
from mathutils import Vector

from pipeline.core import camera as cammod


def apply_render_settings(render_cfg):
    """引擎/采样/抗锯齿滤波/色彩变换。清晰度关键: filter_size 小=更锐, view_transform=Standard 更接近真实相机。"""
    scene = bpy.context.scene
    for ident in (render_cfg.get("engine", "BLENDER_EEVEE_NEXT"),
                  "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = ident
            break
        except TypeError:
            continue
    ee = getattr(scene, "eevee", None)
    if ee is not None and hasattr(ee, "taa_render_samples"):
        ee.taa_render_samples = int(render_cfg.get("samples", 64))
    scene.render.filter_size = float(render_cfg.get("filter_size", 1.5))
    vt = render_cfg.get("view_transform")
    if vt:
        try:
            scene.view_settings.view_transform = vt
        except TypeError:
            pass


def set_render_engine(engine, samples):
    apply_render_settings({"engine": engine, "samples": samples})


def get_frame():
    return bpy.data.objects.get("Shelf_Frame")


def _recenter_frame_origin_xy(frame):
    """把(未旋转的)立柱框架原点在 XY 移到几何中心(=世界0), 之后按比例缩放才对称。只做一次。"""
    if frame.get("yc_centered"):
        return
    loc = frame.matrix_world.translation
    dx, dy = loc.x, loc.y
    for v in frame.data.vertices:
        v.co.x += dx
        v.co.y += dy
    frame.data.update()
    frame.location.x -= dx
    frame.location.y -= dy
    frame["yc_centered"] = 1


def set_board_size(length_x, width_y, prefix="Shelf_Board_"):
    """把所有隔板设为给定长宽, 立柱框架按同比例缩放(横梁若父级绑板会随板走)。"""
    boards = sorted([o for o in bpy.data.objects if o.name.startswith(prefix)],
                    key=lambda o: o.location.z)
    if not boards:
        return
    old_x = boards[0].dimensions.x
    old_y = boards[0].dimensions.y
    for b in boards:
        d = b.dimensions
        b.dimensions = Vector((length_x, width_y, d.z))
    frame = get_frame()
    if frame and old_x > 1e-6 and old_y > 1e-6:
        _recenter_frame_origin_xy(frame)
        frame.scale.x *= length_x / old_x
        frame.scale.y *= width_y / old_y
    bpy.context.view_layer.update()


def orient_shelf(angle_deg, prefix="Shelf_Board_"):
    """把货架(立柱框架+隔板, 横梁作为子物体跟随)整体绕 Z 旋转 angle_deg。

    绕货架 XY 中心旋转; 幂等(打标记, 重复调用/已烘焙进 base_scene 不会二次旋转)。
    恰好 90° 时板仍轴对齐, 因此后续世界坐标下的摆放/建格无需改动。
    """
    import math

    from mathutils import Matrix

    if abs(angle_deg) < 1e-9:
        return
    frame = get_frame()
    boards = [o for o in bpy.data.objects if o.name.startswith(prefix)]
    tops = [o for o in ([frame] + boards) if o and o.parent is None]
    if not tops or any(o.get("yc_scene_rotated") for o in tops):
        return
    pts = [o.matrix_world @ Vector(c) for o in tops for c in o.bound_box]
    px = sum(p.x for p in pts) / len(pts)
    py = sum(p.y for p in pts) / len(pts)
    pivot = Vector((px, py, 0.0))
    R = (Matrix.Translation(pivot)
         @ Matrix.Rotation(math.radians(angle_deg), 4, "Z")
         @ Matrix.Translation(-pivot))
    for o in tops:
        o.matrix_world = R @ o.matrix_world
        o["yc_scene_rotated"] = 1
    bpy.context.view_layer.update()


def board_rect(layer, prefix="Shelf_Board_"):
    """返回某层隔板板面信息: {cx, cy, top_z, length_x, width_y}。"""
    boards = sorted([o for o in bpy.data.objects if o.name.startswith(prefix)],
                    key=lambda o: o.location.z)
    layer = max(0, min(layer, len(boards) - 1))
    b = boards[layer]
    cs = [b.matrix_world @ Vector(c) for c in b.bound_box]
    xs = [c.x for c in cs]
    ys = [c.y for c in cs]
    return {"cx": sum(xs) / 8.0, "cy": sum(ys) / 8.0, "top_z": max(c.z for c in cs),
            "length_x": max(xs) - min(xs), "width_y": max(ys) - min(ys), "obj": b}


def setup_camera(camera_config_path, layer, distance, target_z_offset,
                 yaw_off_deg=0.0, pitch_off_deg=0.0, pos_off=(0, 0, 0),
                 prefix="Shelf_Board_", overscan=0, global_yaw_deg=0.0):
    """按标定相机(可叠加抖动)对准某层板心上方。返回 (cam_obj, base_wh, render_wh)。

    global_yaw_deg: 整场景绕 Z 旋转带来的相机方位角偏移(与 orient_shelf 同角度), 使相机随货架一起转。
    """
    cfg = cammod.load(camera_config_path)
    base_w, base_h = cammod.resolution(cfg)
    # 叠加抖动+全局场景旋转到安装角
    if yaw_off_deg or pitch_off_deg or global_yaw_deg:
        cfg = cammod.cc.json.loads(cammod.cc.json.dumps(cfg))
        m = cfg.setdefault("mount", {})
        m["yaw_deg"] = m.get("yaw_deg", 0.0) + yaw_off_deg + global_yaw_deg
        m["pitch_deg"] = m.get("pitch_deg", 0.0) + pitch_off_deg
    render_cfg = cammod.overscanned(cfg, overscan) if overscan > 0 else cfg
    rect = board_rect(layer, prefix)
    target = (rect["cx"] + pos_off[0], rect["cy"] + pos_off[1],
              rect["top_z"] + target_z_offset + pos_off[2])
    cam = bpy.context.scene.camera
    if cam is None:
        cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
        bpy.context.scene.collection.objects.link(cam)
    cammod.place_camera_from_config(cam, render_cfg, target, distance)
    rx, ry = cammod.resolution(render_cfg)
    return cam, (base_w, base_h), (rx, ry)


def _shelf_bounds(prefix="Shelf_Board_"):
    objs = [get_frame()] + [o for o in bpy.data.objects if o.name.startswith(prefix)]
    objs = [o for o in objs if o]
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def build_base(cfg, paths):
    """从零搭建基础场景: 货架(存在则加载, 否则生成) + 固定板长宽 + 默认相机 + 标称布光。

    返回 dict{shelf_mode, generated}; 生成的货架由调用方决定是否存盘。
    """
    from pipeline.blender import assets

    bpy.ops.wm.read_factory_settings(use_empty=True)
    gen = cfg["shelf"]["generate"] if cfg["shelf"].get("auto_generate_if_missing") else None
    mode = assets.load_shelf(paths["shelf_blend"], gen)

    apply_render_settings(cfg["render"])
    shelf = cfg["shelf"]
    set_board_size(shelf["board_length_x"], shelf["board_width_y"], shelf["board_name_prefix"])
    scene_yaw = cfg.get("scene_z_rotation_deg", 0.0)
    orient_shelf(scene_yaw, shelf["board_name_prefix"])

    lg = cfg["lights"]
    apply_factory_lights(sum(lg["top_power"]) / 2.0, sum(lg["ambient"]) / 2.0,
                         prefix=shelf["board_name_prefix"])

    cam = cfg["camera"]
    setup_camera(paths["camera_config"], cam["work_layer"], cam["distance"],
                 cam["target_z_offset"], prefix=shelf["board_name_prefix"], overscan=0,
                 global_yaw_deg=scene_yaw)
    return {"shelf_mode": mode, "generated": mode == "generated"}


def apply_factory_lights(top_power, ambient, n_strips=3, prefix="Shelf_Board_"):
    """工厂 LED: 顶部若干条形柔光 + 前方补光 + 环境光, 少阴影, 保留膜面长条高光。"""
    for o in list(bpy.data.objects):
        if o.name.startswith("YC_Light"):
            bpy.data.objects.remove(o, do_unlink=True)
    minx, miny, minz, maxx, maxy, maxz = _shelf_bounds(prefix)
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    width, depth = maxx - minx, maxy - miny
    ceil = maxz + 1.0
    for j in range(n_strips):
        t = (j + 0.5) / n_strips
        ld = bpy.data.lights.new(f"YC_Light_top_{j}", "AREA")
        ld.shape = "RECTANGLE"
        ld.size = max(width * 1.2, 0.3)
        ld.size_y = 0.12
        ld.energy = top_power
        ld.color = (1.0, 0.98, 0.95)
        obj = bpy.data.objects.new(ld.name, ld)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = (cx, miny + t * depth, ceil)
    lf = bpy.data.lights.new("YC_Light_front", "AREA")
    lf.shape = "RECTANGLE"
    lf.size = max(width * 1.3, 0.3)
    lf.size_y = max((maxz - minz) * 0.8, 0.3)
    lf.energy = top_power * 0.5
    lf.color = (1.0, 0.98, 0.95)
    of = bpy.data.objects.new(lf.name, lf)
    bpy.context.scene.collection.objects.link(of)
    of.location = (cx, miny - max(depth, 0.6), (minz + maxz) / 2.0)
    d = Vector((cx, cy, (minz + maxz) / 2.0)) - of.location
    of.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.9, 0.9, 0.92, 1.0)
        bg.inputs["Strength"].default_value = ambient
