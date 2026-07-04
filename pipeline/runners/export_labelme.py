"""入口(系统 Python): 由 frames/ 导出 labelme 标注到 <dst>/raw_img_json/。

每帧写 <stem>.png + <stem>.json(json 内嵌 base64)。默认用畸变图(贴近真实相机)。

用法:
    python3 pipeline/runners/export_labelme.py [--config ...] [--dst <保存位置>] \
        [--variant dist|ideal] [--prefix 20260704_]
"""

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from pipeline.core import config, labelme, postprocess    # noqa: E402


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=config.DEFAULT_CONFIG)
    ap.add_argument("--dst", default="", help="保存位置(其下建 raw_img_json/); 默认=out_dir")
    ap.add_argument("--variant", default="dist", choices=["dist", "ideal"])
    ap.add_argument("--prefix", default="", help="文件名前缀(便于多次运行不覆盖)")
    return ap.parse_args()


def main():
    args = parse_args()
    cfg = config.load(args.config)
    paths = config.resolved_paths(cfg)
    frames_dir = os.path.join(paths["out_dir"], "frames")
    dst_root = os.path.abspath(args.dst) if args.dst else paths["out_dir"]
    raw_dir = os.path.join(dst_root, "raw_img_json")
    os.makedirs(raw_dir, exist_ok=True)

    metas = sorted(f for f in os.listdir(frames_dir) if f.endswith(".json"))
    if not metas:
        raise SystemExit(f"没有帧数据: {frames_dir}")

    n = 0
    for m in metas:
        with open(os.path.join(frames_dir, m), "r", encoding="utf-8") as f:
            meta = json.load(f)
        fid = meta["frame_id"]
        arr = np.array(Image.open(os.path.join(frames_dir, meta["image"])).convert("RGBA"))
        res = postprocess.process_frame(meta, arr, meta["camera"])
        bw, bh = res["base_wh"]
        sel = res[args.variant]

        stem = f"{args.prefix}{fid:06d}"
        png_name = stem + ".png"
        png_path = os.path.join(raw_dir, png_name)
        Image.fromarray(sel["image"], "RGBA").convert("RGB").save(png_path)

        b64 = labelme.image_to_b64(png_path)
        doc = labelme.to_labelme(png_name, bw, bh, sel["objects"], image_b64=b64)
        with open(os.path.join(raw_dir, stem + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        n += 1

    print(f"[labelme] {n} 帧 -> {raw_dir} (variant={args.variant})")


if __name__ == "__main__":
    main()
