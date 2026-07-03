import bpy

print("=== SCENE OBJECTS ===")
for obj in bpy.data.objects:
    print(f"- name={obj.name!r} type={obj.type} dims={tuple(round(d,4) for d in obj.dimensions)} loc={tuple(round(v,3) for v in obj.location)}")

print("=== MESHES (world bbox) ===")
for obj in bpy.data.objects:
    if obj.type != "MESH":
        continue
    mw = obj.matrix_world
    zs = [(mw @ obj.data.vertices[0].co).z] if obj.data.vertices else []
    corners = [mw @ __import__("mathutils").Vector(c) for c in obj.bound_box]
    zsc = [round(c.z, 4) for c in corners]
    print(f"- {obj.name!r}: verts={len(obj.data.vertices)} polys={len(obj.data.polygons)} bbox_z={sorted(set(zsc))}")

print("=== CAMERAS / LIGHTS ===")
for obj in bpy.data.objects:
    if obj.type in ("CAMERA", "LIGHT"):
        print(f"- {obj.type}: {obj.name!r}")

print("=== MATERIALS ===")
for m in bpy.data.materials:
    print(f"- {m.name!r} use_nodes={m.use_nodes}")
