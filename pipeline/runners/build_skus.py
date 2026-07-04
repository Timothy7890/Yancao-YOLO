"""入口(系统 Python): 预构建 SKU 烟盒 .blend。

扫描 build_yanhe/<名>/(含 box_model.json), 对缺失或过期的 <名>/<名>.blend, 调用
build_yanhe/scripts/blender_build.py 烘焙贴图并生成(对象名 = 文件夹名)。

用法:
    python3 pipeline/runners/build_skus.py [--config ...] [--force] [--only Huangjinye ...]
"""

import argparse
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from pipeline.core import config                       # noqa: E402

_BLENDER_BUILD = os.path.join(_REPO, "build_yanhe", "scripts", "blender_build.py")
_DEFAULT_BLENDER = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
_RESERVED = {"scripts"}


def _stale(blend, model, faces_dir):
    if not os.path.exists(blend):
        return True
    bt = os.path.getmtime(blend)
    if os.path.getmtime(model) > bt:
        return True
    if os.path.isdir(faces_dir):
        for f in os.listdir(faces_dir):
            if os.path.getmtime(os.path.join(faces_dir, f)) > bt:
                return True
    return False


def scan(sku_root):
    out = {}
    for d in sorted(os.listdir(sku_root)):
        if d in _RESERVED or d.startswith(".") or d.startswith("__"):
            continue
        ddir = os.path.join(sku_root, d)
        model = os.path.join(ddir, "box_model.json")
        if os.path.isdir(ddir) and os.path.exists(model):
            out[d] = {"dir": ddir, "model": model, "faces": os.path.join(ddir, "faces"),
                      "blend": os.path.join(ddir, f"{d}.blend")}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=config.DEFAULT_CONFIG)
    ap.add_argument("--force", action="store_true", help="无视时间戳强制重建")
    ap.add_argument("--only", nargs="*", default=None, help="只构建这些 SKU")
    ap.add_argument("--blender", default=_DEFAULT_BLENDER)
    args = ap.parse_args()

    cfg = config.load(args.config)
    sku_root = config.abspath(cfg["paths"]["sku_root"])
    skus = scan(sku_root)
    if args.only:
        skus = {k: v for k, v in skus.items() if k in set(args.only)}
    if not skus:
        raise SystemExit(f"没有可构建的 SKU: {sku_root}")

    built, skipped = [], []
    for name, info in skus.items():
        if not args.force and not _stale(info["blend"], info["model"], info["faces"]):
            skipped.append(name)
            continue
        cmd = [sys.executable, _BLENDER_BUILD, "--product", name,
               "--name", name, "--out", info["blend"], "--blender", args.blender]
        print(f"[build_skus] 构建 {name} …")
        r = subprocess.run(cmd)
        if r.returncode != 0:
            raise SystemExit(f"[build_skus] {name} 构建失败(码 {r.returncode})")
        built.append(name)

    print(f"[build_skus] 构建 {built} ; 跳过(已最新) {skipped}")


if __name__ == "__main__":
    main()
