"""FastAPI 后端: 编排"选品/条数/变化 -> 渲染 -> labelme 导出"。

不在本进程内跑 bpy; 而是按前端参数生成临时配置, 依次调用:
  1) build_skus.py(系统 Python, 确保各 SKU 已构建)
  2) render_dataset.py(Blender 无头, 出外扩渲染图 + 几何 JSON)
  3) export_labelme.py(系统 Python, 加畸变 + 写 <保存位置>/raw_img_json/*.png,*.json)

启动:
  pip install -r pipeline/web/backend/requirements.txt
  python pipeline/web/backend/app.py            # 默认 127.0.0.1:8000
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from pipeline.core import config                       # noqa: E402

_FRONTEND = os.path.abspath(os.path.join(_HERE, "..", "frontend"))
_RUNNERS = os.path.join(_REPO, "pipeline", "runners")
_BLENDER = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
_RESERVED = {"scripts"}

app = FastAPI(title="Yancao 合成数据集工具")


# ---------------- SKU 列表 ----------------

def list_skus():
    cfg = config.load()
    root = config.abspath(cfg["paths"]["sku_root"])
    out = []
    if not os.path.isdir(root):
        return out
    for d in sorted(os.listdir(root)):
        if d in _RESERVED or d.startswith(".") or d.startswith("__"):
            continue
        ddir = os.path.join(root, d)
        if not (os.path.isdir(ddir) and os.path.exists(os.path.join(ddir, "box_model.json"))):
            continue
        dims = None
        box = os.path.join(ddir, "box.json")
        if os.path.exists(box):
            with open(box, encoding="utf-8") as f:
                b = json.load(f)
            dims = [b.get("length_x"), b.get("width_y"), b.get("height_z")]
        out.append({"name": d, "dims_mm": dims,
                    "built": os.path.exists(os.path.join(ddir, f"{d}.blend"))})
    return out


@app.get("/api/skus")
def api_skus():
    cfg = config.load()
    return {"skus": list_skus(),
            "camera_layers": cfg["placement"]["layers"],
            "defaults": {"yaw": cfg["placement"]["yaw_deg"],
                         "pos_jitter": cfg["placement"]["pos_jitter_m"],
                         "top_power": cfg["lights"]["top_power"],
                         "ambient": cfg["lights"]["ambient"]}}


# ---------------- 渲染请求 ----------------

class SkuCount(BaseModel):
    name: str
    count: int = 1


class RenderReq(BaseModel):
    skus: list[SkuCount]
    yaw: list[float] = [-25.0, 25.0]
    pos_jitter: float = 0.008
    layers: list[int] = [1, 2]
    top_power: list[float] = [150.0, 260.0]
    ambient: list[float] = [0.30, 0.55]
    num: int = 8
    save_dir: str = ""
    variant: str = "dist"


def _run(cmd, tag):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise HTTPException(500, detail=f"[{tag}] 失败(码 {r.returncode})\n"
                                        f"{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return r.stdout


@app.post("/api/render")
def api_render(req: RenderReq):
    comp = {s.name: int(s.count) for s in req.skus if s.count > 0}
    if not comp:
        raise HTTPException(400, "请至少选择一种 SKU 且条数>0")
    if not req.save_dir:
        raise HTTPException(400, "请填写保存位置")

    save_dir = os.path.abspath(req.save_dir)
    os.makedirs(save_dir, exist_ok=True)

    cfg = config.load()
    cfg = copy.deepcopy(cfg)
    cfg["placement"]["composition"] = comp
    cfg["placement"]["yaw_deg"] = req.yaw
    cfg["placement"]["pos_jitter_m"] = req.pos_jitter
    cfg["placement"]["layers"] = req.layers
    cfg["lights"]["top_power"] = req.top_power
    cfg["lights"]["ambient"] = req.ambient
    cfg["dataset"]["num_frames"] = req.num
    cfg["dataset"]["seed"] = int(time.time()) % 1_000_000     # 每次不同
    cfg["paths"]["out_dir"] = os.path.join(save_dir, "_work")

    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(cfg, tmp, ensure_ascii=False)
    tmp.close()
    cfgpath = tmp.name
    prefix = time.strftime("%Y%m%d_%H%M%S_")

    try:
        _run([sys.executable, os.path.join(_RUNNERS, "build_skus.py"), "--config", cfgpath],
             "build_skus")
        _run([_BLENDER, "--background", "--python", os.path.join(_RUNNERS, "render_dataset.py"),
              "--", "--config", cfgpath, "--num", str(req.num)], "render")
        _run([sys.executable, os.path.join(_RUNNERS, "export_labelme.py"),
              "--config", cfgpath, "--dst", save_dir, "--variant", req.variant,
              "--prefix", prefix], "labelme")
    finally:
        os.unlink(cfgpath)

    raw = os.path.join(save_dir, "raw_img_json")
    imgs = sorted(f for f in os.listdir(raw) if f.startswith(prefix) and f.endswith(".png"))
    return {"ok": True, "dir": raw, "count": len(imgs),
            "images": [f"/api/image?path={os.path.join(raw, n)}" for n in imgs]}


@app.get("/api/image")
def api_image(path: str):
    path = os.path.abspath(path)
    if not (path.endswith(".png") and os.path.exists(path)):
        raise HTTPException(404, "not found")
    return FileResponse(path)


# ---------------- 前端静态页 ----------------

@app.get("/")
def index():
    return FileResponse(os.path.join(_FRONTEND, "index.html"))


app.mount("/static", StaticFiles(directory=_FRONTEND), name="static")


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
