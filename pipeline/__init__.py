"""Yancao-YOLO 合成数据集生成管线。

分层:
  core/     纯 Python(可脱离 Blender 单测): 配置、相机、场景规格(SceneSpec)、
            摆放布局、随机化采样、标注格式化。
  blender/  必须在 bpy 内运行: 资产装载、场景搭建、按规格实现、几何标注。
  runners/  入口脚本: make_base_scene(烘基础场景)、render_dataset(无头批量渲染)、
            build_labels(系统 Python 后处理: 裁理想图/加畸变/导 YOLO/划分数据集)。
"""
