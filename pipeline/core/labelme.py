"""labelme 标注格式(可被 labelme 打开)。

每条烟的顶面四点(物体系 TL,TR,BR,BL 顺序)构成一个 polygon(顶面 mask), label = SKU 名。
imageData 可内嵌 base64(与既有标注习惯一致)。
"""

import base64

LABELME_VERSION = "5.5.0"


def image_to_b64(png_path):
    with open(png_path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def to_labelme(image_filename, width, height, objects, image_b64=None):
    """objects: [{"label", "kpts":[(x,y,v)*4], ...}]。返回 labelme dict。

    全部 4 点可见性为 0(完全出画)的对象会被跳过。
    """
    shapes = []
    for o in objects:
        kpts = o["kpts"]
        if all(v == 0 for (_x, _y, v) in kpts):
            continue
        pts = [[round(float(x), 2), round(float(y), 2)] for (x, y, _v) in kpts]
        shapes.append({
            "label": o["label"],
            "points": pts,
            "group_id": None,
            "description": "",
            "shape_type": "polygon",
            "flags": {},
        })
    return {
        "version": LABELME_VERSION,
        "flags": {},
        "shapes": shapes,
        "imagePath": image_filename,
        "imageData": image_b64,
        "imageHeight": int(height),
        "imageWidth": int(width),
    }
