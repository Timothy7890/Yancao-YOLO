# Yancao-YOLO · 合成数据管线

用 Blender 渲染烟盒并**自动导出顶面 4 角点标注**, 为 YOLO 检测/关键点任务批量生成
带精确标注的训练图, 替代"人工摆放拍照 + 人工标注 mask"。

## 路线图与验证关卡 (Gate)

| 阶段 | 内容 | Gate |
| --- | --- | --- |
| **Phase 0** | Blender + 环境就绪 | 能出图 ✅ |
| **Phase 1** | 纯背景单盒渲染 + 自动导出 JSON 标注 | 标注与渲染**像素级对齐** ✅ |
| **Phase 2** | 多目标摆放 + 随机扰动 + 多目标遮挡 + YOLO 导出 | 多目标标注+遮挡判断正确 ✅ |
| Phase 2.5 | 域随机化(光照/视角/缺货/混牌) + 批量无人值守 | 批量出图+标注 |
| Phase 3 | 合成图训练 YOLO, 合成 holdout 测 | 训练闭环跑通 |
| Phase 4 | **真实图测 mAP (Sim2Real gap)** | 用 1-2 个自扫真实 SKU 验差距 |

> 当前进度: **Phase 1 / Phase 2 已通过**。用下载的 "BLUES" 替身盒子验证机制;
> 检测目标为**条烟(carton)**, 同事 Isaac 场景中已有利群/将军/泰山真实 SKU 可后续复用。

## 目录结构

```
data/                     # .blend 素材 (烟盒模型)
src/
  blender/
    kp_lib.py                  # 公共库: 顶面取点/投影/遮挡/相机灯光 (各脚本共用)
    render_annotate.py         # Phase1 单盒: 渲染 + 顶面4角投影 + 导出JSON
    render_scene.py            # Phase2 多目标: 网格摆放+扰动+多目标遮挡+YOLO导出
  verify/draw_labels.py        # 校验脚本 (系统Python+PIL): 把标注画回图, 支持单/多目标
scripts/
  run_demo.sh                  # 一键 demo: 渲染 -> 标注 -> 校验图
  inspect_blend.py             # 检查 .blend 里的对象/尺寸/材质
output/
  images/  labels/  debug/     # 渲染图 / JSON标注 / 校验叠加图
```

## 快速开始

```bash
# 一键跑 (name / azimuth / elevation)
bash scripts/run_demo.sh demo_000 35 30

# 结果:
#   output/images/demo_000.png         渲染图
#   output/labels/demo_000.json        标注 (顶面4角像素坐标 + 可见性 + 2D bbox + 相机参数)
#   output/debug/demo_000_overlay.png  校验图 (点画回渲染图)
```

环境变量可覆盖: `BLENDER`(可执行路径) `BLEND`(素材路径) `RES`(如 1280x720) `ENGINE`(EEVEE/CYCLES)。

Phase 2 多目标场景:

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background data/蓝色香烟盒子.blend \
  --python src/blender/render_scene.py -- --out output --name scene_000 \
  --rows 3 --cols 4 --seed 1 --azimuth 20 --elevation 18 --res 1280x960
python3 src/verify/draw_labels.py --out output --name scene_000
# 额外产出 output/labels/scene_000.txt (YOLO-pose: cls cx cy w h + 4*(kx ky v), 归一化)
```

## 标注约定

顶面 4 角点在**烟盒局部坐标系**中定义 (长轴+端的 4 个 bbox 角, 固定绕序),
因此关键点身份 `#0..#3` 与视角、旋转无关 —— 满足 YOLO-pose 对关键点稳定性的要求。

每个角点带 `in_frame` / `occluded` / `visible` 三个可见性标志。
