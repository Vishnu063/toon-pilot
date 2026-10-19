"""Optional real-Blender check: creates an original tiny rig fixture, imports, animates, renders.
Run: blender --background --factory-startup --python-exit-code 1 --python tests/blender_rig_smoke.py
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bpy
import blender_scene

folder=Path('output/rig-smoke').resolve();folder.mkdir(parents=True,exist_ok=True)
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
bpy.ops.object.armature_add(location=(0,0,0))
arm=bpy.context.object;arm.name='FixtureRig'
bone=arm.data.bones[0].name
bpy.ops.mesh.primitive_cube_add(location=(0,0,1))
mesh=bpy.context.object;mesh.scale=(.3,.2,1)
bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
mesh.parent=arm
modifier=mesh.modifiers.new('Rig','ARMATURE');modifier.object=arm
group=mesh.vertex_groups.new(name=bone);group.add(list(range(len(mesh.data.vertices))),1,'REPLACE')
for frame,angle in [(20,-.35),(30,.35)]:
    arm.pose.bones[bone].rotation_mode='XYZ'
    arm.pose.bones[bone].rotation_euler.y=angle
    arm.pose.bones[bone].keyframe_insert('rotation_euler',frame=frame)
arm.animation_data.action.name='Wave'
bpy.context.scene.frame_start=20;bpy.context.scene.frame_end=30
bpy.ops.export_scene.gltf(filepath=str(folder/'fixture.glb'),export_format='GLB',export_animations=True)
config=dict(action='dance',camera='static',frames=2,fps=12,width=128,height=228,samples=4,threads=2,
    characters=[dict(name='Fixture',model=str(folder/'fixture.glb'),clip='Wave_FixtureRig',height=2,position=[0,0,0])])
scene,camera,duck,bunny,wings,paws,imported=blender_scene.build_scene(config)
arm,action=imported[0]
scene.frame_set(1);bpy.context.view_layer.update();first=arm.pose.bones[0].matrix.copy()
scene.frame_set(11);bpy.context.view_layer.update();last=arm.pose.bones[0].matrix.copy()
assert first!=last, 'Imported rig is frozen'
blender_scene.camera_pose(camera,'static',0)
scene.render.filepath=str(folder/'imported.png');bpy.ops.render.render(write_still=True)
# A missing clip must fail rather than silently rendering a static pose.
config['characters'][0]['clip']='DOES_NOT_EXIST'
try:
    blender_scene.build_scene(config)
except ValueError as exc:
    assert 'Missing clip' in str(exc)
else:
    raise AssertionError('Missing clip was accepted')
print('REAL BLENDER RIG CHECK PASSED: imported motion, rendered frame, missing clip rejected')
