# 烟盒三维建模工具（网页版）

从手机拍的 6 张烟盒照片（含背景），在浏览器里重建成一个带贴图的长方体模型描述。
分两步：① 可视化点 4 角做去背景 + 透视校正；② 空长方体 6 面贴图、鼠标拖动旋转、
逐面换图/旋转/翻转，确认后导出朝向 JSON。

技术栈：**FastAPI**（后端，复用 `common.py` 做校正/几何/存 JSON）+ **Vue3 + Three.js**
（前端，CDN 免打包）。所有代码都在 `build_yanhe/scripts/` 下。

```
build_yanhe/scripts/
  common.py                     # 公共库: 坐标约定/6面几何/box.json读写/透视系数
  web/
    backend/
      app.py                    # FastAPI: 静态页 + raw/faces 读写 + 校正 + 存 JSON
      requirements.txt
    frontend/
      index.html                # Vue3 + Three.js (importmap CDN)
      app.js
      style.css
```

数据默认读写上一级 `build_yanhe/`：原图 `raw/`、面图 `faces/`、尺寸 `box.json`、
结果 `box_model.json`（可用环境变量 `BUILD`/`RAW`/`FACES` 覆盖）。

## 启动

```bash
pip install -r build_yanhe/scripts/web/backend/requirements.txt
python build_yanhe/scripts/web/backend/app.py            # 默认 127.0.0.1:8000
# 浏览器打开 http://127.0.0.1:8000/
```

前端走 CDN 加载 Vue/Three，需联网；后端负责本地文件读写。

## 用法

顶部先填三边长 `长X / 宽Y / 高Z` 和单位，点“保存尺寸”（写入 `box.json`）。

**① 校正去背景**
- 上方选一个面（front/back/left/right/top/bottom）。
- 左栏点一张原图载入中间画布。
- 在图上按顺序点 4 角：**左上 → 右上 → 右下 → 左下**（可撤销/清空）。
- 点“校正并保存”：后端按该面真实边长比例透视校正、裁掉背景，存成 `faces/<面>.png`，
  右栏显示预览。逐面重复。

**② 3D 放置**
- 空盒（蓝色线框）+ 6 面。鼠标左键拖动旋转、滚轮缩放。
- 右侧每个面：下拉选用哪张校正图、`旋转90°`（顺时针）、`翻转`（水平镜像），实时预览。
- 点“保存 box_model.json”导出。

## 坐标约定（沿用本项目）

- `X=长(length_x)`，`Y=宽(width_y)`，`Z=高(height_z)`，中心在原点。
- 前/后面在 **YOZ 平面**（法线沿 X）；左/右面在 XOZ 平面（法线沿 Y）；顶/底面在 XOY 平面（法线沿 Z）。
- 6 面：`front 前(+X)` `back 后(-X)`（宽Y×高Z） · `left 左(-Y)` `right 右(+Y)`（长X×高Z） ·
  `top 顶(+Z)` `bottom 底(-Z)`（长X×宽Y）。
- Web 3D 视图坐标轴配色：红 X / 绿 Y / 蓝 Z。
- 每个面 4 角固定按 `[TL,TR,BR,BL]`，对应贴图像素 `(0,0)(W,0)(W,H)(0,H)`；
  校正采点、3D 贴图、导出 JSON 三者一致，网页所见即导出结果（WYSIWYG）。

## 导出的 `box_model.json`

给下一个 AI / Blender 用：

- `convention`：轴向、原点、正面朝向、单位、角点顺序。
- `dimensions`：三边长。
- `faces.<面>`：`normal`（朝外法线）、`size_units`、`image`（贴图相对路径）、
  `texture_rotation_cw_deg` / `texture_flip_horizontal`、`corners_box_coords`
  （该面 TL/TR/BR/BL 的盒内 3D 坐标）、`uv`。
- `orientation_guide`：构建步骤文字。

下游构建：建对应尺寸长方体 → 每面加载 `image` → 先水平镜像（若 flip）再顺时针旋转
`texture_rotation_cw_deg` → 把贴图四角贴到 `corners_box_coords` 的 TL/TR/BR/BL。
