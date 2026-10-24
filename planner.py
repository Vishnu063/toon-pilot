"""Deterministic offline story-to-shot planning. Never invents model-generated prose."""
import re
import characters


def plan(title, text, duration=30, language='en', cast=None, orientation='portrait'):
    if not isinstance(title, str) or not title.strip() or len(title) > 100:
        raise ValueError('Title must contain 1–100 characters.')
    if not isinstance(text, str) or not text.strip() or len(text) > 8000 or '\x00' in text:
        raise ValueError('Story must contain 1–8000 characters.')
    if duration not in (30, 60, 120) or type(duration) is not int:
        raise ValueError('Automatic plans support 30, 60 or 120 seconds.')
    if language not in ('en', 'hi') or orientation not in ('portrait', 'landscape'):
        raise ValueError('Choose English/Hindi and portrait/landscape.')
    members = characters.select(['milo', 'pip'] if cast is None else cast)
    # Keep every word, in order. Split long lines at word boundaries, not by dropping text.
    words = text.split()
    count = min(12, max(2, duration // 10, (len(text) + 399) // 400))
    groups = [' '.join(words[i * len(words) // count:(i + 1) * len(words) // count]) for i in range(count)]
    groups = [g for g in groups if g]
    if any(len(g) > 500 for g in groups):
        raise ValueError('Story is too dense for captions; shorten it or add line breaks.')
    count = len(groups)
    ticks, extra = divmod(duration * 2, count)
    shots = []
    for i, line in enumerate(groups):
        action = 'hop' if re.search(r'\b(hop|jump)\b', line, re.I) else 'wave' if re.search(r'\b(wave|hello|bye)\b', line, re.I) else ['waddle', 'dance', 'wave'][i % 3]
        shots.append(dict(seconds=(ticks + (i < extra)) / 2, action=action,
            camera=['dolly', 'arc', 'static', 'pullback'][i % 4], caption=line,
            dialogue=line, speaker=members[i % len(members)]['id'],
            original_characters=[m['id'] for m in members], background='garden',
            expression='happy', transition='fade' if i else 'cut',
            description=f"{', '.join(m['name'] for m in members)} {action} in the garden."))
    return dict(title=title.strip(), language=language, orientation=orientation,
                generator='offline-template-v1', character_versions={m['id']: m['version'] for m in members}, scenes=shots)
