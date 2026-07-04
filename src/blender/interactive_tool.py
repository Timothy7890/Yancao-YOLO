"""货架/烟盒交互调节工具 (Blender 插件, 在 EEVEE 视口里实时预览)。

用法:
  1) 用 Blender GUI 打开 data/shelf_with_carton.blend
  2) 视口右上角着色模式切到 "Rendered"(EEVEE), 即可实时看渲染效果
  3) Scripting 工作区 -> 打开本文件 -> Run Script (Alt+P)
  4) 3D 视口按 N 打开侧栏 -> "烟草" 标签

功能:
  - 相机: 6 个方向按钮; 或点 "▶ 键盘驾驶" 进入模式后用 WASD(前后左右)/QE(上下) 推相机, 鼠标照常转视角, ESC 退出
  - 烟盒: 偏航角滑块 (实时, 底面始终贴板)
  - 面板: 长(X)/宽(Y) 滑块; 第三层高度滑块 (实时)
  - "对齐相机到当前视角" / "打印相机位姿" 便于把机位喂给渲染管线
  - "显示顶面四点" 在朝上面四角放标记, 随烟盒转动实时更新

只依赖 bpy, 不引用项目其它脚本。要求场景里有 Shelf_Board_* 与 名字含 liqun/carton 的 MESH。
"""

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty
from bpy.types import Operator, Panel
from mathutils import Vector

_updating = False          # 防止 Init 写属性时触发回调递归


# ---------------- 场景查询/操作 ----------------

def get_carton():
    cs = [o for o in bpy.data.objects
          if o.type == "MESH" and ("liqun" in o.name.lower() or "carton" in o.name.lower())]
    return cs[0] if cs else None


def get_boards():
    return sorted([o for o in bpy.data.objects if o.name.startswith("Shelf_Board_")],
                  key=lambda o: o.location.z)


def board_top_center(board):
    cs = [board.matrix_world @ Vector(c) for c in board.bound_box]
    return (sum(c.x for c in cs) / 8.0, sum(c.y for c in cs) / 8.0, max(c.z for c in cs))


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
    for b in get_boards():
        d = b.dimensions
        b.dimensions = Vector((context.scene.yc_board_len, context.scene.yc_board_wid, d.z))
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


class YC_OT_init(Operator):
    bl_idname = "yc.init"
    bl_label = "从场景读取当前值"

    def execute(self, context):
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
        box.prop(s, "yc_layer")
        box.prop(s, "yc_yaw", slider=True)
        box.prop(s, "yc_markers")

        box = self.layout.box()
        box.label(text="面板", icon="MESH_PLANE")
        box.prop(s, "yc_board_len", slider=True)
        box.prop(s, "yc_board_wid", slider=True)
        box.prop(s, "yc_board3_z", slider=True)


_CLASSES = (YC_OT_move_cam, YC_OT_drive, YC_OT_align_cam, YC_OT_print_pose,
            YC_OT_init, YC_PT_panel)


def register():
    S = bpy.types.Scene
    S.yc_step = FloatProperty(name="步长(m)", default=0.05, min=0.001, max=1.0)
    S.yc_layer = IntProperty(name="所在层", default=2, min=0, max=10)
    S.yc_yaw = FloatProperty(name="偏航角(°)", default=0.0, min=-180, max=180, update=_on_yaw)
    S.yc_markers = BoolProperty(name="显示顶面四点", default=False, update=_on_markers)
    S.yc_board_len = FloatProperty(name="面板长X(m)", default=1.12, min=0.1, max=3.0,
                                   update=_on_board_size)
    S.yc_board_wid = FloatProperty(name="面板宽Y(m)", default=1.0, min=0.1, max=3.0,
                                   update=_on_board_size)
    S.yc_board3_z = FloatProperty(name="该层高度Z(m)", default=1.072, min=0.0, max=3.0,
                                  update=_on_board3_z)
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
    for p in ("yc_step", "yc_layer", "yc_yaw", "yc_markers",
              "yc_board_len", "yc_board_wid", "yc_board3_z"):
        if hasattr(bpy.types.Scene, p):
            delattr(bpy.types.Scene, p)


if __name__ == "__main__":
    try:
        unregister()
    except Exception:
        pass
    register()
    print("[YC] 交互工具已加载: 3D 视口按 N -> '烟草' 标签。先点 '从场景读取当前值'。")
