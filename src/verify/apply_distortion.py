"""给理想针孔渲染图 + 其标注 JSON 加上真实镜头畸变 (系统 Python, 需 numpy+Pillow)。

用法:
    python3 src/verify/apply_distortion.py --config config/camera.json \
        --out output --name shelf_kp_00 [--suffix _dist]

读取 output/images/<name>.png 与 output/labels/<name>.json,
输出 output/images/<name><suffix>.png 与 output/labels/<name><suffix>.json
(关键点/bbox 已同步畸变, 可直接用 draw_labels.py 校验对齐)。

若标注里 overscan_margin>0, 输入图应是外扩大图, 加畸变后自动裁回目标分辨率、去掉边角黑边。
若配置里畸变系数全 0, 则等价于原图(裁剪后)拷贝。
"""

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import camera_config as cc  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/camera.json")
    ap.add_argument("--out", default="output")
    ap.add_argument("--name", required=True)
    ap.add_argument("--suffix", default="_dist")
    ap.add_argument("--overscan", type=int, default=None,
                    help="外扩边距(px); 通常自动从标注读取, 无标注时可手动指定")
    args = ap.parse_args()

    cfg = cc.load(os.path.abspath(args.config))
    out_root = os.path.abspath(args.out)
    img_in = os.path.join(out_root, "images", f"{args.name}.png")
    lbl_in = os.path.join(out_root, "labels", f"{args.name}.json")
    name_out = f"{args.name}{args.suffix}"
    img_rel = os.path.join("images", f"{name_out}.png")
    img_out = os.path.join(out_root, img_rel)
    lbl_out = os.path.join(out_root, "labels", f"{name_out}.json")

    data = None
    if os.path.exists(lbl_in):
        with open(lbl_in) as f:
            data = json.load(f)
    margin = args.overscan if args.overscan is not None else (
        int(data.get("overscan_margin", 0)) if data else 0)

    tw, th = cc.resolution(cfg)                       # 目标(标定)分辨率
    arr = np.asarray(Image.open(img_in).convert("RGBA"))
    ih, iw = arr.shape[:2]
    if (iw, ih) != (tw + 2 * margin, th + 2 * margin):
        raise SystemExit(
            f"[ERR] 分辨率不匹配: 图像 {iw}x{ih}, 期望 {tw + 2 * margin}x{th + 2 * margin} "
            f"(标定 {tw}x{th} + overscan {margin}/边)。\n"
            f"      畸变系数与内参绑定在标定分辨率上, 请对同参数渲染的图使用。")

    # overscan 时额外裁出干净的 640x480 无畸变原图 (_ideal), 补回被外扩"吃掉"的原图
    if margin > 0:
        crop = arr[margin:margin + th, margin:margin + tw]
        ideal_rel = os.path.join("images", f"{args.name}_ideal.png")
        Image.fromarray(crop, "RGBA").save(os.path.join(out_root, ideal_rel))
        if data is not None:
            idl = json.loads(json.dumps(data))
            for obj in (idl["objects"] if "objects" in idl else [idl]):
                for k in obj["top_face_keypoints"]:
                    k["x"], k["y"] = round(k["x"] - margin, 2), round(k["y"] - margin, 2)
                b = obj["bbox_2d"]
                b["x_min"] -= margin; b["x_max"] -= margin
                b["y_min"] -= margin; b["y_max"] -= margin
            idl["image"] = ideal_rel
            idl["width"], idl["height"] = tw, th
            idl["overscan_margin"] = 0
            with open(os.path.join(out_root, "labels", f"{args.name}_ideal.json"), "w") as f:
                json.dump(idl, f, indent=2, ensure_ascii=False)
        print(f"[INFO] ideal(裁剪原图) -> {os.path.join(out_root, ideal_rel)}  {tw}x{th}")

    dist = cc.distort_image(arr, cfg, margin=margin)  # 输出裁回目标尺寸
    Image.fromarray(dist, "RGBA").save(img_out)

    if data is not None:
        objs = data["objects"] if "objects" in data else [data]
        for obj in objs:
            kps = obj["top_face_keypoints"]
            # 关键点原本在(外扩)理想图坐标, 减 margin 回到目标理想坐标, 再前向畸变
            ideal = [[k["x"] - margin, k["y"] - margin] for k in kps]
            pts = cc.distort_points(ideal, cfg)
            for k, (u, v) in zip(kps, pts):
                k["x"], k["y"] = round(float(u), 2), round(float(v), 2)
            b = obj["bbox_2d"]
            corners = cc.distort_points(
                [[b["x_min"] - margin, b["y_min"] - margin],
                 [b["x_max"] - margin, b["y_min"] - margin],
                 [b["x_max"] - margin, b["y_max"] - margin],
                 [b["x_min"] - margin, b["y_max"] - margin]], cfg)
            obj["bbox_2d"] = {"x_min": round(float(corners[:, 0].min()), 2),
                              "y_min": round(float(corners[:, 1].min()), 2),
                              "x_max": round(float(corners[:, 0].max()), 2),
                              "y_max": round(float(corners[:, 1].max()), 2)}
        data["image"] = img_rel
        data["width"], data["height"] = tw, th
        data["overscan_margin"] = 0
        data["distorted"] = True
        with open(lbl_out, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[INFO] distorted labels -> {lbl_out}")

    print(f"[INFO] distorted image  -> {img_out}  {tw}x{th}  "
          f"(overscan={margin}, distortion={'on' if cc.has_distortion(cfg) else 'off/零'})")


if __name__ == "__main__":
    main()
