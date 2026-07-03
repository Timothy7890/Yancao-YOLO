"""在师兄机器上无头运行 (Isaac 自带 python.sh), 从 ycfj_scene.usd 导出利群条烟为 glb。

用法 (远端):
    cd ~/isaacsim && ./python.sh /tmp/isaac_export_liqun.py

产出:
    /tmp/liqun_iso.usd   隔离出的利群子树 (引用+扁平)
    /tmp/liqun.glb       自包含 glTF (网格+UV+贴图+PBR), 供 Blender 导入
    /tmp/liqun.obj       兜底: 纯几何+UV (若 glb 失败时用, 贴图另配 tiaoyan.png)
"""

import asyncio
import os

from isaacsim import SimulationApp

simulation_app = SimulationApp({"headless": True})

import omni.kit.app  # noqa: E402
from pxr import Usd, UsdGeom, UsdShade, Gf  # noqa: E402
from pxr import Sdf  # noqa: E402,F401

SRC = "/home/robot/isaacproject/ycfj_scene.usd"
ISO = "/tmp/liqun_iso.usd"
GLB = "/tmp/liqun.glb"
OBJ = "/tmp/liqun.obj"


def find_target(stage):
    cands = [p for p in stage.Traverse() if "liqun" in p.GetName().lower()]
    print(f"[EXPORT] liqun 候选 prim ({len(cands)}):")
    for p in cands:
        n_mesh = sum(1 for c in Usd.PrimRange(p) if c.GetTypeName() == "Mesh")
        print(f"    {p.GetPath()}  type={p.GetTypeName()}  meshes={n_mesh}")
    for p in cands:
        if any(c.GetTypeName() == "Mesh" for c in Usd.PrimRange(p)):
            return p
    return cands[0] if cands else None


def dump_textures(prim):
    print("[EXPORT] 材质/贴图绑定:")
    for p in Usd.PrimRange(prim):
        if p.GetTypeName() != "Mesh":
            continue
        mat, _ = UsdShade.MaterialBindingAPI(p).ComputeBoundMaterial()
        if not mat:
            continue
        for shd in Usd.PrimRange(mat.GetPrim()):
            shader = UsdShade.Shader(shd)
            if not shader:
                continue
            for inp in shader.GetInputs():
                name = inp.GetBaseName().lower()
                if "file" in name or "tex" in name or "diffuse" in name or "albedo" in name:
                    print(f"    {p.GetName()} <- {shd.GetName()}.{inp.GetBaseName()} = {inp.Get()}")


def write_obj(stage, target):
    xf = UsdGeom.XformCache()
    tw = xf.GetLocalToWorldTransform(target)
    tw_inv = tw.GetInverse()
    with open(OBJ, "w") as f:
        f.write("# liqun exported from ycfj_scene.usd (target-local space)\n")
        base = 0
        for p in Usd.PrimRange(target):
            if p.GetTypeName() != "Mesh":
                continue
            m = UsdGeom.Mesh(p)
            mw = xf.GetLocalToWorldTransform(p) * tw_inv
            pts = m.GetPointsAttr().Get() or []
            counts = m.GetFaceVertexCountsAttr().Get() or []
            idx = m.GetFaceVertexIndicesAttr().Get() or []
            st_attr = m.GetPrim().GetAttribute("primvars:st")
            st = st_attr.Get() if st_attr and st_attr.HasValue() else None
            for v in pts:
                w = mw.Transform(Gf.Vec3d(v[0], v[1], v[2]))
                f.write(f"v {w[0]:.6f} {w[1]:.6f} {w[2]:.6f}\n")
            if st:
                for uv in st:
                    f.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\n")
            o = 0
            uv_i = 0
            for c in counts:
                face = [idx[o + k] + 1 + base for k in range(c)]
                if st and len(st) == len(pts):
                    f.write("f " + " ".join(f"{vi}/{vi}" for vi in face) + "\n")
                elif st:
                    uvs = [uv_i + k + 1 for k in range(c)]
                    f.write("f " + " ".join(f"{vi}/{ui}" for vi, ui in zip(face, uvs)) + "\n")
                    uv_i += c
                else:
                    f.write("f " + " ".join(str(vi) for vi in face) + "\n")
                o += c
            base += len(pts)
    print(f"[EXPORT] OBJ 写出 -> {OBJ}  size={os.path.getsize(OBJ)}")


def build_iso(stage, target):
    iso = Usd.Stage.CreateNew(ISO)
    root = UsdGeom.Xform.Define(iso, "/Root")
    iso.SetDefaultPrim(root.GetPrim())
    ref = iso.DefinePrim("/Root/liqun", "Xform")
    ref.GetReferences().AddReference(SRC, target.GetPath())
    iso.GetRootLayer().Save()
    print(f"[EXPORT] 隔离 USD -> {ISO}")


async def convert_to_glb():
    mgr = omni.kit.app.get_app().get_extension_manager()
    mgr.set_extension_enabled_immediate("omni.kit.asset_converter", True)
    import omni.kit.asset_converter as ac
    task = ac.get_instance().create_converter_task(ISO, GLB, None)
    ok = await task.wait_until_finished()
    if ok is False or (hasattr(task, "get_status") and task.get_status() != ac.AssetConverterStatus.SUCCESS):
        print(f"[EXPORT] glb 转换失败: {getattr(task, 'get_error_message', lambda: '')()}")
        return False
    print(f"[EXPORT] GLB 写出 -> {GLB}  size={os.path.getsize(GLB)}")
    return True


def main():
    stage = Usd.Stage.Open(SRC)
    target = find_target(stage)
    if target is None:
        print("[EXPORT] 未找到 liqun prim")
        return
    print(f"[EXPORT] 选中: {target.GetPath()}")
    try:
        dump_textures(target)
    except Exception as e:  # noqa
        print(f"[EXPORT] 贴图 dump 跳过: {e}")
    try:
        write_obj(stage, target)
    except Exception as e:  # noqa
        print(f"[EXPORT] OBJ 写出失败: {e}")
    build_iso(stage, target)

    loop = asyncio.get_event_loop()
    fut = asyncio.ensure_future(convert_to_glb())
    while not fut.done():
        simulation_app.update()
    print("[EXPORT] 完成")


if __name__ == "__main__":
    main()
    simulation_app.close()
