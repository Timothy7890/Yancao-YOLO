"""烟盒三维建模网页工具 · FastAPI 后端 (多产品/SKU 版)。

目录规范:
  build_yanhe/
    scripts/                 # 代码
    <Product>/               # 每个烟盒(SKU)一个目录, 如 Huangjinye
      raw/                   # 手机原图
      faces/                 # 校正后的面图
      box.json               # 三边长
      box_model.json         # 导出的模型描述

职责:
  - 提供前端静态页 (Vue3 + Three.js)。
  - 列出/新建产品; 按产品读写 raw/faces/box.json/box_model.json。
  - 服务端透视校正 (复用 common.find_coeffs + PIL) + 去背景。

启动:
  python build_yanhe/scripts/web/backend/app.py            # 默认 127.0.0.1:8000
  或 BUILD=/path python .../app.py --port 8000
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
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

# 产品(SKU)目录都放在 BUILD_DIR 下; scripts 不是产品。
BUILD_DIR = os.environ.get("BUILD", _BUILD)
_RESERVED = {"scripts"}
_IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")
_NAME_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{1,64}$")

app = FastAPI(title="Yanhe 3D Box Builder")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


# ---------------- 产品目录 ----------------

def _valid_name(name: str) -> bool:
    return bool(name) and name not in _RESERVED and bool(_NAME_RE.match(name)) \
        and name == os.path.basename(name)


def product_dir(product: str) -> str:
    if not _valid_name(product):
        raise HTTPException(400, f"非法产品名: {product}")
    return os.path.join(BUILD_DIR, product)


def raw_dir(product):
    return os.path.join(product_dir(product), "raw")


def faces_dir(product):
    return os.path.join(product_dir(product), "faces")


def model_path(product):
    return os.path.join(product_dir(product), "box_model.json")


def list_products():
    out = []
    if os.path.isdir(BUILD_DIR):
        for d in sorted(os.listdir(BUILD_DIR)):
            p = os.path.join(BUILD_DIR, d)
            if os.path.isdir(p) and d not in _RESERVED and not d.startswith(".") \
                    and not d.startswith("__"):
                out.append(d)
    return out


def _list_images(d):
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d)
                  if f.lower().endswith(_IMG_EXT) and not f.startswith("."))


def _safe_join(base, name):
    return os.path.join(base, os.path.basename(name))


# ---------------- 数据模型 ----------------

class Dims(BaseModel):
    length_x: float
    width_y: float
    height_z: float
    units: str = "mm"


class DimsReq(Dims):
    product: str


class NewProductReq(BaseModel):
    name: str


class RectifyReq(BaseModel):
    product: str
    src: str
    face: str
    corners: list[list[float]]      # 4 个 [x,y], 顺序 TL,TR,BR,BL (原图像素)
    long_px: int = 1200


class FaceAssign(BaseModel):
    image: str | None = None
    rot: int = 0
    flip: bool = False


class ModelReq(BaseModel):
    product: str
    dims: Dims
    faces: dict[str, FaceAssign]


# ---------------- 接口 ----------------

@app.get("/api/products")
def get_products():
    return {"products": list_products()}


@app.post("/api/products")
def create_product(req: NewProductReq):
    name = (req.name or "").strip()
    if not _valid_name(name):
        raise HTTPException(400, "产品名只能含 字母/数字/下划线/连字符/中文, 长度≤64")
    d = os.path.join(BUILD_DIR, name)
    if os.path.exists(d):
        raise HTTPException(409, f"产品已存在: {name}")
    os.makedirs(os.path.join(d, "raw"), exist_ok=True)
    os.makedirs(os.path.join(d, "faces"), exist_ok=True)
    return {"ok": True, "product": name, "products": list_products()}


@app.get("/api/state")
def get_state(product: str):
    pdir = product_dir(product)
    if not os.path.isdir(pdir):
        raise HTTPException(404, f"产品不存在: {product}")
    dims = common.load_dims(pdir)
    a = b = c = None
    if dims:
        a, b, c = common.dims_tuple(dims)
    fdir = faces_dir(product)
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
        fpath = _safe_join(fdir, f"{face}.png")
        info["image"] = f"{face}.png" if os.path.exists(fpath) else None
        faces_meta[face] = info

    model = None
    mp = model_path(product)
    if os.path.exists(mp):
        try:
            with open(mp, "r", encoding="utf-8") as f:
                model = json.load(f)
        except Exception:
            model = None

    return {
        "product": product,
        "dims": dims,
        "raw": _list_images(raw_dir(product)),
        "faces_available": _list_images(fdir),
        "face_order": common.FACE_ORDER,
        "faces_meta": faces_meta,
        "model": model,
    }


@app.post("/api/dims")
def set_dims(d: DimsReq):
    pdir = product_dir(d.product)
    if not os.path.isdir(pdir):
        raise HTTPException(404, f"产品不存在: {d.product}")
    path = common.save_dims(pdir, d.length_x, d.width_y, d.height_z, d.units)
    return {"ok": True, "path": path}


@app.get("/raw/{product}/{name}")
def get_raw(product: str, name: str):
    p = _safe_join(raw_dir(product), name)
    if not os.path.exists(p):
        raise HTTPException(404, "raw not found")
    return FileResponse(p)


@app.get("/faces/{product}/{name}")
def get_face(product: str, name: str):
    p = _safe_join(faces_dir(product), name)
    if not os.path.exists(p):
        raise HTTPException(404, "face not found")
    return FileResponse(p, headers={"Cache-Control": "no-store"})


@app.post("/api/rectify")
def rectify(req: RectifyReq):
    if req.face not in common.FACE_ORDER:
        raise HTTPException(400, f"unknown face {req.face}")
    if len(req.corners) != 4:
        raise HTTPException(400, "corners must have 4 points")
    pdir = product_dir(req.product)
    dims = common.load_dims(pdir)
    if not dims:
        raise HTTPException(400, "请先设置三边长 (box.json)")
    a, b, c = common.dims_tuple(dims)
    src_path = _safe_join(raw_dir(req.product), req.src)
    if not os.path.exists(src_path):
        raise HTTPException(404, f"raw not found: {req.src}")

    # 按 EXIF 转正, 使 PIL 像素空间与浏览器显示(描点坐标)一致。
    im = ImageOps.exif_transpose(Image.open(src_path)).convert("RGB")

    fw, fh = common.face_size(req.face, a, b, c)
    out_w, out_h = common.output_size(fw, fh, req.long_px)
    corners = [(float(x), float(y)) for x, y in req.corners]

    # 按描点四边形横/竖朝向决定输出方向: 保持真实比例又不拉伸变形。
    w_tr = (math.dist(corners[0], corners[1]) + math.dist(corners[3], corners[2])) / 2
    h_tr = (math.dist(corners[0], corners[3]) + math.dist(corners[1], corners[2])) / 2
    if (w_tr >= h_tr) != (out_w >= out_h):
        out_w, out_h = out_h, out_w

    dst = [(0, 0), (out_w, 0), (out_w, out_h), (0, out_h)]
    coeffs = common.find_coeffs(dst, corners)
    warped = im.transform((out_w, out_h), Image.PERSPECTIVE, coeffs,
                          resample=Image.BICUBIC).convert("RGBA")
    fdir = faces_dir(req.product)
    os.makedirs(fdir, exist_ok=True)
    out_name = f"{req.face}.png"
    warped.save(_safe_join(fdir, out_name))
    return {"ok": True, "image": out_name, "size": [out_w, out_h],
            "face_size_units": [fw, fh]}


@app.post("/api/model")
def save_model(req: ModelReq):
    pdir = product_dir(req.product)
    if not os.path.isdir(pdir):
        raise HTTPException(404, f"产品不存在: {req.product}")
    d = req.dims
    common.save_dims(pdir, d.length_x, d.width_y, d.height_z, d.units)
    a, b, c = d.length_x, d.width_y, d.height_z

    faces_out = {}
    names = ["TL", "TR", "BR", "BL"]
    for face in common.FACE_ORDER:
        assign = req.faces.get(face, FaceAssign())
        corners = common.face_corners(face, a, b, c)
        corner_map = {n: [round(float(v), 4) for v in corners[i]]
                      for i, n in enumerate(names)}
        fw, fh = common.face_size(face, a, b, c)
        img_rel = f"faces/{os.path.basename(assign.image)}" if assign.image else None
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
        "product": req.product,
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
            "2) 每个面若 image 非空则加载贴图(相对本产品目录); 先按 texture_flip_horizontal 水平镜像, "
            "再按 texture_rotation_cw_deg 顺时针旋转。 "
            "3) 把贴图四角 (0,0)/(W,0)/(W,H)/(0,H) 分别贴到该面 corners_box_coords 的 "
            "TL/TR/BR/BL (盒内坐标, 单位见 convention.units)。 "
            "4) normal 为该面朝外世界法线, 正面 front 朝 +X (前/后面在 YOZ 平面), 用于判断朝向。"
        ),
    }
    with open(model_path(req.product), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"ok": True, "path": model_path(req.product), "model": data}


# 前端静态页挂在根路径 (放在所有 API 之后)
if os.path.isdir(_FRONTEND):
    app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    import uvicorn
    print(f"[Yanhe] build={BUILD_DIR}  产品: {list_products()}")
    print(f"[Yanhe] 打开 http://{args.host}:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
