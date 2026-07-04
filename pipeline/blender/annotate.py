"""几何标注(bpy): 顶面四角、投影到(外扩)像素、遮挡射线检测、检测框。

输出以"外扩(overscan)像素坐标"记录, 世界角点也一并存; 后处理再裁理想图/加畸变。
关键点标识在"物体自身坐标系"下固定(TL/TR/BR/BL), 与偏航无关, 保证 pose 关键点语义稳定。
"""

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


def top_face_corners_local(obj):
    """朝上面(局部法线 +Z 最大)的 4 个局部角点, 按物体系 [TL,TR,BR,BL] 稳定排序。"""
    me = obj.data
    best, best_up = None, -2.0
    for poly in me.polygons:
        if poly.normal.z > best_up:
            best_up, best = poly.normal.z, poly
    verts = [me.vertices[i].co.copy() for i in best.vertices]
    cxl = sum(v.x for v in verts) / len(verts)
    cyl = sum(v.y for v in verts) / len(verts)
    left = [v for v in verts if v.x < cxl]
    right = [v for v in verts if v.x >= cxl]
    tl = max(left, key=lambda v: v.y)
    bl = min(left, key=lambda v: v.y)
    tr = max(right, key=lambda v: v.y)
    br = min(right, key=lambda v: v.y)
    return [tl, tr, br, bl]


def _project(scene, cam, world_pt, rw, rh):
    """世界点 -> (px, py, depth)。px,py 为渲染(外扩)像素坐标, 原点左上。"""
    co = world_to_camera_view(scene, cam, Vector(world_pt))
    return (co.x * rw, (1.0 - co.y) * rh, co.z)


def _visible(scene, depsgraph, cam, world_pt, owner, eps=1e-3):
    """从相机到该点做射线, 命中的第一个物体是自身则可见(2), 否则被遮挡(1)。"""
    origin = cam.matrix_world.translation
    target = Vector(world_pt)
    direction = (target - origin)
    dist = direction.length
    if dist < 1e-6:
        return 2
    direction = direction / dist
    hit, loc, _n, _idx, obj, _m = scene.ray_cast(depsgraph, origin, direction, distance=dist * 1.5)
    if not hit:
        return 2
    if (loc - target).length <= eps or obj is owner:
        return 2
    if (loc - origin).length < dist - eps:
        return 1
    return 2


def annotate_frame(cfg, placed, cam, render_wh):
    """对已摆放的每个烟盒算标注, 返回 objects 列表(外扩像素坐标)。"""
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    rw, rh = render_wh
    out = []
    for obj, p in placed:
        mw = obj.matrix_world
        top_world = [mw @ v for v in top_face_corners_local(obj)]
        kpts = []
        for wp in top_world:
            px, py, depth = _project(scene, cam, wp, rw, rh)
            if depth <= 0.0:
                v = 0
            elif not (0.0 <= px <= rw and 0.0 <= py <= rh):
                v = 0
            else:
                v = _visible(scene, depsgraph, cam, wp, obj)
            kpts.append([px, py, v])
        # 检测框: 8 个包围盒角投影
        bb = [_project(scene, cam, mw @ Vector(c), rw, rh)[:2] for c in obj.bound_box]
        xs = [b[0] for b in bb]
        ys = [b[1] for b in bb]
        out.append({
            "sku": p.sku,
            "yaw_deg": p.yaw_deg,
            "top_world": [[c.x, c.y, c.z] for c in top_world],
            "keypoints_overscan": kpts,
            "bbox_overscan": [min(xs), min(ys), max(xs), max(ys)],
        })
    return out
