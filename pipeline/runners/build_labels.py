"""入口(系统 Python): 由 render_dataset 产出的 frames/ 组装 YOLO-pose 数据集。

默认用"畸变图"作为训练图(贴近真实相机); 理想图存到 debug/ 便于核对。
坐标换算集中在 core.postprocess。

用法:
    python3 pipeline/runners/build_labels.py [--config ...] [--variant dist|ideal]
"""

import argparse
import json
import os
import random
import sys

import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from pipeline.core import config, labels, postprocess    # noqa: E402


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=config.DEFAULT_CONFIG)
    ap.add_argument("--variant", default="dist", choices=["dist", "ideal"])
    return ap.parse_args()


def yolo_lines(objs, bw, bh, class_id):
    return [labels.to_yolo_pose(class_id, o["bbox"], o["kpts"], bw, bh) for o in objs]


def write_data_yaml(out_dir, cfg):
    lb = cfg["label"]
    txt = (f"path: {os.path.abspath(out_dir)}\n"
           f"train: images/train\nval: images/val\n"
           f"kpt_shape: [{lb['num_keypoints']}, 3]\n"
           f"flip_idx: [1, 0, 3, 2]\n"
           f"names:\n  {lb['class_id']}: {lb['class_name']}\n")
    with open(os.path.join(out_dir, "data.yaml"), "w", encoding="utf-8") as f:
        f.write(txt)


def main():
    args = parse_args()
    cfg = config.load(args.config)
    paths = config.resolved_paths(cfg)
    out_dir = paths["out_dir"]
    frames_dir = os.path.join(out_dir, "frames")
    metas = sorted(f for f in os.listdir(frames_dir) if f.endswith(".json"))
    if not metas:
        raise SystemExit(f"没有帧数据: {frames_dir}")

    ids = [int(m[len("frame_"):-len(".json")]) for m in metas]
    rng = random.Random(cfg["dataset"]["seed"])
    shuffled = ids[:]
    rng.shuffle(shuffled)
    n_val = int(round(len(shuffled) * cfg["dataset"]["val_ratio"]))
    val_set = set(shuffled[:n_val])

    for split in ("train", "val"):
        os.makedirs(os.path.join(out_dir, "images", split), exist_ok=True)
        os.makedirs(os.path.join(out_dir, "labels", split), exist_ok=True)
    debug_dir = os.path.join(out_dir, "debug")
    os.makedirs(debug_dir, exist_ok=True)

    class_id = cfg["label"]["class_id"]
    variant = args.variant
    for m in metas:
        with open(os.path.join(frames_dir, m), "r", encoding="utf-8") as f:
            meta = json.load(f)
        fid = meta["frame_id"]
        arr = postprocess.load_overscan(os.path.join(frames_dir, meta["image"]), meta)
        res = postprocess.process_frame(meta, arr, meta["camera"])
        bw, bh = res["base_wh"]

        split = "val" if fid in val_set else "train"
        stem = f"frame_{fid:06d}"
        sel = res[variant]
        Image.fromarray(sel["image"], "RGBA").save(
            os.path.join(out_dir, "images", split, stem + ".png"))
        lines = yolo_lines(sel["objects"], bw, bh, class_id)
        with open(os.path.join(out_dir, "labels", split, stem + ".txt"), "w") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))

        other = "ideal" if variant == "dist" else "dist"
        Image.fromarray(res[other]["image"], "RGBA").save(
            os.path.join(debug_dir, f"{stem}_{other}.png"))

    write_data_yaml(out_dir, cfg)
    print(f"[labels] {len(metas)} 帧 -> {out_dir} (train={len(ids)-n_val}, val={n_val}, 训练图={variant})")


if __name__ == "__main__":
    main()
