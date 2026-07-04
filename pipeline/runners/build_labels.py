"""入口(系统 Python): 由 render_dataset 产出的 frames/ 组装 YOLO-pose 数据集。

对每帧: 外扩理想图 -> (a)中心裁剪得理想针孔图; (b)加畸变得"真实相机"图。
关键点/检测框在两种图里各自换算, 导出 YOLO-pose txt, 并按 val_ratio 做 train/val 划分。
默认用"畸变图"作为训练图(贴近真实相机); 理想图存到 debug/ 便于核对。

用法:
    python3 pipeline/runners/build_labels.py [--config pipeline/config/dataset.json] [--variant dist|ideal]
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

from pipeline.core import camera as cammod            # noqa: E402
from pipeline.core import config, labels              # noqa: E402


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=config.DEFAULT_CONFIG)
    ap.add_argument("--variant", default="dist", choices=["dist", "ideal"],
                    help="训练集用哪种图: dist=加畸变(默认, 贴近真实相机), ideal=理想针孔")
    return ap.parse_args()


def _clip_pt(x, y, w, h):
    return min(max(x, 0.0), w), min(max(y, 0.0), h)


def _kpts_to_ideal(kpts, margin, bw, bh):
    out = []
    for kx, ky, v in kpts:
        x, y = kx - margin, ky - margin
        vis = 0 if (v == 0 or not (0 <= x <= bw and 0 <= y <= bh)) else int(v)
        out.append((x, y, vis))
    return out


def _kpts_to_dist(kpts_ideal, cam_cfg, bw, bh):
    pts = np.array([[x, y] for (x, y, _v) in kpts_ideal], dtype=float)
    dp = cammod.distort_points(pts, cam_cfg) if len(pts) else pts
    out = []
    for (x, y, v), (dx, dy) in zip(kpts_ideal, dp):
        vis = 0 if (v == 0 or not (0 <= dx <= bw and 0 <= dy <= bh)) else int(v)
        out.append((dx, dy, vis))
    return out


def _bbox_ideal(bbox_overscan, margin, bw, bh):
    x0, y0, x1, y1 = bbox_overscan
    x0, y0 = _clip_pt(x0 - margin, y0 - margin, bw, bh)
    x1, y1 = _clip_pt(x1 - margin, y1 - margin, bw, bh)
    return (x0, y0, x1, y1)


def _bbox_dist(bbox_ideal, cam_cfg, bw, bh):
    x0, y0, x1, y1 = bbox_ideal
    corners = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=float)
    d = cammod.distort_points(corners, cam_cfg)
    xs, ys = d[:, 0], d[:, 1]
    x0, y0 = _clip_pt(float(xs.min()), float(ys.min()), bw, bh)
    x1, y1 = _clip_pt(float(xs.max()), float(ys.max()), bw, bh)
    return (x0, y0, x1, y1)


def process_frame(meta, overscan_arr, cam_cfg, class_id):
    """返回 dict{ideal:(img,lines), dist:(img,lines)}。"""
    bw, bh = meta["base_width"], meta["base_height"]
    margin = meta["overscan_margin"]

    if margin > 0:
        ideal_img = overscan_arr[margin:margin + bh, margin:margin + bw]
    else:
        ideal_img = overscan_arr
    dist_img = cammod.distort_image(overscan_arr, cam_cfg, margin=margin)

    ideal_lines, dist_lines = [], []
    for obj in meta["objects"]:
        ki = _kpts_to_ideal(obj["keypoints_overscan"], margin, bw, bh)
        bi = _bbox_ideal(obj["bbox_overscan"], margin, bw, bh)
        ideal_lines.append(labels.to_yolo_pose(class_id, bi, ki, bw, bh))

        kd = _kpts_to_dist(ki, cam_cfg, bw, bh)
        bd = _bbox_dist(bi, cam_cfg, bw, bh)
        dist_lines.append(labels.to_yolo_pose(class_id, bd, kd, bw, bh))

    return {"ideal": (ideal_img, ideal_lines), "dist": (dist_img, dist_lines)}


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
        img = Image.open(os.path.join(frames_dir, meta["image"])).convert("RGBA")
        arr = np.array(img)
        res = process_frame(meta, arr, meta["camera"], class_id)

        split = "val" if fid in val_set else "train"
        stem = f"frame_{fid:06d}"
        train_img, train_lines = res[variant]
        Image.fromarray(train_img, "RGBA").save(
            os.path.join(out_dir, "images", split, stem + ".png"))
        with open(os.path.join(out_dir, "labels", split, stem + ".txt"), "w") as f:
            f.write("\n".join(train_lines) + ("\n" if train_lines else ""))

        other = "ideal" if variant == "dist" else "dist"
        Image.fromarray(res[other][0], "RGBA").save(
            os.path.join(debug_dir, f"{stem}_{other}.png"))

    write_data_yaml(out_dir, cfg)
    print(f"[labels] {len(metas)} 帧 -> {out_dir} (train={len(ids)-n_val}, val={n_val}, 训练图={variant})")


if __name__ == "__main__":
    main()
