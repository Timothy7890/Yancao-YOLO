"""相机配置(内参+畸变+安装角)读取与应用。

同一个模块在两处运行:
  - Blender(bpy) 内: place_camera_from_config() 按配置设分辨率/FOV/朝向。
  - 系统 Python(numpy) 内: distort_points()/distort_image() 给理想针孔图和关键点加畸变。

坐标约定:
  - 世界 +Z 朝上; yaw=0 时相机朝 -Y(货架正前), pitch>0 向下俯视。
  - 畸变用 OpenCV Brown-Conrady: 径向 k1,k2,k3 + 切向 p1,p2。
"""

import json
import math


def load(path):
    with open(path) as f:
        return json.load(f)


def overscanned(cfg, margin):
    """返回一个'外扩 margin 像素'的配置: 画布每边+margin, 主点同步平移, 焦距不变。

    用于渲染时多渲一圈, 加畸变后再裁回原分辨率, 消除边角黑边。margin<=0 时原样返回。
    """
    if margin <= 0:
        return cfg
    c = json.loads(json.dumps(cfg))
    w, h = resolution(cfg)
    fx, fy, cx, cy = intrinsics(cfg)
    c["resolution"] = {"width": w + 2 * margin, "height": h + 2 * margin}
    c["intrinsics"] = {"fx": fx, "fy": fy, "cx": cx + margin, "cy": cy + margin}
    return c


def resolution(cfg):
    r = cfg["resolution"]
    return int(r["width"]), int(r["height"])


def fov_x_rad(cfg):
    """把配置里的 FOV 统一换算成水平全角(弧度)。"""
    w, h = resolution(cfg)
    fov = cfg["fov"]
    val = math.radians(float(fov["degrees"]))
    axis = fov.get("axis", "horizontal")
    if axis == "vertical":
        return 2.0 * math.atan(math.tan(val / 2.0) * w / h)
    if axis == "diagonal":
        d = math.hypot(w, h)
        fdiag = (d / 2.0) / math.tan(val / 2.0)
        return 2.0 * math.atan((w / 2.0) / fdiag)
    return val


def intrinsics(cfg):
    """返回 (fx, fy, cx, cy)。有标定 intrinsics 则用之(支持离心主点/fx!=fy), 否则由 fov 推(方形像素+居中)。"""
    intr = cfg.get("intrinsics")
    if intr and all(k in intr for k in ("fx", "fy", "cx", "cy")):
        return float(intr["fx"]), float(intr["fy"]), float(intr["cx"]), float(intr["cy"])
    w, h = resolution(cfg)
    fx = (w / 2.0) / math.tan(fov_x_rad(cfg) / 2.0)
    return fx, fx, w / 2.0, h / 2.0


def dist_coeffs(cfg):
    d = cfg.get("distortion", {})
    return (d.get("k1", 0.0), d.get("k2", 0.0), d.get("k3", 0.0),
            d.get("p1", 0.0), d.get("p2", 0.0))


def has_distortion(cfg):
    return any(abs(c) > 1e-12 for c in dist_coeffs(cfg))


def mount_rpy_rad(cfg):
    m = cfg["mount"]
    return (math.radians(m.get("roll_deg", 0.0)),
            math.radians(m.get("pitch_deg", 0.0)),
            math.radians(m.get("yaw_deg", 0.0)))


def forward_vector(cfg):
    """由 yaw/pitch 得到相机光轴前向单位向量(世界系)。yaw=0->-Y, pitch>0 向下。"""
    _roll, pitch, yaw = mount_rpy_rad(cfg)
    return (math.cos(pitch) * math.sin(yaw),
            -math.cos(pitch) * math.cos(yaw),
            -math.sin(pitch))


# ---------------- Blender 侧 ----------------

def blender_intrinsic_params(cfg, sensor_width_mm=36.0):
    """K(fx,fy,cx,cy) -> Blender 相机参数 (基于 BlenderProc/stackexchange 120063)。

    返回 dict: lens_mm, sensor_width_mm, pixel_aspect_x/y, shift_x/y。支持离心主点与 fx!=fy。
    """
    w, h = resolution(cfg)
    fx, fy, cx, cy = intrinsics(cfg)
    pax = pay = 1.0
    if fx > fy:
        pay = fx / fy
    elif fx < fy:
        pax = fy / fx
    par = pay / pax                                   # pixel_aspect_ratio
    view_fac_px = w if (pax * w >= pay * h) else par * h   # sensor_fit=AUTO
    return {
        "lens_mm": fx * sensor_width_mm / view_fac_px,
        "sensor_width_mm": sensor_width_mm,
        "pixel_aspect_x": pax,
        "pixel_aspect_y": pay,
        "shift_x": (cx - (w - 1) / 2.0) / -view_fac_px,
        "shift_y": (cy - (h - 1) / 2.0) / view_fac_px * par,
    }


