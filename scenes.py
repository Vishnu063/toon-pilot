"""Load JSON plans or our small YAML scene format; export explicit timed captions."""
import copy
import json
import math
from pathlib import Path


def load_plan(path):
    path = Path(path).resolve()
    if path.suffix.lower() in {'.yaml', '.yml'}:
        try:
            import yaml
        except ImportError as exc:
            raise ValueError('YAML scenes need PyYAML: python3 -m pip install -r requirements-scenes.txt') from exc
        plan = yaml.safe_load(path.read_text(encoding='utf-8'))
    else:
        plan = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(plan, dict):
        raise ValueError('scene file must contain a mapping')
    cast = plan.pop('cast', {})
    if not isinstance(cast, dict):
        raise ValueError('cast must be a mapping')
    shots = plan.get('scenes')
    if not isinstance(shots, list) or any(not isinstance(s, dict) for s in shots):
        raise ValueError('scenes must be a list of mappings')
    for scene in shots:
        members = scene.get('characters')
        if members is None:
            continue
        if not isinstance(members, list) or not 1 <= len(members) <= 4:
            raise ValueError('characters must name 1 to 4 cast members')
        resolved = []
        for name in members:
            if not isinstance(name, str) or name not in cast:
                raise ValueError(f'unknown cast member: {name}')
            entry = copy.deepcopy(cast[name])
            if not isinstance(entry, dict) or not isinstance(entry.get('model'), str):
                raise ValueError(f'{name} needs a model path')
            model = (path.parent / entry['model']).resolve()
            if model.suffix.lower() not in {'.glb', '.fbx'} or not model.is_file():
                raise ValueError(f'{name}: model must be an existing .glb or .fbx file: {model}')
            if not isinstance(entry.get('clip'), str) or not entry['clip']:
                raise ValueError(f'{name} needs an exact animation clip name')
            height = entry.get('height', 2)
            if type(height) not in (int,float) or not math.isfinite(height) or not .1 <= height <= 10:
                raise ValueError('character height must be 0.1 to 10')
            position = entry.get('position', [0,0,0])
            if not isinstance(position,list) or len(position)!=3 or any(type(n) not in (int,float) or not math.isfinite(n) or abs(n)>20 for n in position):
                raise ValueError('position must contain three finite coordinates within +/-20')
            entry.update(name=name, model=str(model), height=height, position=position)
            resolved.append(entry)
        scene['characters'] = resolved
    return plan


def timestamp(seconds):
    milliseconds = round(seconds*1000)
    hours, milliseconds = divmod(milliseconds,3600000)
    minutes, milliseconds = divmod(milliseconds,60000)
    seconds, milliseconds = divmod(milliseconds,1000)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}'


def write_captions(scenes, durations, destination):
    blocks=[]
    start=0
    for scene, duration in zip(scenes,durations):
        caption=scene.get('caption','')
        if not isinstance(caption,str) or len(caption)>500 or '-->' in caption or '\x00' in caption:
            raise ValueError('caption must be text of at most 500 characters, without SRT arrows or nulls')
        text='\n'.join(line.strip() for line in caption.splitlines() if line.strip())
        if text:
            blocks.append(f'{len(blocks)+1}\n{timestamp(start)} --> {timestamp(start+duration)}\n{text}\n')
        start+=duration
    Path(destination).write_text('\n'.join(blocks),encoding='utf-8')
    return len(blocks)
