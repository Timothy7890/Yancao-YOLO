"""货架/烟盒交互调节工具 (Blender 插件, 在 EEVEE 视口里实时预览)。

用法:
  1) 用 Blender GUI 打开 data/shelf_with_carton.blend
  2) 视口右上角着色模式切到 "Rendered"(EEVEE), 即可实时看渲染效果
  3) Scripting 工作区 -> 打开本文件 -> Run Script (Alt+P)
  4) 3D 视口按 N 打开侧栏 -> "烟草" 标签

功能:
  - 相机: 应用标定相机(config); 6 个方向按钮; 或 "▶ 键盘驾驶" 用 WASD/QE 推相机
  - 烟盒: 偏航角滑块 (实时, 底面始终贴板)
  - 面板: 长(X)/宽(Y) 滑块 -> 隔板与立柱框架一起缩放; 选中层升降滑块 -> 该层横梁跟随
  - 结构: "拆分横梁并绑定隔板" 把老货架里合并的 Shelf_Frame 拆出横梁并父级绑到各层板
  - 灯光: "工厂LED布光" 一键铺顶部条形柔光 + 环境光, 少阴影, 保留膜面反光高光
  - "拾取选中隔板" 把视口里选中的 Shelf_Board_* 设为当前操作层
  - "显示顶面四点" 在朝上面四角放标记, 随烟盒转动实时更新

只依赖 bpy(+可选 camera_config)。要求场景里有 Shelf_Board_* 与 名字含 liqun/carton 的 MESH。
"""

import os
import sys

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty
from bpy.types import Operator, Panel
from mathutils import Vector

_updating = False          # 防止 Init 写属性时触发回调递归

# 定位仓库, 加载 camera_config (供"应用标定相机"用)
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = "/Users/timo/code/Python/Yancao-YOLO/src/blender"
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
_CONFIG_PATH = os.path.join(_REPO, "config", "camera.json")
sys.path.insert(0, os.path.join(_REPO, "src", "config"))
try:
    import camera_config as cc
    _HAS_CC = True
except Exception as _e:          # noqa: F841
    _HAS_CC = False


# ---------------- 场景查询/操作 ----------------

def get_carton():
    cs = [o for o in bpy.data.objects
          if o.type == "MESH" and ("liqun" in o.name.lower() or "carton" in o.name.lower())]
    return cs[0] if cs else None


def get_boards():
    return sorted([o for o in bpy.data.objects if o.name.startswith("Shelf_Board_")],
                  key=lambda o: o.location.z)


def get_frame():
    return bpy.data.objects.get("Shelf_Frame")


def get_beams():
    return [o for o in bpy.data.objects if o.name.startswith("Shelf_Beam_")]


def board_top_center(board):
    cs = [board.matrix_world @ Vector(c) for c in board.bound_box]
    return (sum(c.x for c in cs) / 8.0, sum(c.y for c in cs) / 8.0, max(c.z for c in cs))


def world_center_z(o):
    cs = [(o.matrix_world @ Vector(c)).z for c in o.bound_box]
    return sum(cs) / 8.0


def shelf_bounds():
    """货架整体世界包围盒 (立柱+隔板), 返回 (minx,miny,minz,maxx,maxy,maxz)。"""
    objs = [o for o in ([get_frame()] + get_boards()) if o]
    if not objs:
        return None
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def _center_frame_origin(context):
    """把 Shelf_Frame 的原点移到几何包围盒中心(XY居中), 之后按比例缩放才对称。只做一次。"""
    frame = get_frame()
    if not frame or frame.get("yc_centered"):
        return
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in list(context.selected_objects):
        o.select_set(False)
    frame.select_set(True)
    context.view_layer.objects.active = frame
    try:
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
        frame["yc_centered"] = 1
    except RuntimeError:
        pass


def reseat_carton():
    """把烟盒包围盒中心对准所在层板心, 底面落到板面。"""
    carton = get_carton()
    boards = get_boards()
    if not carton or not boards:
        return
    layer = min(max(bpy.context.scene.yc_layer, 0), len(boards) - 1)
    bcx, bcy, btop = board_top_center(boards[layer])
    bpy.context.view_layer.update()
    cs = [carton.matrix_world @ Vector(c) for c in carton.bound_box]
    cxw = sum(c.x for c in cs) / 8.0
    cyw = sum(c.y for c in cs) / 8.0
    zmin = min(c.z for c in cs)
    carton.location.x += bcx - cxw
    carton.location.y += bcy - cyw
    carton.location.z += btop - zmin
    bpy.context.view_layer.update()


