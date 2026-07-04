"""在 Blender 进程内引导 sys.path, 使 `import pipeline.core...` 可用。

runner 脚本(blender --python ...)开头先 `import pipeline.blender.env`(通过手动加路径),
或直接调用 bootstrap()。因为 Blender 用自带 Python, 不认项目安装, 需手动把仓库根加入路径。
"""

import os
import sys


def repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", ".."))


def bootstrap():
    root = repo_root()
    for p in (root, os.path.join(root, "src", "config"), os.path.join(root, "src", "blender")):
        if p not in sys.path:
            sys.path.insert(0, p)
    return root
