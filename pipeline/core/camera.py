"""相机模块: 复用经过验证的 src/config/camera_config.py(双端 bpy/numpy)。

以路径方式加载, 系统 Python 与 Blender 内均可用, 避免重复实现内参/畸变/投影数学。
对外暴露 cc(模块本体)及最常用函数别名。
"""

import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
_CC_PATH = os.path.join(_REPO, "src", "config", "camera_config.py")

_spec = importlib.util.spec_from_file_location("yc_camera_config", _CC_PATH)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

# 常用别名
load = cc.load
resolution = cc.resolution
intrinsics = cc.intrinsics
dist_coeffs = cc.dist_coeffs
has_distortion = cc.has_distortion
mount_rpy_rad = cc.mount_rpy_rad
forward_vector = cc.forward_vector
overscanned = cc.overscanned
distort_points = cc.distort_points
distort_image = cc.distort_image
place_camera_from_config = cc.place_camera_from_config
