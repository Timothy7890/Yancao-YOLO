"""主配置读取与路径解析。所有相对路径都相对仓库根解析为绝对路径。"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
DEFAULT_CONFIG = os.path.join(REPO_ROOT, "pipeline", "config", "dataset.json")


def abspath(rel):
    """把相对仓库根的路径转成绝对路径; 已是绝对路径则原样返回。"""
    if os.path.isabs(rel):
        return rel
    return os.path.abspath(os.path.join(REPO_ROOT, rel))


def load(path=None):
    path = path or DEFAULT_CONFIG
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["_config_path"] = os.path.abspath(path)
    return cfg


def resolved_paths(cfg):
    """把 paths.* 全部解析为绝对路径返回一个新 dict。"""
    return {k: abspath(v) for k, v in cfg["paths"].items()}
