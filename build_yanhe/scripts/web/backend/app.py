"""烟盒三维建模网页工具 · FastAPI 后端。

职责:
  - 提供前端静态页 (Vue3 + Three.js, 免打包 CDN 方案)。
  - 列出/读取 raw 原图, 保存/读取校正后的面图 faces/。
  - 服务端做透视校正 (复用 common.find_coeffs + PIL), 去背景。
  - 保存/读取三边长 box.json 与最终 box_model.json (几何用 common 权威计算)。

启动:
  python build_yanhe/scripts/web/backend/app.py            # 默认 127.0.0.1:8000
  或 BUILD=/path RAW=/path python .../app.py --port 8000

目录 (默认): build_yanhe/{raw, faces, box.json, box_model.json}
"""

from __future__ import annotations

import argparse
import os
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel

# 定位目录: 本文件在 build_yanhe/scripts/web/backend/app.py
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.abspath(os.path.join(_HERE, "..", ".."))       # build_yanhe/scripts
_BUILD = os.path.abspath(os.path.join(_SCRIPTS, ".."))            # build_yanhe
_FRONTEND = os.path.abspath(os.path.join(_HERE, "..", "frontend"))

sys.path.insert(0, _SCRIPTS)
import common  # noqa: E402

BUILD_DIR = os.environ.get("BUILD", _BUILD)
RAW_DIR = os.environ.get("RAW", os.path.join(BUILD_DIR, "raw"))
FACES_DIR = os.environ.get("FACES", os.path.join(BUILD_DIR, "faces"))
MODEL_PATH = os.path.join(BUILD_DIR, "box_model.json")

_IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")

app = FastAPI(title="Yanhe 3D Box Builder")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


def _list_images(d):
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d)
                  if f.lower().endswith(_IMG_EXT) and not f.startswith("."))


def _safe_join(base, name):
    """防目录穿越: 只允许 base 下的文件名。"""
    name = os.path.basename(name)
    p = os.path.join(base, name)
    return p


# ---------------- 数据模型 ----------------

class Dims(BaseModel):
    length_x: float
    width_y: float
    height_z: float
    units: str = "mm"


class RectifyReq(BaseModel):
    src: str                        # raw 文件名
    face: str                       # front/back/left/right/top/bottom
    corners: list[list[float]]      # 4 个 [x,y], 顺序 TL,TR,BR,BL (原图像素)
    long_px: int = 1200


class FaceAssign(BaseModel):
    image: str | None = None        # faces 文件名 (相对 faces/)
    rot: int = 0                    # 顺时针 0/90/180/270
    flip: bool = False


class ModelReq(BaseModel):
    dims: Dims
    faces: dict[str, FaceAssign]


# ---------------- 接口 ----------------

@app.get("/api/state")
def get_state():
    dims = common.load_dims(BUILD_DIR)
    a = b = c = None
    if dims:
        a, b, c = common.dims_tuple(dims)
    faces_meta = {}
    for face in common.FACE_ORDER:
        info = {
            "cn": common.FACE_CN[face],
            "normal": list(common.FACE_NORMAL[face]),
        }
        if a is not None:
            fw, fh = common.face_size(face, a, b, c)
            info["size_units"] = [fw, fh]
            info["corners"] = [c.tolist() for c in common.face_corners(face, a, b, c)]
        # 该面默认对应的已有校正图
        fpath = _safe_join(FACES_DIR, f"{face}.png")
        info["image"] = f"{face}.png" if os.path.exists(fpath) else None
        faces_meta[face] = info

    model = None
    if os.path.exists(MODEL_PATH):
        import json
        try:
            with open(MODEL_PATH, "r", encoding="utf-8") as f:
                model = json.load(f)
        except Exception:
            model = None

    return {
        "dims": dims,
        "raw": _list_images(RAW_DIR),
        "faces_available": _list_images(FACES_DIR),
        "face_order": common.FACE_ORDER,
        "faces_meta": faces_meta,
        "model": model,
        "paths": {"build": BUILD_DIR, "raw": RAW_DIR, "faces": FACES_DIR,
                  "model": MODEL_PATH},
    }


@app.post("/api/dims")
def set_dims(d: Dims):
    path = common.save_dims(BUILD_DIR, d.length_x, d.width_y, d.height_z, d.units)
    return {"ok": True, "path": path}


@app.get("/raw/{name}")
def get_raw(name: str):
    p = _safe_join(RAW_DIR, name)
    if not os.path.exists(p):
        raise HTTPException(404, "raw not found")
    return FileResponse(p)


@app.get("/faces/{name}")
def get_face(name: str):
    p = _safe_join(FACES_DIR, name)
    if not os.path.exists(p):
        raise HTTPException(404, "face not found")
    return FileResponse(p, headers={"Cache-Control": "no-store"})


