"""烟盒三维重建公共库。

坐标约定:
  - X = 长 (length),  Y = 宽 (width),  Z = 高 (height)
  - 原点 = 底面中心; 盒子位于 z ∈ [0, height], XY 在 [-长/2,长/2]×[-宽/2,宽/2] 居中。
    (即模型"站"在 z=0 平面上, 原点落在底面正中, 便于摆到货架层板上。)
  - 前/后面在 YOZ 平面 (法线沿 X); 左/右面在 XOZ 平面 (法线沿 Y);
    顶/底面在 XOY 平面 (法线沿 Z)。
  - 6 个面及其外法线:
        front  前  +X      back   后  -X      (YOZ 平面, 尺寸 宽Y×高Z)
        left   左  -Y      right  右  +Y      (XOZ 平面, 尺寸 长X×高Z)
        top    顶  +Z      bottom 底  -Z      (XOY 平面, 尺寸 长X×宽Y)

每个面的 4 个纹理角点固定按 [TL, TR, BR, BL] (左上/右上/右下/左下) 顺序给出,
对应贴图像素 (0,0)/(W,0)/(W,H)/(0,H)。脚本一按此顺序采点, 脚本二按此顺序贴图,
导出的 JSON 也按此顺序记录, 三者一致, 下游 Blender 可直接使用。

只依赖 numpy (+ 调用方按需 PIL/matplotlib)。
"""

from __future__ import annotations

import json
import os

import numpy as np

# ---------------- 面定义 ----------------

FACE_ORDER = ["front", "back", "left", "right", "top", "bottom"]

FACE_CN = {
    "front": "前", "back": "后",
    "left": "左", "right": "右",
    "top": "顶", "bottom": "底",
}

FACE_NORMAL = {
    "front": (1.0, 0.0, 0.0),
    "back": (-1.0, 0.0, 0.0),
    "left": (0.0, -1.0, 0.0),
    "right": (0.0, 1.0, 0.0),
    "top": (0.0, 0.0, 1.0),
    "bottom": (0.0, 0.0, -1.0),
}


def face_size(face: str, a: float, b: float, c: float):
    """返回该面的 (宽 w, 高 h), 单位与边长相同。

    a=长(X), b=宽(Y), c=高(Z)。
      front/back (YOZ 平面): 宽=b(Y), 高=c(Z)
      left/right (XOZ 平面): 宽=a(X), 高=c(Z)
      top/bottom (XOY 平面): 宽=a(X), 高=b(Y)
    """
    if face in ("front", "back"):
        return (b, c)
    if face in ("left", "right"):
        return (a, c)
    return (a, b)  # top / bottom


def face_corners(face: str, a: float, b: float, c: float):
    """返回该面 4 个纹理角点 [TL, TR, BR, BL] 在盒内坐标系的 3D 坐标 (np.array)。

    约定: 原点=底面中心, 盒子位于 z∈[0, c]; 从盒子外部正视该面时, 图片上边朝 +Z
    (顶/底面朝 +Y), 使贴图正立。
    """
    hx, hy, hz = a / 2.0, b / 2.0, c / 2.0
    table = {
        # 正视 +X 方向看 (viewer 在 +X): 右=+Y, 上=+Z
        "front": [(hx, -hy, hz), (hx, hy, hz), (hx, hy, -hz), (hx, -hy, -hz)],
        # 正视 -X 方向看: 右=-Y, 上=+Z
        "back": [(-hx, hy, hz), (-hx, -hy, hz), (-hx, -hy, -hz), (-hx, hy, -hz)],
        # 正视 -Y 方向看: 右=+X, 上=+Z
        "left": [(-hx, -hy, hz), (hx, -hy, hz), (hx, -hy, -hz), (-hx, -hy, -hz)],
        # 正视 +Y 方向看: 右=-X, 上=+Z
        "right": [(hx, hy, hz), (-hx, hy, hz), (-hx, hy, -hz), (hx, hy, -hz)],
        # 俯视 +Z 方向看: 右=+X, 上=+Y
        "top": [(-hx, hy, hz), (hx, hy, hz), (hx, -hy, hz), (-hx, -hy, hz)],
        # 仰视 -Z 方向看: 右=-X, 上=+Y
        "bottom": [(hx, hy, -hz), (-hx, hy, -hz), (-hx, -hy, -hz), (hx, -hy, -hz)],
    }
    # 上表以几何中心为原点 (z∈[-hz,hz]); 平移到"原点=底面中心" (z∈[0,c])。
    return [np.array((x, y, z + hz), dtype=float) for (x, y, z) in table[face]]


# ---------------- box.json 尺寸配置 ----------------

def box_json_path(build_dir: str) -> str:
    return os.path.join(build_dir, "box.json")


def load_dims(build_dir: str):
    """读取 box.json, 返回 dict(length_x,width_y,height_z,units)。不存在返回 None。"""
    p = box_json_path(build_dir)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_dims(build_dir: str, length_x: float, width_y: float,
              height_z: float, units: str = "mm") -> str:
    """写 box.json, 返回路径。"""
    p = box_json_path(build_dir)
    data = {
        "_note": "烟盒三边长。X=长(length_x), Y=宽(width_y), Z=高(height_z)。",
        "units": units,
        "length_x": float(length_x),
        "width_y": float(width_y),
        "height_z": float(height_z),
    }
    os.makedirs(build_dir, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return p


def dims_tuple(dims: dict):
    """dict -> (a,b,c) = (length_x, width_y, height_z)。"""
    return (float(dims["length_x"]), float(dims["width_y"]), float(dims["height_z"]))


# ---------------- 透视校正 ----------------

def find_coeffs(dst_pts, src_pts):
    """求 PIL Image.transform(PERSPECTIVE) 的 8 个系数。

    PIL 的 PERSPECTIVE 是"输出->输入"映射:
        src_x = (c0*X + c1*Y + c2) / (c6*X + c7*Y + 1)
        src_y = (c3*X + c4*Y + c5) / (c6*X + c7*Y + 1)
    其中 (X,Y) 为输出图坐标 (dst_pts), (src_x,src_y) 为输入原图坐标 (src_pts)。

    dst_pts / src_pts: 均为 4 个 (x,y), 顺序一一对应 (这里用 TL,TR,BR,BL)。
    """
    matrix = []
    for (X, Y), (x, y) in zip(dst_pts, src_pts):
        matrix.append([X, Y, 1, 0, 0, 0, -x * X, -x * Y])
        matrix.append([0, 0, 0, X, Y, 1, -y * X, -y * Y])
    A = np.array(matrix, dtype=float)
    B = np.array(src_pts, dtype=float).reshape(8)
    res = np.linalg.solve(A, B)
    return res.tolist()


def output_size(face_w: float, face_h: float, long_px: int = 1200):
    """按真实边长比例算校正后输出分辨率, 使长边 = long_px。返回 (W, H)。"""
    if face_w <= 0 or face_h <= 0:
        return (long_px, long_px)
    if face_w >= face_h:
        w = long_px
        h = max(1, int(round(long_px * face_h / face_w)))
    else:
        h = long_px
        w = max(1, int(round(long_px * face_w / face_h)))
    return (w, h)
