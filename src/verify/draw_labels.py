"""Phase 1 Gate: 把导出的 JSON 顶面 4 角点画回渲染图, 肉眼校验像素级对齐。

用系统 Python 运行 (需 pillow):
    python3 src/verify/draw_labels.py --out output --name demo_000

生成 output/debug/<name>_overlay.png:
  - 绿点+编号 = 可见角点; 红点 = 被遮挡/出画角点
  - 青色多边形 = 顶面四边形
  - 黄色矩形 = 整体 2D 包围盒
"""

import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont


def load_font(size):
    for path in [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/SFNS.ttf",
    ]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output")
    ap.add_argument("--name", default="demo_000")
    args = ap.parse_args()

    out_root = os.path.abspath(args.out)
    lbl_path = os.path.join(out_root, "labels", f"{args.name}.json")
    with open(lbl_path) as f:
        data = json.load(f)

    img_path = os.path.join(out_root, data["image"])
    img = Image.open(img_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    font = load_font(max(13, img.size[0] // 60))

    # 兼容单目标(Phase1) 与多目标(Phase2) 两种 schema
    if "objects" in data:
        objs = data["objects"]
    else:
        objs = [{"top_face_keypoints": data["top_face_keypoints"], "bbox_2d": data["bbox_2d"]}]

    r = max(4, img.size[0] // 220)
    n_occ = 0
    for obj in objs:
        kps = obj["top_face_keypoints"]
        pts = [(kp["x"], kp["y"]) for kp in kps]
        d.line(pts + [pts[0]], fill=(0, 200, 200, 220), width=2)
        b = obj["bbox_2d"]
        d.rectangle([b["x_min"], b["y_min"], b["x_max"], b["y_max"]],
                    outline=(255, 220, 0, 160), width=1)
        for kp in kps:
            x, y = kp["x"], kp["y"]
            color = (0, 255, 0, 255) if kp["visible"] else (255, 40, 40, 255)
            n_occ += 0 if kp["visible"] else 1
            d.ellipse([x - r, y - r, x + r, y + r], fill=color, outline=(0, 0, 0, 255), width=1)

    out = Image.alpha_composite(img, overlay).convert("RGB")
    dbg_path = os.path.join(out_root, "debug", f"{args.name}_overlay.png")
    os.makedirs(os.path.dirname(dbg_path), exist_ok=True)
    out.save(dbg_path)
    print(f"[INFO] overlay -> {dbg_path}  objects={len(objs)}  非可见关键点(红)={n_occ}")


if __name__ == "__main__":
    main()