def place_camera_from_config(cam_obj, cfg, target, distance):
    """按配置设置相机: 分辨率、完整内参(含离心主点)、由安装角决定朝向, 沿光轴反向退 distance 看向 target。"""
    import bpy
    from mathutils import Vector, Quaternion

    scene = bpy.context.scene
    w, h = resolution(cfg)
    scene.render.resolution_x = w
    scene.render.resolution_y = h
    scene.render.resolution_percentage = 100

    bp = blender_intrinsic_params(cfg)
    scene.render.pixel_aspect_x = bp["pixel_aspect_x"]
    scene.render.pixel_aspect_y = bp["pixel_aspect_y"]
    cd = cam_obj.data
    cd.sensor_fit = "AUTO"
    cd.sensor_width = bp["sensor_width_mm"]
    cd.lens_unit = "MILLIMETERS"
    cd.lens = bp["lens_mm"]
    cd.shift_x = bp["shift_x"]
    cd.shift_y = bp["shift_y"]

    fwd = Vector(forward_vector(cfg))
    cam_obj.location = Vector(target) - fwd * distance
    quat = fwd.to_track_quat("-Z", "Y")
    roll, _pitch, _yaw = mount_rpy_rad(cfg)
    if abs(roll) > 1e-9:
        quat = quat @ Quaternion((0.0, 0.0, 1.0), roll)   # 绕光轴滚转
    cam_obj.rotation_mode = "QUATERNION"
    cam_obj.rotation_quaternion = quat
    scene.camera = cam_obj
    return cam_obj


# ---------------- 系统 Python 侧 (numpy) ----------------

def distort_points(pts, cfg):
    """理想针孔像素坐标 -> 加畸变后的像素坐标 (前向模型)。pts: (N,2)。"""
    import numpy as np

    fx, fy, cx, cy = intrinsics(cfg)
    k1, k2, k3, p1, p2 = dist_coeffs(cfg)
    pts = np.asarray(pts, dtype=float)
    x = (pts[:, 0] - cx) / fx
    y = (pts[:, 1] - cy) / fy
    r2 = x * x + y * y
    radial = 1.0 + k1 * r2 + k2 * r2 ** 2 + k3 * r2 ** 3
    xd = x * radial + 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x)
    yd = y * radial + p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y
    return np.stack([fx * xd + cx, fy * yd + cy], axis=1)


def _bilinear(img, mx, my):
    import numpy as np

    H, W = img.shape[:2]
    x0 = np.floor(mx).astype(int)
    y0 = np.floor(my).astype(int)
    x1, y1 = x0 + 1, y0 + 1
    wx, wy = mx - x0, my - y0
    cx0, cx1 = np.clip(x0, 0, W - 1), np.clip(x1, 0, W - 1)
    cy0, cy1 = np.clip(y0, 0, H - 1), np.clip(y1, 0, H - 1)
    Ia, Ib = img[cy0, cx0], img[cy0, cx1]
    Ic, Id = img[cy1, cx0], img[cy1, cx1]
    wa = ((1 - wx) * (1 - wy))[..., None]
    wb = (wx * (1 - wy))[..., None]
    wc = ((1 - wx) * wy)[..., None]
    wd = (wx * wy)[..., None]
    out = Ia * wa + Ib * wb + Ic * wc + Id * wd
    valid = (mx >= 0) & (mx <= W - 1) & (my >= 0) & (my <= H - 1)
    out[~valid] = 0
    return out


def distort_image(arr, cfg, iters=8, margin=0, ssaa=1):
    """给理想针孔图加畸变。

    arr: (H,W,C) 理想图; 若 margin>0, arr 应是外扩过的大图(每边多 margin, 以基准像素计)。
    ssaa>1 时, arr 是超采样后的高分图(尺寸 = 外扩尺寸*ssaa), 本函数在 基准*ssaa 网格上
    直接从高分图采样, 返回 (H*ssaa, W*ssaa, C) 的高分畸变图, 由调用方再做一次高质量降采样。
    这样畸变只在最高分辨率上采样一次, 避免"先降采样再重采样"的二次模糊。
    """
    import numpy as np

    fx, fy, cx, cy = intrinsics(cfg)          # 目标(标定)内参, 基准像素单位
    k1, k2, k3, p1, p2 = dist_coeffs(cfg)
    if arr.ndim == 2:
        arr = arr[..., None]
    W, H = resolution(cfg)                    # 目标输出尺寸(基准)
    Wo, Ho = W * ssaa, H * ssaa
    xs, ys = np.meshgrid(np.arange(Wo), np.arange(Ho))
    xd = (xs / ssaa - cx) / fx                # 输出网格换算回基准像素再归一化
    yd = (ys / ssaa - cy) / fy
    x, y = xd.copy(), yd.copy()
    for _ in range(iters):                      # 迭代反解: 去畸变得到理想归一化坐标
        r2 = x * x + y * y
        radial = 1.0 + k1 * r2 + k2 * r2 ** 2 + k3 * r2 ** 3
        dx = 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x)
        dy = p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y
        x = (xd - dx) / radial
        y = (yd - dy) / radial
    mx = ((fx * x + cx + margin) * ssaa).astype(np.float32)   # 采样到高分外扩图坐标系
    my = ((fy * y + cy + margin) * ssaa).astype(np.float32)
    out = _bilinear(arr.astype(np.float32), mx, my)
    return np.clip(out, 0, 255).astype(arr.dtype) if arr.dtype != np.float32 else out