def top_face_up_corners(obj):
    """朝上那面(法线最朝世界+Z、面积最大)的 4 个世界角点。"""
    me = obj.data
    R = obj.matrix_world.to_3x3()
    best, best_score = None, -1.0
    for p in me.polygons:
        nw = R @ p.normal
        if nw.length < 1e-9:
            continue
        up = nw.normalized().z
        if up <= 0.1:
            continue
        score = p.area * up
        if score > best_score:
            best_score, best = score, p
    if best is None:
        return []
    return [obj.matrix_world @ me.vertices[i].co for i in best.vertices][:4]


def refresh_markers():
    if not bpy.context.scene.yc_markers:
        return
    carton = get_carton()
    if not carton:
        return
    corners = top_face_up_corners(carton)
    for i, c in enumerate(corners):
        name = f"YC_KP_{i}"
        e = bpy.data.objects.get(name)
        if e is None:
            e = bpy.data.objects.new(name, None)
            e.empty_display_type = "SPHERE"
            e.empty_display_size = 0.01
            e.show_in_front = True
            bpy.context.collection.objects.link(e)
        e.location = c


def clear_markers():
    for i in range(4):
        e = bpy.data.objects.get(f"YC_KP_{i}")
        if e:
            bpy.data.objects.remove(e, do_unlink=True)


# ---------------- 属性回调 ----------------

def _on_yaw(self, context):
    if _updating:
        return
    import math
    carton = get_carton()
    if carton:
        carton.rotation_mode = "XYZ"
        carton.rotation_euler = (0.0, 0.0, math.radians(context.scene.yc_yaw))
        reseat_carton()
        refresh_markers()


def _on_board_size(self, context):
    if _updating:
        return
    boards = get_boards()
    if not boards:
        return
    old_x = boards[0].dimensions.x
    old_y = boards[0].dimensions.y
    new_x = context.scene.yc_board_len
    new_y = context.scene.yc_board_wid
    for b in boards:
        d = b.dimensions
        b.dimensions = Vector((new_x, new_y, d.z))
    # 立柱框架按同一比例缩放, 让立柱跟着隔板长宽走 (横梁若已绑到隔板会随板缩放)
    frame = get_frame()
    if frame and old_x > 1e-6 and old_y > 1e-6:
        if not frame.get("yc_centered"):
            _center_frame_origin(context)
        frame.scale.x *= new_x / old_x
        frame.scale.y *= new_y / old_y
    bpy.context.view_layer.update()
    reseat_carton()
    refresh_markers()


def _on_board3_z(self, context):
    if _updating:
        return
    boards = get_boards()
    layer = min(max(context.scene.yc_layer, 0), len(boards) - 1)
    b = boards[layer]
    b.location.z = context.scene.yc_board3_z - b.dimensions.z / 2.0
    bpy.context.view_layer.update()
    reseat_carton()
    refresh_markers()


def _on_markers(self, context):
    if self.yc_markers:
        refresh_markers()
    else:
        clear_markers()


# ---------------- 操作符 ----------------

class YC_OT_move_cam(Operator):
    bl_idname = "yc.move_cam"
    bl_label = "移动相机"
    bl_options = {"REGISTER", "UNDO"}
    dx: FloatProperty(default=0.0)
    dy: FloatProperty(default=0.0)
    dz: FloatProperty(default=0.0)

    def execute(self, context):
        cam = context.scene.camera
        if cam is None:
            self.report({"ERROR"}, "场景没有相机")
            return {"CANCELLED"}
        s = context.scene.yc_step
        cam.location += Vector((self.dx, self.dy, self.dz)) * s
        return {"FINISHED"}


class YC_OT_drive(Operator):
    bl_idname = "yc.drive"
    bl_label = "键盘驾驶相机"
    _keys = {"W": (0, 1, 0), "S": (0, -1, 0), "A": (-1, 0, 0),
             "D": (1, 0, 0), "Q": (0, 0, 1), "E": (0, 0, -1)}

    def modal(self, context, event):
        if event.type in {"ESC", "RET", "SPACE"} and event.value == "PRESS":
            context.area.header_text_set(None)
            return {"FINISHED"}
        if event.type in self._keys and event.value == "PRESS":
            cam = context.scene.camera
            if cam:
                d = Vector(self._keys[event.type]) * context.scene.yc_step
                cam.location += d
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}          # 鼠标转视角等照常

    def invoke(self, context, event):
        if context.scene.camera is None:
            self.report({"ERROR"}, "场景没有相机")
            return {"CANCELLED"}
        context.area.header_text_set("键盘驾驶: WASD 前后左右 / QE 上下 / 鼠标转视角 / ESC 退出")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}


