"""Adapted from DvaitAI-tech/anim-studio/studiolib/rig.py, commit
58c258f674788360ed855eceb0cfdbedfff7a65b. Copyright (c) 2026 DvaitAI.
MIT; see LICENSE. Changes: fail on slot-binding errors; iterate layered curves.
"""

def find_armature(objects):
    for obj in objects:
        if obj.type == 'ARMATURE':
            return obj
    return None


def bind_action(arm, action):
    """Bind the action slot as well as the action on Blender 4.4+ rigs."""
    if not arm.animation_data:
        arm.animation_data_create()
    arm.animation_data.action = action
    slots = list(getattr(action, 'slots', []))
    if slots:
        objects = [slot for slot in slots if getattr(slot, 'target_id_type', 'OBJECT') == 'OBJECT']
        arm.animation_data.action_slot = (objects or slots)[0]


def curves(action):
    if hasattr(action, 'fcurves'):
        yield from action.fcurves
    else:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in getattr(strip, 'channelbags', []):
                    yield from bag.fcurves


def shift_action_to_frame1(action):
    """Normalize an imported animation's timeline before playing it."""
    if action.get('_shifted_to_1'):
        return
    offset = action.frame_range[0]-1
    if abs(offset)>.5:
        for curve in curves(action):
            for point in curve.keyframe_points:
                point.co.x -= offset
                point.handle_left.x -= offset
                point.handle_right.x -= offset
            curve.update()
    action['_shifted_to_1']=True
