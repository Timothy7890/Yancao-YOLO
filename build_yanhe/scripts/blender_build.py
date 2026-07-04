"""编排脚本 (系统 Python): 由某个产品的 box_model.json 生成带贴图的 .blend。

目录规范: build_yanhe/<Product>/{raw, faces, box.json, box_model.json}

步骤:
  1) 读 build_yanhe/<Product>/box_model.json; 对每个面用 PIL 把校正图按
     texture_flip_horizontal 水平镜像、再按 texture_rotation_cw_deg 顺时针旋转,
     烘焙成"最终朝向纹理", 存到临时目录。
  2) 调 Blender: blender --background --python _blend_make.py -- ... 建长方体、贴图、
     打包纹理并保存 .blend。

用法:
  python build_yanhe/scripts/blender_build.py --product Huangjinye   # -> build_yanhe/Huangjinye/Huangjinye.blend
  python build_yanhe/scripts/blender_build.py --product Huangjinye --name 黄金叶 --out data/yanhe/黄金叶.blend
  # 只有一个产品时可省略 --product
  BLENDER=/path/to/Blender python build_yanhe/scripts/blender_build.py --product Huangjinye

依赖: pillow (系统 Python)。Blender 路径默认 /Applications/Blender.app/Contents/MacOS/Blender。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageOps

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.abspath(os.path.join(_HERE, ".."))          # build_yanhe
_REPO = os.path.abspath(os.path.join(_BUILD, ".."))          # 仓库根
_MAKE = os.path.join(_HERE, "_blend_make.py")
_DEFAULT_BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"

FACE_ORDER = ["front", "back", "left", "right", "top", "bottom"]
_RESERVED = {"scripts"}


def list_products():
    out = []
    if os.path.isdir(_BUILD):
        for d in sorted(os.listdir(_BUILD)):
            p = os.path.join(_BUILD, d)
            if os.path.isdir(p) and d not in _RESERVED and not d.startswith(".") \
                    and not d.startswith("__"):
                out.append(d)
    return out


def bake_texture(img_path, rot, flip, out_path):
    """按 先水平镜像、再顺时针旋转 rot 度 烘焙纹理。"""
    im = Image.open(img_path).convert("RGBA")
    if flip:
        im = ImageOps.mirror(im)
    if rot % 360:
        im = im.rotate(-(rot % 360), expand=True)  # PIL 正角=逆时针, 取负即顺时针
    im.save(out_path)
    return im.size


def main():
    ap = argparse.ArgumentParser(description="由某产品的 box_model.json 生成带贴图的 .blend")
    ap.add_argument("--product", default=None, help="产品(SKU)名, 即 build_yanhe/<Product>")
    ap.add_argument("--model", default=None, help="直接指定模型 JSON (覆盖 --product)")
    ap.add_argument("--name", default=None, help="Blender 里的对象名, 默认=产品名")
    ap.add_argument("--out", default=None, help="输出 .blend, 默认 build_yanhe/<Product>/<Product>.blend")
    ap.add_argument("--blender", default=os.environ.get("BLENDER", _DEFAULT_BLENDER))
    args = ap.parse_args()

    # 确定产品与各路径
    product = args.product
    if product is None and args.model is None:
        prods = list_products()
        if len(prods) == 1:
            product = prods[0]
            print(f"未指定 --product, 自动选用唯一产品: {product}")
        elif not prods:
            print("build_yanhe 下没有产品目录, 请先在网页里新建并保存。")
            sys.exit(1)
        else:
            print(f"存在多个产品, 请用 --product 指定其一: {prods}")
            sys.exit(1)

    if args.model:
        model_path = args.model
        product_dir = os.path.dirname(model_path)
        product = product or os.path.basename(product_dir)
    else:
        product_dir = os.path.join(_BUILD, product)
        model_path = os.path.join(product_dir, "box_model.json")

    name = args.name or product
    out = args.out or os.path.join(product_dir, f"{product}.blend")

    if not os.path.exists(model_path):
        print(f"找不到模型 JSON: {model_path} (请先在网页里保存该产品)")
        sys.exit(1)
    if not os.path.exists(args.blender):
        print(f"找不到 Blender: {args.blender} (用 --blender 或环境变量 BLENDER 指定)")
        sys.exit(1)

    with open(model_path, "r", encoding="utf-8") as f:
        model = json.load(f)
    faces = model["faces"]

    tmp = tempfile.mkdtemp(prefix="yanhe_tex_")
    n_baked = 0
    for face in FACE_ORDER:
        fd = faces.get(face)
        if not fd or not fd.get("image"):
            print(f"  - {face}: 无贴图, 跳过")
            continue
        img_path = os.path.join(product_dir, fd["image"])
        if not os.path.exists(img_path):
            print(f"  - {face}: 找不到 {img_path}, 跳过")
            continue
        size = bake_texture(img_path, int(fd.get("texture_rotation_cw_deg", 0)),
                            bool(fd.get("texture_flip_horizontal", False)),
                            os.path.join(tmp, f"{face}.png"))
        n_baked += 1
        print(f"  ✓ {face}: {fd['image']} -> 烘焙 {size[0]}x{size[1]}")

    print(f"[产品 {product}] 已烘焙 {n_baked} 张纹理, 调用 Blender 构建模型…")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    cmd = [args.blender, "--background", "--python", _MAKE, "--",
           "--model", model_path, "--textures", tmp, "--out", out,
           "--name", name]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print("Blender 构建失败, 返回码", r.returncode)
        sys.exit(r.returncode)
    print(f"\n完成 -> {out}")


if __name__ == "__main__":
    main()