class YC_OT_apply_config_cam(Operator):
    bl_idname = "yc.apply_config_cam"
    bl_label = "应用标定相机(config)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not _HAS_CC:
            self.report({"ERROR"}, "找不到 camera_config, 无法读取配置")
            return {"CANCELLED"}
        if not os.path.exists(_CONFIG_PATH):
            self.report({"ERROR"}, f"配置不存在: {_CONFIG_PATH}")
            return {"CANCELLED"}
        cfg = cc.load(_CONFIG_PATH)
        boards = get_boards()
        if not boards:
            self.report({"ERROR"}, "场景没有 Shelf_Board_*")
            return {"CANCELLED"}
        layer = min(max(context.scene.yc_layer, 0), len(boards) - 1)
        bcx, bcy, btop = board_top_center(boards[layer])
        cam = context.scene.camera
        if cam is None:
            cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
            context.collection.objects.link(cam)
        cc.place_camera_from_config(cam, cfg, (bcx, bcy, btop + 0.03), context.scene.yc_cam_dist)
        refresh_markers()
        self.report({"INFO"}, "已应用标定相机, 记得 Cmd+S 保存为默认")
        return {"FINISHED"}


class YC_OT_align_cam(Operator):
    bl_idname = "yc.align_cam"
    bl_label = "对齐相机到当前视角"

    def execute(self, context):
        try:
            bpy.ops.view3d.camera_to_view()
        except RuntimeError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class YC_OT_print_pose(Operator):
    bl_idname = "yc.print_pose"
    bl_label = "打印相机位姿"

    def execute(self, context):
        cam = context.scene.camera
        if cam is None:
            self.report({"ERROR"}, "场景没有相机")
            return {"CANCELLED"}
        loc = tuple(round(v, 4) for v in cam.location)
        rot = tuple(round(v, 4) for v in cam.rotation_euler)
        print(f"[YC] camera location={loc} rotation_euler={rot} lens={cam.data.lens:.2f}mm")
        self.report({"INFO"}, f"loc={loc} (详见控制台)")
        return {"FINISHED"}


def sync_from_scene(context):
    """把滑块值刷新为场景当前状态(按当前 yc_layer)。"""
    global _updating
    _updating = True
    boards = get_boards()
    carton = get_carton()
    if boards:
        layer = min(max(context.scene.yc_layer, 0), len(boards) - 1)
        b = boards[layer]
        context.scene.yc_board_len = boards[0].dimensions.x
        context.scene.yc_board_wid = boards[0].dimensions.y
        context.scene.yc_board3_z = b.location.z + b.dimensions.z / 2.0
    if carton:
        context.scene.yc_yaw = round(carton.rotation_euler.z * 57.2958, 1)
    _updating = False
    refresh_markers()


class YC_OT_init(Operator):
    bl_idname = "yc.init"
    bl_label = "从场景读取当前值"

    def execute(self, context):
        _center_frame_origin(context)
        sync_from_scene(context)
        return {"FINISHED"}


class YC_OT_pick_layer(Operator):
    bl_idname = "yc.pick_layer"
    bl_label = "拾取选中隔板"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        if obj is None or not obj.name.startswith("Shelf_Board_"):
            self.report({"ERROR"}, "请先在视口里点选一块 Shelf_Board_*")
            return {"CANCELLED"}
        boards = get_boards()
        if obj not in boards:
            self.report({"ERROR"}, "选中对象不是隔板")
            return {"CANCELLED"}
        context.scene.yc_layer = boards.index(obj)
        sync_from_scene(context)
        self.report({"INFO"}, f"当前操作层 = {context.scene.yc_layer}")
        return {"FINISHED"}