@app.post("/api/rectify")
def rectify(req: RectifyReq):
    if req.face not in common.FACE_ORDER:
        raise HTTPException(400, f"unknown face {req.face}")
    if len(req.corners) != 4:
        raise HTTPException(400, "corners must have 4 points")
    dims = common.load_dims(BUILD_DIR)
    if not dims:
        raise HTTPException(400, "请先设置三边长 (box.json)")
    a, b, c = common.dims_tuple(dims)
    src_path = _safe_join(RAW_DIR, req.src)
    if not os.path.exists(src_path):
        raise HTTPException(404, f"raw not found: {req.src}")

    # 关键: 按 EXIF 把图转正, 使 PIL 的像素空间与浏览器显示(及描点坐标)一致。
    # 否则手机竖拍(EXIF Orientation)时坐标错位, 框会落到错误区域并带入背景。
    im = ImageOps.exif_transpose(Image.open(src_path)).convert("RGB")

    fw, fh = common.face_size(req.face, a, b, c)
    out_w, out_h = common.output_size(fw, fh, req.long_px)
    corners = [(float(x), float(y)) for x, y in req.corners]

    # 按描点四边形的横/竖朝向决定输出方向: 保持该面真实比例, 又不会把竖拍的面
    # 硬塞进横向框而拉伸变形。最终朝向在第②步用"旋转90°"摆正即可。
    import math
    w_tr = (math.dist(corners[0], corners[1]) + math.dist(corners[3], corners[2])) / 2
    h_tr = (math.dist(corners[0], corners[3]) + math.dist(corners[1], corners[2])) / 2
    if (w_tr >= h_tr) != (out_w >= out_h):
        out_w, out_h = out_h, out_w

    dst = [(0, 0), (out_w, 0), (out_w, out_h), (0, out_h)]
    coeffs = common.find_coeffs(dst, corners)
    warped = im.transform((out_w, out_h), Image.PERSPECTIVE, coeffs,
                          resample=Image.BICUBIC).convert("RGBA")
    os.makedirs(FACES_DIR, exist_ok=True)
    out_name = f"{req.face}.png"
    warped.save(_safe_join(FACES_DIR, out_name))
    return {"ok": True, "image": out_name, "size": [out_w, out_h],
            "face_size_units": [fw, fh]}


@app.post("/api/model")
def save_model(req: ModelReq):
    import json
    d = req.dims
    common.save_dims(BUILD_DIR, d.length_x, d.width_y, d.height_z, d.units)
    a, b, c = d.length_x, d.width_y, d.height_z

    faces_out = {}
    names = ["TL", "TR", "BR", "BL"]
    for face in common.FACE_ORDER:
        assign = req.faces.get(face, FaceAssign())
        corners = common.face_corners(face, a, b, c)
        corner_map = {n: [round(float(v), 4) for v in corners[i]]
                      for i, n in enumerate(names)}
        fw, fh = common.face_size(face, a, b, c)
        img_rel = None
        if assign.image:
            img_rel = os.path.relpath(_safe_join(FACES_DIR, assign.image), BUILD_DIR)
        faces_out[face] = {
            "cn": common.FACE_CN[face],
            "normal": list(common.FACE_NORMAL[face]),
            "size_units": [fw, fh],
            "image": img_rel,
            "texture_rotation_cw_deg": int(assign.rot) % 360,
            "texture_flip_horizontal": bool(assign.flip),
            "corners_box_coords": corner_map,
            "uv": {"TL": [0, 0], "TR": [1, 0], "BR": [1, 1], "BL": [0, 1]},
        }

    data = {
        "_note": "烟盒三维模型描述 (网页工具导出)。下游按 orientation_guide 构建带贴图模型。",
        "convention": {
            "axes": "X=长(length_x), Y=宽(width_y), Z=高(height_z)",
            "origin": "底面中心 (盒子位于 z∈[0, height_z], XY 居中)",
            "front_faces": "+X 方向 (前/后面在 YOZ 平面, 法线沿 X)",
            "units": d.units,
            "corner_order": "每个面按 [TL,TR,BR,BL] 记录, 对应贴图像素 (0,0),(W,0),(W,H),(0,H)",
        },
        "dimensions": {"length_x": a, "width_y": b, "height_z": c},
        "faces": faces_out,
        "orientation_guide": (
            "构建步骤: 1) 建尺寸 length_x×width_y×height_z 的长方体, 原点在底面中心 (盒子位于 z∈[0,height_z], XY 居中)。 "
            "2) 每个面若 image 非空则加载贴图; 先按 texture_flip_horizontal 水平镜像, "
            "再按 texture_rotation_cw_deg 顺时针旋转。 "
            "3) 把贴图四角 (0,0)/(W,0)/(W,H)/(0,H) 分别贴到该面 corners_box_coords 的 "
            "TL/TR/BR/BL (盒内坐标, 单位见 convention.units)。 "
            "4) normal 为该面朝外世界法线, 正面 front 朝 +X (前/后面在 YOZ 平面), 用于判断朝向。"
        ),
    }
    with open(MODEL_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"ok": True, "path": MODEL_PATH, "model": data}


# 前端静态页挂在根路径 (放在所有 API 之后)
if os.path.isdir(_FRONTEND):
    app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    import uvicorn
    print(f"[Yanhe] build={BUILD_DIR}\n[Yanhe] 打开 http://{args.host}:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
