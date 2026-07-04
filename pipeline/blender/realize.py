"""按 SceneSpec 在 bpy 场景里实现: 摆放烟盒、布光、摆相机。"""

import math

import bpy

from pipeline.blender import assets, scene as sc


def realize(cfg, spec, registry, camera_config_path):
    """返回 (placed, cam, base_wh, render_wh)。placed = [(obj, placement), ...]。"""
    prefix = cfg["shelf"]["board_name_prefix"]
    assets.clear_instances()
    rect = sc.board_rect(spec.layer, prefix)

    placed = []
    for p in spec.placements:
        obj = assets.instance_sku(registry, p.sku)
        obj.rotation_mode = "XYZ"
        obj.rotation_euler = (0.0, 0.0, math.radians(p.yaw_deg))
        # 烟盒底面在自身 z=0, 底心=原点 -> location.z=板面顶 即贴板
        obj.location = (rect["cx"] + p.x, rect["cy"] + p.y, rect["top_z"])
        placed.append((obj, p))
    bpy.context.view_layer.update()

    sc.apply_factory_lights(spec.lights.top_power, spec.lights.ambient, prefix=prefix)

    cam_cfg = cfg["camera"]
    cam, base_wh, render_wh = sc.setup_camera(
        camera_config_path, spec.layer, spec.camera.distance,
        cam_cfg["target_z_offset"], spec.camera.yaw_off_deg, spec.camera.pitch_off_deg,
        tuple(spec.camera.pos_off), prefix, cam_cfg["overscan"],
        global_yaw_deg=cfg.get("scene_z_rotation_deg", 0.0))
    bpy.context.view_layer.update()
    return placed, cam, base_wh, render_wh
