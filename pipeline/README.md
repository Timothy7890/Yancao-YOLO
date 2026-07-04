# pipeline —— 烟盒货架合成数据集生成管线

为 YOLO-pose(顶面四角关键点)批量生成带标注的合成图像。核心设计:**把"一帧的规格"
(SceneSpec)做成纯 Python、可种子复现、可脱离 Blender 单测;Blender 只负责按规格实现场景
+ 渲染 + 取几何;图像畸变与数据集组装放系统 Python 后处理。**

## 目录结构

```
pipeline/
  config/dataset.json      # 主配置(路径/板长宽/相机/随机化范围/渲染/数据集/标注)
  core/                    # 纯 Python, 不 import bpy
    config.py              # 配置读取 + 路径解析(相对仓库根)
    camera.py              # 复用 src/config/camera_config.py(内参/畸变/投影, 双端)
    spec.py                # SceneSpec 数据类 + (反)序列化
    layout.py              # 板面格位求解(旋转包围盒建网格, 保证不重叠/不越界)
    randomize.py           # 由配置范围确定性采样一帧 SceneSpec(seed+frame_id)
    labels.py              # bbox / YOLO-pose 文本行格式化
  blender/                 # 仅在 bpy 内 import
    env.py                 # 进程内 sys.path 引导
    assets.py              # SKU 登记表(扫描 data/yanhe/*.blend) + 货架加载/生成 + 实例化
    scene.py               # 板长宽适配立柱、板面查询、默认相机、工厂LED布光、build_base
    realize.py             # 按 SceneSpec 摆盒/布光/摆相机
    annotate.py            # 顶面四角(物体系稳定序) + 投影 + 遮挡射线 + 检测框
  runners/                 # 入口
    make_base_scene.py     # (Blender)烘基础场景: 固定板长宽 + 默认相机 -> base_scene.blend
    render_dataset.py      # (Blender)无头批量渲染 -> frames/frame_%06d.{png,json}
    build_labels.py        # (系统 Python)裁理想图/加畸变/导 YOLO/train-val 划分
```

## 渲染自由度(靠随机化)

品种及组合、偏航、平移、所在层高度、光照。场景变化暂缺(待场景资源)。见
`config/dataset.json` 的 `placement` / `camera.jitter` / `lights`。

## 两处需要"手工确定"的量

1. **货架板最终长宽** → `shelf.board_length_x` / `shelf.board_width_y`(米)。
2. **相机默认位姿** → `camera.work_layer`(对准第几层)、`camera.distance`(退多远)、
   `camera.target_z_offset`。安装角(俯仰/横滚/偏航)取自 `config/camera.json`。

改完这两处后重跑 `make_base_scene` 即可把它们烘进 `base_scene.blend`。
想可视化地调,可用 `src/blender/interactive_tool.py` 在 GUI 里摆好再读数填回配置。

## 三步跑法

```bash
BL=/Applications/Blender.app/Contents/MacOS/Blender

# 1) 烘基础场景(货架若不存在会按 shelf.generate 生成到 data/jiazi/shelf.blend)
$BL --background --python pipeline/runners/make_base_scene.py -- --preview output/dataset/base_preview.png

# 2) 无头批量渲染(默认取 dataset.num_frames; 可 --num/--start 断点续跑)
$BL --background --python pipeline/runners/render_dataset.py -- --num 50

# 3) 后处理: 加畸变 + 导 YOLO-pose + 划分 train/val
python3 pipeline/runners/build_labels.py
```

产物在 `output/dataset/`: `images/{train,val}` `labels/{train,val}` `data.yaml`,
`frames/`(渲染中间产物, 含几何 JSON), `debug/`(理想针孔图, 便于核对)。

## 换成你自己的货架

把拆分好的货架 `.blend` 放到 `data/jiazi/` 并让 `paths.shelf_blend` 指向它;
隔板对象名前缀用 `shelf.board_name_prefix`(默认 `Shelf_Board_`)。删除已生成的
`shelf.blend` / `base_scene.blend` 后重跑第 1 步。

## 新增 SKU(烟盒品种)

把新烟盒 `.blend` 放进 `data/yanhe/`(对象为底面 z=0、顶面朝上,和黄金叶一致),
文件名即 SKU 名。`render_dataset` 会自动扫描纳入; 想限定用哪些, 填 `placement.sku_choices`。

## 交互式 Web 工具(FastAPI + Vue3)

在浏览器里选品/条数/变化范围/张数/保存位置, 一键出图并写 labelme。后端不跑 bpy,
而是编排: `build_skus`(确保 SKU 已构建) → `render_dataset`(Blender 无头) →
`export_labelme`(加畸变 + 写 `<保存位置>/raw_img_json/*.png,*.json`, JSON 内嵌 base64)。

```bash
# 用你的 conda fastapi 环境启动(默认 127.0.0.1:8000, 可用 PORT 改端口)
PORT=8010 /opt/anaconda3/envs/fastapi/bin/python pipeline/web/backend/app.py
# 浏览器打开 http://127.0.0.1:8010/
```

- 前端控件: SKU 多选+各自条数、偏航范围、平移抖动、放置层、顶灯功率/环境光范围、张数、
  保存位置、训练图类型(畸变/理想), 渲染后右侧缩略图预览。
- 产物: `<保存位置>/raw_img_json/<时间戳>_XXXXXX.{png,json}`(labelme 可直接打开);
  中间渲染件在 `<保存位置>/_work/frames/`。
- Blender 路径默认 `/Applications/Blender.app/...`, 可用环境变量 `BLENDER` 覆盖。

## SKU 来源与构建

SKU = `build_yanhe/<名>/`(含 `box_model.json` + `faces/`), 标注名 = 文件夹名。
渲染前需先把每个 SKU 构建成 `<名>/<名>.blend`(对象名=文件夹名):

```bash
python3 pipeline/runners/build_skus.py           # 缺失/过期才重建; --force 强制
```

Web 后端会在每次渲染前自动跑一次 build_skus。

## labelme 标注格式

每条烟的**顶面四点**(物体系 TL,TR,BR,BL)构成一个 `polygon`, `label` = SKU 名;
`imageData` 内嵌整图 base64。见 `core/labelme.py`。

## 关键点约定

顶面四角按**物体自身坐标系**固定为 `TL, TR, BR, BL`(与偏航无关, 保证 pose 语义稳定);
`data.yaml` 的 `flip_idx=[1,0,3,2]` 对应水平翻转增强。可见性 `v`: 0=出画/无标注,
1=被遮挡(射线检测), 2=可见。
```
