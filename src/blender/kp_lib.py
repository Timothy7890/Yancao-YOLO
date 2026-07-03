"""烟盒/条烟顶面关键点的公共几何与投影逻辑 (Blender 内运行, 供各渲染脚本共用)。

约定:
  - "顶面" = 沿最长局部轴正端、法线最朝上、面积最大的多边形 (真实顶盖面, 非包围盒)。
  - 4 个角点按剩余两轴符号固定绕序 (-a,-b)(+a,-b)(+a,+b)(-a,+b), 保证关键点身份跨视角稳定。
"""

import math

import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

KEYPOINT_ORDER = ["(-a,-b)", "(+a,-b)", "(+a,+b)", "(-a,+b)"]


def _order_by_sign(verts, a, b):
    """按 (a,b) 两轴相对质心的符号固定绕序: (-a,-b)(+a,-b)(+a,+b)(-a,+b)。"""
    cen_a = sum(v[a] for v in verts) / len(verts)
    cen_b = sum(v[b] for v in verts) / len(verts)

    def order_key(v):
        sa, sb = v[a] < cen_a, v[b] < cen_b
        return {(True, True): 0, (False, True): 1, (False, False): 2, (True, False): 3}[(sa, sb)]

    return sorted(verts, key=order_key)


def _quad_from_polygon(verts, a, b):
    """退化处理: 非四边形面时, 在 (a,b) 平面沿 4 条对角方向取最远点作为 4 角。"""
    dirs = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    return [max(verts, key=lambda v: v[a] * da + v[b] * db) for da, db in dirs]


def top_face_local_corners_aabb(obj):
    """[旧版, 汇报对照用] 用轴对齐包围盒(AABB)取顶面 4 角 (会外扩/拍平)。"""
    corners = [Vector(c) for c in obj.bound_box]
    dims = obj.dimensions
    up = max(range(3), key=lambda i: dims[i])
    a, b = [i for i in range(3) if i != up]
    max_up = max(c[up] for c in corners)
    top = [c for c in corners if abs(c[up] - max_up) < 1e-6]
    return _order_by_sign(top, a, b)


def top_face_local_corners(obj):
    """返回真实顶盖多边形的 4 个角点 (局部坐标), 固定绕序。"""
    me = obj.data
    dims = obj.dimensions
    up = max(range(3), key=lambda i: dims[i])
    a, b = [i for i in range(3) if i != up]

    best, best_score = None, -1.0
    for p in me.polygons:
        d = p.normal[up]
        if d <= 0.3:
            continue
        score = p.area * d
        if score > best_score:
            best_score, best = score, p
    if best is None:
        raise SystemExit("[ERR] 找不到朝上的顶面多边形")

    verts = [me.vertices[i].co.copy() for i in best.vertices]
    if len(verts) != 4:
        verts = _quad_from_polygon(verts, a, b)
    return _order_by_sign(verts, a, b)


def top_face_world_corners(obj, method="face"):
    """顶面 4 角点的世界坐标 (已乘 matrix_world)。"""
    picker = top_face_local_corners_aabb if method == "aabb" else top_face_local_corners
    mw = obj.matrix_world
    return [mw @ c for c in picker(obj)]


def all_world_corners(obj):
    mw = obj.matrix_world
    return [mw @ Vector(c) for c in obj.bound_box]


def world_center(obj):
    return sum(all_world_corners(obj), Vector()) / 8.0


def project(scene, cam, world_pt, rx, ry):
    """世界坐标 -> 像素坐标; 返回 (px, py, depth, in_frame)。"""
    ndc = world_to_camera_view(scene, cam, world_pt)
    px = ndc.x * rx
    py = (1.0 - ndc.y) * ry
    in_frame = (0.0 <= ndc.x <= 1.0) and (0.0 <= ndc.y <= 1.0) and (ndc.z > 0.0)
    return px, py, ndc.z, in_frame


def is_occluded(depsgraph, scene, cam_loc, world_pt):
    """从相机到该点做射线检测, 若有更近的表面挡住则判为遮挡。"""
    direction = world_pt - cam_loc
    dist = direction.length
    if dist < 1e-9:
        return False
    direction = direction.normalized()
    hit, loc, _n, _idx, _obj, _m = scene.ray_cast(depsgraph, cam_loc, direction)
    if not hit:
        return False
    return (loc - cam_loc).length < dist - 5e-4


# ---------- 场景搭建工具 (相机/灯光/世界/引擎) ----------

def setup_world(bg):
    scene = bpy.context.scene
    scene.render.film_transparent = (bg == "transparent")
    world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bgnode = world.node_tree.nodes.get("Background")
    if bgnode:
        val = {"grey": (0.18, 0.18, 0.18, 1.0), "white": (0.85, 0.85, 0.85, 1.0),
               "transparent": (0.05, 0.05, 0.05, 1.0)}[bg]
        bgnode.inputs["Color"].default_value = val
        bgnode.inputs["Strength"].default_value = 1.0


def ensure_light(energy=30.0, location=(0.3, -0.3, 0.6), size=0.5):
    lights = [o for o in bpy.data.objects if o.type == "LIGHT"]
    if lights:
        return lights[0]
    ld = bpy.data.lights.new("KeyLight", type="AREA")
    ld.energy = energy
    ld.size = size
    obj = bpy.data.objects.new("KeyLight", ld)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    return obj


def place_camera(target, azimuth, elevation, distance, lens=50.0):
    cam = next((o for o in bpy.data.objects if o.type == "CAMERA"), None)
    if cam is None:
        cd = bpy.data.cameras.new("Camera")
        cam = bpy.data.objects.new("Camera", cd)
        bpy.context.collection.objects.link(cam)
    cam.data.lens = lens
    az, el = math.radians(azimuth), math.radians(elevation)
    pos = Vector((
        target.x + distance * math.cos(el) * math.cos(az),
        target.y + distance * math.cos(el) * math.sin(az),
        target.z + distance * math.sin(el),
    ))
    cam.location = pos
    cam.rotation_euler = (target - pos).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    return cam


def set_engine(scene, engine, samples=64):
    if engine == "CYCLES":
        scene.render.engine = "CYCLES"
        scene.cycles.samples = samples
    else:
        for ident in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            try:
                scene.render.engine = ident
                break
            except TypeError:
                continue
    print(f"[INFO] render engine = {scene.render.engine}")
