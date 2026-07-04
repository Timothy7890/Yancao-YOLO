"""编排脚本 (系统 Python): 由 box_model.json 生成带贴图的 .blend。

步骤:
  1) 读 box_model.json; 对每个面用 PIL 把校正图按 texture_flip_horizontal 水平镜像、
     再按 texture_rotation_cw_deg 顺时针旋转, 烘焙成"最终朝向纹理", 存到临时目录。
  2) 调 Blender: blender --background --python _blend_make.py -- ... 建长方体、贴图、
     打包纹理并保存 .blend。

用法:
  python build_yanhe/scripts/blender_build.py                       # 默认输出 data/黄金叶.blend
  python build_yanhe/scripts/blender_build.py --name 黄金叶 --out data/黄金叶.blend
  BLENDER=/path/to/Blender python build_yanhe/scripts/blender_build.py

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
    ap = argparse.ArgumentParser(description="由 box_model.json 生成带贴图的 .blend")
    ap.add_argument("--model", default=os.path.join(_BUILD, "box_model.json"))
    ap.add_argument("--build", default=_BUILD, help="面图相对路径的根目录")
    ap.add_argument("--name", default="黄金叶")
    ap.add_argument("--out", default=os.path.join(_REPO, "data", "yanhe", "黄金叶.blend"))
    ap.add_argument("--blender", default=os.environ.get("BLENDER", _DEFAULT_BLENDER))
    args = ap.parse_args()

    if not os.path.exists(args.model):
        print(f"找不到模型 JSON: {args.model} (请先在网页里保存)")
        sys.exit(1)
    if not os.path.exists(args.blender):
        print(f"找不到 Blender: {args.blender} (用 --blender 或环境变量 BLENDER 指定)")
        sys.exit(1)

    with open(args.model, "r", encoding="utf-8") as f:
        model = json.load(f)
    faces = model["faces"]

    tmp = tempfile.mkdtemp(prefix="yanhe_tex_")
    n_baked = 0
    for face in FACE_ORDER:
        fd = faces.get(face)
        if not fd or not fd.get("image"):
            print(f"  - {face}: 无贴图, 跳过")
            continue
        img_path = os.path.join(args.build, fd["image"])
        if not os.path.exists(img_path):
            print(f"  - {face}: 找不到 {img_path}, 跳过")
            continue
        size = bake_texture(img_path, int(fd.get("texture_rotation_cw_deg", 0)),
                            bool(fd.get("texture_flip_horizontal", False)),
                            os.path.join(tmp, f"{face}.png"))
        n_baked += 1
        print(f"  ✓ {face}: {fd['image']} -> 烘焙 {size[0]}x{size[1]}")

    print(f"已烘焙 {n_baked} 张纹理, 调用 Blender 构建模型…")
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    cmd = [args.blender, "--background", "--python", _MAKE, "--",
           "--model", args.model, "--textures", tmp, "--out", args.out,
           "--name", args.name]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print("Blender 构建失败, 返回码", r.returncode)
        sys.exit(r.returncode)
    print(f"\n完成 -> {args.out}")


if __name__ == "__main__":
    main()
