"""帧后处理(系统 Python, numpy): 由外扩渲染图 + 几何 JSON 得到

  - ideal: 中心裁剪的理想针孔图 + 关键点/框(基准分辨率坐标)
  - dist : 加畸变后的"真实相机"图 + 关键点/框

供 build_labels(YOLO) 与 export_labelme(labelme) 共用, 集中所有坐标换算。
"""

import numpy as np

from . import camera as cammod


def _clip_pt(x, y, w, h):
    return min(max(x, 0.0), w), min(max(y, 0.0), h)


def _kpts_ideal(kpts, margin, bw, bh):
    out = []
    for kx, ky, v in kpts:
        x, y = kx - margin, ky - margin
        vis = 0 if (v == 0 or not (0 <= x <= bw and 0 <= y <= bh)) else int(v)
        out.append((x, y, vis))
    return out


def _kpts_dist(kpts_ideal, cam_cfg, bw, bh):
    if not kpts_ideal:
        return []
    pts = np.array([[x, y] for (x, y, _v) in kpts_ideal], dtype=float)
    dp = cammod.distort_points(pts, cam_cfg)
    out = []
    for (x, y, v), (dx, dy) in zip(kpts_ideal, dp):
        vis = 0 if (v == 0 or not (0 <= dx <= bw and 0 <= dy <= bh)) else int(v)
        out.append((float(dx), float(dy), vis))
    return out


def _bbox_ideal(bbox_overscan, margin, bw, bh):
    x0, y0, x1, y1 = bbox_overscan
    x0, y0 = _clip_pt(x0 - margin, y0 - margin, bw, bh)
    x1, y1 = _clip_pt(x1 - margin, y1 - margin, bw, bh)
    return (x0, y0, x1, y1)


def _bbox_dist(bbox_ideal, cam_cfg, bw, bh):
    x0, y0, x1, y1 = bbox_ideal
    corners = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=float)
    d = cammod.distort_points(corners, cam_cfg)
    xs, ys = d[:, 0], d[:, 1]
    x0, y0 = _clip_pt(float(xs.min()), float(ys.min()), bw, bh)
    x1, y1 = _clip_pt(float(xs.max()), float(ys.max()), bw, bh)
    return (x0, y0, x1, y1)


def process_frame(meta, overscan_arr, cam_cfg):
    """返回 {"base_wh", "ideal":{image,objects}, "dist":{image,objects}}。

    objects 每项: {"label", "kpts":[(x,y,v)*4], "bbox":(x0,y0,x1,y1)}。
    """
    bw, bh = meta["base_width"], meta["base_height"]
    margin = meta["overscan_margin"]

    ideal_img = overscan_arr[margin:margin + bh, margin:margin + bw] if margin > 0 else overscan_arr
    dist_img = cammod.distort_image(overscan_arr, cam_cfg, margin=margin)

    ideal_objs, dist_objs = [], []
    for obj in meta["objects"]:
        label = obj["sku"]
        ki = _kpts_ideal(obj["keypoints_overscan"], margin, bw, bh)
        bi = _bbox_ideal(obj["bbox_overscan"], margin, bw, bh)
        ideal_objs.append({"label": label, "kpts": ki, "bbox": bi})
        dist_objs.append({"label": label,
                          "kpts": _kpts_dist(ki, cam_cfg, bw, bh),
                          "bbox": _bbox_dist(bi, cam_cfg, bw, bh)})

    return {"base_wh": (bw, bh),
            "ideal": {"image": ideal_img, "objects": ideal_objs},
            "dist": {"image": dist_img, "objects": dist_objs}}