class YC_OT_split_frame(Operator):
    bl_idname = "yc.split_frame"
    bl_label = "拆分横梁并绑定隔板"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        frame = get_frame()
        if frame is None:
            self.report({"ERROR"}, "场景没有 Shelf_Frame")
            return {"CANCELLED"}
        if get_beams():
            _center_frame_origin(context)
            self.report({"INFO"}, "已是拆分结构, 无需再拆")
            return {"FINISHED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for o in list(context.selected_objects):
            o.select_set(False)
        frame.select_set(True)
        context.view_layer.objects.active = frame
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.separate(type="LOOSE")
        bpy.ops.object.mode_set(mode="OBJECT")
        parts = list(context.selected_objects)
        # 按竖直跨度分立柱(高)与横梁(矮)
        posts = [o for o in parts if o.dimensions.z >= 0.3]
        beams = [o for o in parts if o.dimensions.z < 0.3]
        if not posts:
            self.report({"ERROR"}, "没识别出立柱, 已取消")
            return {"CANCELLED"}
        for k, o in enumerate(parts):
            o.name = f"_yc_part_{k}"
        for o in list(context.selected_objects):
            o.select_set(False)
        for p in posts:
            p.select_set(True)
        context.view_layer.objects.active = posts[0]
        bpy.ops.object.join()
        newframe = context.view_layer.objects.active
        newframe.name = "Shelf_Frame"
        boards = get_boards()
        for k, bm in enumerate(beams):
            bm.name = f"Shelf_Beam_{k}"
            bz = world_center_z(bm)
            nearest = min(boards, key=lambda b: abs(world_center_z(b) - bz))
            bm.parent = nearest
            bm.matrix_parent_inverse = nearest.matrix_world.inverted()
        _center_frame_origin(context)
        self.report({"INFO"}, f"拆出 {len(posts)} 立柱 + {len(beams)} 横梁, 横梁已绑到隔板")
        return {"FINISHED"}


class YC_OT_factory_lights(Operator):
    bl_idname = "yc.factory_lights"
    bl_label = "工厂LED布光"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        for ident in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            try:
                scene.render.engine = ident
                break
            except TypeError:
                continue
        b = shelf_bounds()
        if b is None:
            self.report({"ERROR"}, "场景没有货架, 无法定位灯")
            return {"CANCELLED"}
        minx, miny, minz, maxx, maxy, maxz = b
        cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
        width, depth = maxx - minx, maxy - miny
        power = scene.yc_light_power

        for o in list(bpy.data.objects):
            if o.name.startswith("YC_Light"):
                bpy.data.objects.remove(o, do_unlink=True)

        ceil = maxz + 1.0
        n = 3
        for j in range(n):
            t = (j + 0.5) / n
            y = miny + t * depth
            ld = bpy.data.lights.new(f"YC_Light_top_{j}", "AREA")
            ld.shape = "RECTANGLE"
            ld.size = max(width * 1.2, 0.3)
            ld.size_y = 0.12                      # 细长 -> 模拟条形 LED, 高光呈长条
            ld.energy = power
            ld.color = (1.0, 0.98, 0.95)
            obj = bpy.data.objects.new(ld.name, ld)
            context.collection.objects.link(obj)
            obj.location = (cx, y, ceil)          # 朝下(默认 -Z)

        # 正前方一盏大柔光补光, 抬升朝相机面亮度, 减少正面死黑
        lf = bpy.data.lights.new("YC_Light_front", "AREA")
        lf.shape = "RECTANGLE"
        lf.size = max(width * 1.3, 0.3)
        lf.size_y = max((maxz - minz) * 0.8, 0.3)
        lf.energy = power * 0.5
        lf.color = (1.0, 0.98, 0.95)
        of = bpy.data.objects.new(lf.name, lf)
        context.collection.objects.link(of)
        of.location = (cx, miny - max(depth, 0.6), (minz + maxz) / 2.0)
        d = Vector((cx, cy, (minz + maxz) / 2.0)) - of.location
        of.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

        world = scene.world or bpy.data.worlds.new("World")
        scene.world = world
        world.use_nodes = True
        bg = world.node_tree.nodes.get("Background")
        if bg:
            bg.inputs["Color"].default_value = (0.9, 0.9, 0.92, 1.0)
            bg.inputs["Strength"].default_value = scene.yc_ambient
        self.report({"INFO"}, f"已布 {n} 条顶灯 + 1 补光 + 环境光, 功率 {power:.0f}W")
        return {"FINISHED"}


# ---------------- 面板 ----------------

class YC_PT_panel(Panel):
    bl_label = "烟草调节工具"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "烟草"

    def draw(self, context):
        s = context.scene
        col = self.layout.column(align=True)
        col.operator("yc.init", icon="FILE_REFRESH")

        box = self.layout.box()
        box.label(text="相机", icon="CAMERA_DATA")
        row = box.row(align=True)
        row.operator("yc.apply_config_cam", icon="OUTLINER_OB_CAMERA")
        row.prop(s, "yc_cam_dist", text="距")
        box.prop(s, "yc_step")
        box.operator("yc.drive", icon="PLAY")
        row = box.row(align=True)
        row.operator("yc.move_cam", text="左").dx = -1
        row.operator("yc.move_cam", text="右").dx = 1
        row = box.row(align=True)
        row.operator("yc.move_cam", text="前").dy = 1
        row.operator("yc.move_cam", text="后").dy = -1
        row = box.row(align=True)
        row.operator("yc.move_cam", text="上").dz = 1
        row.operator("yc.move_cam", text="下").dz = -1
        box.operator("yc.align_cam", icon="VIEW_CAMERA")
        box.operator("yc.print_pose", icon="INFO")

        box = self.layout.box()
        box.label(text="烟盒", icon="MESH_CUBE")
        row = box.row(align=True)
        row.prop(s, "yc_layer")
        row.operator("yc.pick_layer", text="", icon="EYEDROPPER")
        box.prop(s, "yc_yaw", slider=True)
        box.prop(s, "yc_markers")

        box = self.layout.box()
        box.label(text="面板", icon="MESH_PLANE")
        box.prop(s, "yc_board_len", slider=True)
        box.prop(s, "yc_board_wid", slider=True)
        box.prop(s, "yc_board3_z", slider=True, text="选中层高度Z(m)")

        box = self.layout.box()
        box.label(text="结构", icon="MOD_BUILD")
        box.operator("yc.split_frame", icon="UNLINKED")

        box = self.layout.box()
        box.label(text="灯光(工厂LED)", icon="LIGHT_AREA")
        box.prop(s, "yc_light_power", slider=True)
        box.prop(s, "yc_ambient", slider=True)
        box.operator("yc.factory_lights", icon="OUTLINER_OB_LIGHT")


_CLASSES = (YC_OT_move_cam, YC_OT_drive, YC_OT_apply_config_cam, YC_OT_align_cam,
            YC_OT_print_pose, YC_OT_init, YC_OT_pick_layer, YC_OT_split_frame,
            YC_OT_factory_lights, YC_PT_panel)


def register():
    S = bpy.types.Scene
    S.yc_step = FloatProperty(name="步长(m)", default=0.05, min=0.001, max=1.0)
    S.yc_cam_dist = FloatProperty(name="相机距离(m)", default=0.9, min=0.05, max=5.0)
    S.yc_layer = IntProperty(name="所在层", default=2, min=0, max=10)
    S.yc_yaw = FloatProperty(name="偏航角(°)", default=0.0, min=-180, max=180, update=_on_yaw)
    S.yc_markers = BoolProperty(name="显示顶面四点", default=False, update=_on_markers)
    S.yc_board_len = FloatProperty(name="面板长X(m)", default=1.12, min=0.1, max=3.0,
                                   update=_on_board_size)
    S.yc_board_wid = FloatProperty(name="面板宽Y(m)", default=1.0, min=0.1, max=3.0,
                                   update=_on_board_size)
    S.yc_board3_z = FloatProperty(name="该层高度Z(m)", default=1.072, min=0.0, max=3.0,
                                  update=_on_board3_z)
    S.yc_light_power = FloatProperty(name="顶灯功率(W)", default=200.0, min=0.0, max=2000.0)
    S.yc_ambient = FloatProperty(name="环境光强度", default=0.4, min=0.0, max=3.0)
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
    for p in ("yc_step", "yc_cam_dist", "yc_layer", "yc_yaw", "yc_markers",
              "yc_board_len", "yc_board_wid", "yc_board3_z",
              "yc_light_power", "yc_ambient"):
        if hasattr(bpy.types.Scene, p):
            delattr(bpy.types.Scene, p)


if __name__ == "__main__":
    try:
        unregister()
    except Exception:
        pass
    register()
    print("[YC] 交互工具已加载: 3D 视口按 N -> '烟草' 标签。先点 '从场景读取当前值'。")
