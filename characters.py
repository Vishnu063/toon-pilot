"""Versioned metadata for the original procedural starter characters."""
import copy

CHARACTERS = {
    'milo': dict(name='Milo', version=1, species='duck', color='yellow',
                 outfit='blue neckerchief', model='procedural:milo:v1', rig=None,
                 voice='en-boy', animations=['waddle', 'hop', 'dance', 'wave', 'idle', 'walk', 'run', 'talk', 'sing']),
    'pip': dict(name='Pip', version=1, species='bunny', color='cream',
                outfit='mint overalls', model='procedural:pip:v1', rig=None,
                voice='en-girl', animations=['waddle', 'hop', 'dance', 'wave', 'idle', 'walk', 'run', 'talk', 'sing']),
}


def select(names):
    if not isinstance(names, list) or not 1 <= len(names) <= 2 or len(set(str(n) for n in names)) != len(names):
        raise ValueError('Choose Milo, Pip, or both, without duplicates.')
    if any(not isinstance(n, str) or n not in CHARACTERS for n in names):
        raise ValueError('Unknown original character.')
    return [dict(id=n, **copy.deepcopy(CHARACTERS[n])) for n in names]
