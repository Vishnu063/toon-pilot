"""Run with Blender 4.2+: procedural starter assets and reusable motion presets."""
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector
sys.path.insert(0, str(Path(__file__).resolve().parent))
from third_party.anim_studio.rig import find_armature, bind_action, shift_action_to_frame1, curves

COLORS = {'yellow': (1, .69, .08, 1), 'orange': (1, .31, .025, 1),
          'cream': (.95, .85, .68, 1), 'mint': (.25, .70, .48, 1),
          'blue': (.12, .56, .90, 1), 'eye': (.09, .04, .02, 1),
          'white': (1, 1, .97, 1), 'pink': (1, .40, .48, 1)}

def ball(name, location, scale, color, parent=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    if parent:
        obj.parent = parent
    material = bpy.data.materials.get(color)
    if material is None:
        material = bpy.data.materials.new(color)
    # diffuse_color alone is a viewport setting on newer Blender versions.
    # Always set the actual surface shader used by Cycles as well.
    material.diffuse_color = COLORS[color]
    material.use_nodes = True
    surface = material.node_tree.nodes.get('Principled BSDF')
    surface.inputs['Base Color'].default_value = COLORS[color]
    surface.inputs['Roughness'].default_value = .65
    obj.data.materials.append(material)
    for face in obj.data.polygons:
        face.use_smooth = True
    return obj

def character(name, x, bunny=False):
    root = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(root)
    root.location.x = x
    fur = 'cream' if bunny else 'yellow'
    ball(name+' body', (0, 0, .9), (.53, .40, .65), fur, root)
    ball(name+' head', (0, -.06, 1.70), (.56, .44, .52), fur, root)
    for side in (-1, 1):
        ball('foot', (side*.24, -.12, .16), (.22, .32, .14), fur if bunny else 'orange', root)
        ball('eye', (side*.19, -.455, 1.79), (.09, .055, .12), 'eye', root)
        ball('eye sparkle', (side*.19-.02, -.503, 1.83), (.028, .018, .032), 'white', root)
        ball('cheek', (side*.32, -.44, 1.60), (.09, .024, .045), 'pink', root)
    arms = [ball('paw' if bunny else 'wing', (side*.50, 0, .98), (.14, .25, .36), fur, root) for side in (-1, 1)]
    if bunny:
        for side in (-1, 1):
            ear = ball('ear', (side*.29, .01, 2.18), (.16, .13, .52), fur, root)
            ear.rotation_euler.y = side*.32
            ball('inner ear', (side*.32, -.12, 2.28), (.07, .025, .28), 'pink', root)
        ball('nose', (0, -.51, 1.60), (.075, .04, .05), 'pink', root)
        ball('overalls', (0, -.035, .74), (.55, .41, .45), 'mint', root)
        for side in (-1, 1):
            ball('strap', (side*.25, -.36, 1.10), (.07, .06, .27), 'mint', root)
            ball('button', (side*.25, -.43, 1.12), (.035, .02, .035), 'yellow', root)
    else:
        ball('beak', (0, -.52, 1.53), (.24, .22, .095), 'orange', root)
        ball('neckerchief', (0, -.02, 1.28), (.40, .33, .10), 'blue', root)
        scarf = ball('scarf point', (0, -.37, 1.11), (.15, .06, .22), 'blue', root)
        scarf.rotation_euler.y = .15
    return root, arms

def import_character(entry):
    before_objects = set(bpy.data.objects)
    before_actions = set(bpy.data.actions)
    model = Path(entry['model'])
    if model.suffix.lower() == '.glb':
        bpy.ops.import_scene.gltf(filepath=str(model))
    else:
        bpy.ops.import_scene.fbx(filepath=str(model))
    objects = list(set(bpy.data.objects)-before_objects)
    arm = find_armature(objects)
    if arm is None:
        raise ValueError(f"{entry['name']}: imported model has no armature")
    if sum(obj.type=='ARMATURE' for obj in objects)!=1:
        raise ValueError('starter import supports exactly one armature per model')
    actions = list(set(bpy.data.actions)-before_actions)
    action = next((a for a in actions if a.name == entry['clip']), None)
    if action is None:
        action = next((a for a in actions if a.name.rpartition('.')[0] == entry['clip'] and a.name.rpartition('.')[2].isdigit()), None)
    if action is None:
        raise ValueError(f"Missing clip {entry['clip']!r}. Imported clips: {[a.name for a in actions]}")
    for obj in objects:
        if obj.animation_data:
            for track in list(obj.animation_data.nla_tracks):
                obj.animation_data.nla_tracks.remove(track)
    shift_action_to_frame1(action)
    bind_action(arm, action)
    for curve in curves(action):
        if not any(mod.type=='CYCLES' for mod in curve.modifiers):
            curve.modifiers.new('CYCLES')
    # Normalize the model at the first animated frame, keeping imported parenting intact.
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    meshes = [obj for obj in objects if obj.type=='MESH']
    if not meshes:
        raise ValueError('model contains no mesh')
    points = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    lower = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    upper = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    if upper.z-lower.z < .00001:
        raise ValueError('model has zero height')
    factor = entry['height']/(upper.z-lower.z)
    root = bpy.data.objects.new(entry['name']+' placement',None)
    bpy.context.collection.objects.link(root)
    for obj in objects:
        if obj.parent not in objects:
            matrix = obj.matrix_world.copy()
            obj.parent=root
            obj.matrix_world=matrix
    root.scale=(factor,)*3
    position=Vector(entry['position'])
    center=Vector(((lower.x+upper.x)/2,(lower.y+upper.y)/2,lower.z))
    root.location=position-center*factor
    return arm, action


def build_scene(config):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    engine = config.get('engine', 'cycles')
    if engine not in ('cycles', 'eevee'):
        raise ValueError('Unknown render engine')
    scene.render.engine = 'CYCLES' if engine == 'cycles' else 'BLENDER_EEVEE_NEXT'
    if engine == 'cycles':
        scene.cycles.device = 'CPU'
        scene.cycles.samples = config['samples']
        denoise = config.get('denoise', True)
        scene.cycles.use_denoising = denoise
        if denoise:
            try:
                scene.cycles.denoiser = 'OPENIMAGEDENOISE'
            except TypeError as exc:
                raise ValueError('This Blender build lacks OpenImageDenoise. Use Lite mode explicitly or install an official Blender build for Quality mode.') from exc
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.adaptive_threshold = .03
        scene.view_layers[0].cycles.use_denoising = denoise
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = config['threads']
    scene.render.resolution_x = config['width']
    scene.render.resolution_y = config['height']
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.fps = config['fps']
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get('Background')
    background.inputs['Color'].default_value = (.60, .78, .95, 1)
    background.inputs['Strength'].default_value = .6
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    COLORS['grass'] = (.43, .72, .35, 1)
    ball('garden ground', (0, 0, -.22), (200, 200, .25), 'grass')
    for i in range(14):
        x, y = (-4 + i*.62), 1.0 + (i%3)*.45
        ball('flower center', (x, y, .38), (.085, .085, .085), 'yellow')
        for petal in range(5):
            angle = petal * math.tau/5
            ball('petal', (x+.13*math.cos(angle), y, .38+.13*math.sin(angle)), (.10, .07, .10), 'pink' if i%2 else 'white')
    imported = []
    if config.get('characters'):
        for entry in config['characters']:
            imported.append(import_character(entry))
        duck = bunny = None
        duck_arms = bunny_arms = []
    else:
        members = config.get('original_characters', ['milo', 'pip'])
        duck, duck_arms = character('Milo', -.70 if len(members) == 2 else 0) if 'milo' in members else (None, [])
        bunny, bunny_arms = character('Pip', .70 if len(members) == 2 else 0, True) if 'pip' in members else (None, [])
    bpy.ops.object.light_add(type='AREA', location=(-3, -4, 7))
    bpy.context.object.data.energy = 850
    bpy.context.object.data.size = 5
    bpy.context.object.rotation_euler = (Vector((0, 0, 1))-bpy.context.object.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.ops.object.camera_add(location=(0, -9, 3.5))
    camera = bpy.context.object
    scene.camera = camera
    camera.data.lens = 44
    return scene, camera, duck, bunny, duck_arms, bunny_arms, imported

def pose(root, arms, action, t, bunny=False):
    root.location.z = 0
    root.location.y = 0
    root.rotation_euler = (0, 0, 0)
    for arm in arms:
        arm.rotation_euler = (0, 0, 0)
    cycle = math.tau * t
    if action in ('waddle', 'walk', 'run'):
        cycle *= 2 if action == 'run' else 1
        root.location.y = -.25 * math.sin(t*.6)
        root.rotation_euler.y = .11 * math.sin(cycle*1.5)
        root.location.z = .04 * abs(math.sin(cycle*1.5))
    elif action == 'hop':
        root.location.z = (.24 if bunny else .10) * abs(math.sin(cycle))
    elif action == 'dance':
        root.rotation_euler.z = .15 * math.sin(cycle)
        root.rotation_euler.y = .10 * math.sin(cycle)
        for side, arm in zip((-1, 1), arms):
            arm.rotation_euler.y = side * (.4 + .25*math.sin(cycle))
    elif action == 'wave':
        arms[1].rotation_euler.y = -1.0 + .3*math.sin(cycle*1.5)
    elif action in ('talk', 'sing', 'idle'):
        # Deliberately a body gesture, not phoneme-driven facial animation.
        root.location.z = .015 * math.sin(cycle*.5)
        if action != 'idle':
            arms[1].rotation_euler.y = -.25 + .15*math.sin(cycle)

def camera_pose(camera, preset, progress):
    smooth = progress*progress*(3-2*progress)
    x, y, z = 0, -9, 3.5
    if preset == 'dolly':
        y += .8*smooth
    elif preset == 'arc':
        angle = -.14 + .28*smooth
        x, y = 9*math.sin(angle), -9*math.cos(angle)
    elif preset == 'pullback':
        y -= smooth
    camera.location = (x, y, z)
    camera.rotation_euler = (Vector((0, 0, 1.25))-camera.location).to_track_quat('-Z', 'Y').to_euler()

def main():
    config = json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
    scene, camera, duck, bunny, wings, paws, imported = build_scene(config)
    directory = Path(config['directory'])
    # Every frame is deterministic: restart can skip intact PNGs.
    for frame in range(1, config['frames']+1):
        destination = directory / f'{frame:05d}.png'
        if destination.exists():
            try:
                loaded = bpy.data.images.load(str(destination), check_existing=False)
                valid = tuple(loaded.size) == (config['width'], config['height'])
                bpy.data.images.remove(loaded)
                if valid:
                    continue
            except RuntimeError:
                pass
        t = (frame-1)/config['fps']
        scene.frame_set(frame)
        if duck is not None:
            pose(duck, wings, config['action'], t)
        if bunny is not None:
            pose(bunny, paws, config['action'], t, True)
        camera_pose(camera, config['camera'], (frame-1)/max(1, config['frames']-1))
        scene.render.filepath = str(destination)
        bpy.ops.render.render(write_still=True)

if __name__ == '__main__':
    main()

