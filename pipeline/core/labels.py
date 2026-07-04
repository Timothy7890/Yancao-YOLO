"""标注格式化(纯函数): 由像素坐标构造 bbox 与 YOLO-pose 文本行。

YOLO-pose 一行: <cls> <cx> <cy> <w> <h> <kx1> <ky1> <v1> ... <kxK> <kyK> <vK>
所有坐标按图宽高归一化到 [0,1]; 可见性 v: 0=无标注,1=被遮挡,2=可见。
"""


def bbox_from_points(pts):
    """由若干 (x,y) 像素点得到 (xmin, ymin, xmax, ymax)。"""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def to_yolo_pose(class_id, bbox_px, kpts_px_vis, img_w, img_h):
    """bbox_px=(xmin,ymin,xmax,ymax); kpts_px_vis=[(x,y,v)...]; 返回归一化字符串行。"""
    xmin, ymin, xmax, ymax = bbox_px
    cx = clamp01((xmin + xmax) / 2.0 / img_w)
    cy = clamp01((ymin + ymax) / 2.0 / img_h)
    w = clamp01((xmax - xmin) / img_w)
    h = clamp01((ymax - ymin) / img_h)
    parts = [str(class_id), f"{cx:.6f}", f"{cy:.6f}", f"{w:.6f}", f"{h:.6f}"]
    for (kx, ky, v) in kpts_px_vis:
        parts += [f"{clamp01(kx / img_w):.6f}", f"{clamp01(ky / img_h):.6f}", str(int(v))]
    return " ".join(parts)
