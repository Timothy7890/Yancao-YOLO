import bpy
from mathutils import Vector

obj = next(o for o in bpy.data.objects if o.type == "MESH")
me = obj.data
print(f"=== OBJECT {obj.name!r} ===")
print("matrix_world:")
for row in obj.matrix_world:
    print("   ", [round(v, 5) for v in row])
print("scale:", [round(v, 5) for v in obj.scale], "rot_euler(deg):",
      [round(a * 57.2958, 2) for a in obj.rotation_euler])

print(f"\n=== {len(me.vertices)} LOCAL VERTICES ===")
for v in me.vertices:
    print(f"  v{v.index}: {tuple(round(c,5) for c in v.co)}")

print(f"\n=== {len(me.polygons)} POLYGONS (local normal / center / area) ===")
for p in me.polygons:
    print(f"  f{p.index}: verts={list(p.vertices)} "
          f"n={tuple(round(c,3) for c in p.normal)} "
          f"c={tuple(round(c,4) for c in p.center)} area={p.area:.6f}")

print("\n=== LOCAL AABB (bound_box) 8 corners ===")
for i, c in enumerate(obj.bound_box):
    print(f"  bb{i}: {tuple(round(x,5) for x in c)}")

print("\ndimensions:", tuple(round(d, 5) for d in obj.dimensions))
