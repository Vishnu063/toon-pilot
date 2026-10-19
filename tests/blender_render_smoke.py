"""Real Blender regression for white materials and disabled denoising.
blender --background --factory-startup --python-exit-code 1 --python tests/blender_render_smoke.py
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bpy
import blender_scene

folder = Path('output/render-smoke').resolve()
folder.mkdir(parents=True, exist_ok=True)
config = dict(width=256, height=456, fps=12, samples=32, threads=2)
scene, camera, *_ = blender_scene.build_scene(config)
for color in ('yellow', 'blue', 'mint', 'eye', 'grass'):
    material = bpy.data.materials[color]
    assert material.use_nodes, f'{color}: missing render shader'
    surface = material.node_tree.nodes.get('Principled BSDF')
    assert all(abs(a-b) < 1e-5 for a, b in zip(
        surface.inputs['Base Color'].default_value, blender_scene.COLORS[color]))
assert scene.cycles.use_denoising and scene.view_layers[0].cycles.use_denoising
blender_scene.camera_pose(camera, 'dolly', 0)
scene.render.filepath = str(folder/'frame.png')
bpy.ops.render.render(write_still=True)
# Check actual output pixels too: a valid MP4 can still contain white characters.
image = bpy.data.images.load(scene.render.filepath, check_existing=False)
pixels = list(image.pixels)
yellow = blue = green = 0
for i in range(0, len(pixels), 4):
    r, g, b = pixels[i:i+3]
    yellow += r > .5 and g > .25 and r > b*1.4 and g > b*1.25
    blue += b > .3 and b > r*1.3 and g > r*1.2
    green += g > .25 and g > r*1.15 and g > b*1.15
assert yellow > 300, f'Yellow duck missing: {yellow} pixels'
assert blue > 100, f'Blue scarf missing: {blue} pixels'
assert green > 1000, f'Green garden missing: {green} pixels'
print(f'REAL RENDER CHECK PASSED: yellow={yellow}, blue={blue}, green={green}')
