# YAML scenes, rigged characters and captions

This focused integration reuses a small piece of [anim-studio](https://github.com/DvaitAI-tech/anim-studio) rather than depending on its complete Windows/GPU/voice environment. Our runner retains sequential CPU rendering, cached frames/clips, OpenUtau audio handoff, and the optional local ACE-Step client.

## Start with the included scene

Install the optional YAML dependency in your Python environment:

```bash
python3 -m pip install -r requirements-scenes.txt
python3 video.py create --plan examples/happy_feet.scene.yaml --preview
```

This is an instrumental, two-second preview using the existing original procedural duck/bunny. It does not require a model download or voicebank. After supplying a reviewed complete song:

```bash
python3 video.py create --plan examples/happy_feet.scene.yaml --soundtrack output/music/happy_feet.wav
```

Use `--instrumental` explicitly to render the full example without singing. Existing JSON plans remain supported without PyYAML.

## Captions

Add `caption: Your text` to any scene. The runner creates `captions.srt` and embeds a selectable English `mov_text` subtitle track in the MP4. Enable subtitles in your player. These captions are **not burned into the image**, and players/platforms may not automatically display or retain the MP4 track; the SRT can be used separately in an editor or uploaded manually. There is no YouTube upload integration here.

Each caption occupies its full scene. Timing uses the frame-rounded scene durations; the preview's caption ends at its two-second cutoff. No speech recognition, lyric alignment, karaoke highlighting, or word-level sync is implied. The included example text is a scene description, not a transcript of every possible soundtrack. Edit it to match your chosen audio.

## Import a rigged character with embedded clips

Download a `.glb` or `.fbx` that contains a mesh, exactly one armature and a named skeletal animation. Use an asset whose license permits your intended use. [Quaternius](https://quaternius.com/) is one source discussed by upstream; no third-party character pack is downloaded or redistributed here. This update does not include high-quality replacement models for Milo/Pip.

Example scene (save beside your other scenes and adjust the model path):

```yaml
title: Garden dance
cast:
  dancer:
    model: ../assets/characters/dancer.glb
    clip: Dance
    height: 2
    position: [0, 0, 0]
scenes:
  - seconds: 32
    action: dance
    camera: arc
    characters: [dancer]
    caption: Dance along with me!
```

Model paths are relative to the scene file. `clip` must match the **imported Blender action name**, which may include the rig name added by an exporter. A missing clip prints the names imported from the model instead of silently accepting a frozen character. Blender's `.001` collision suffix is handled for multiple instances.

`height` normalizes the model to the requested world height at the first animation frame; `position` places it in the garden. Keep characters near the origin for the existing camera presets. Clip keyframes are shifted to frame one and their curves loop over the shot. Animation speed follows the scene frame rate; it is not automatically retimed to the music. Up to four cast entries can be selected in a scene.

When `characters` is omitted, the procedural Milo and Pip appear. When it is provided, selected imported characters replace that pair. For imported actors the embedded clip drives motion; the scene's `action` label is kept for schema compatibility and does not retarget the character. Different clips can be selected by defining additional cast entries. Separate animation files, automatic rigging, cross-skeleton retargeting, facial animation, and singing lip-sync are not implemented.

Prefer a self-contained `.glb`. FBX may reference textures outside the file; ensure they exist locally. Cache fingerprints include the selected model bytes but not separately referenced texture files: use a fresh `--out` directory after changing external textures. Large meshes/textures can exceed 8 GB despite sequential rendering.

## Reused code and differences from upstream

`third_party/anim_studio/rig.py` adapts `find_armature`, `bind_action`, and `shift_action_to_frame1` from `studiolib/rig.py` at commit `58c258f674788360ed855eceb0cfdbedfff7a65b`. The original MIT copyright/license is preserved in that directory. Changes make binding errors explicit and support iterating layered action curves. The original code's helper for Blender 4.4+ action slots is retained, but those versions still need a runtime trial.

YAML cast resolution and shot-level SRT timing follow the architecture of upstream, with a smaller new schema. **This is not a full anim-studio schema importer.** We do not import its `use:` recipes, role-specific motion library, Orpheus/dots voice setup, branded end card, or MCP control path. The generated clip is a deterministic preset workflow, not an LLM agent.

## Checks

```bash
python3 -m unittest discover -s tests -v
```

The tests cover YAML parsing, missing characters/assets, caption timing, model-content cache invalidation, and actual FFmpeg subtitle/audio/video assembly using synthetic renderer fixtures.

An optional real-Blender check creates its own original tiny animated GLB fixture, verifies bone motion after importing it, renders a frame, and checks that a missing clip is rejected:

```bash
blender --background --factory-startup --python-exit-code 1 --python tests/blender_rig_smoke.py
```

This synthetic rig test does not validate any specific Quaternius asset, FBX import, or an 8 GB memory ceiling. Actual singing quality remains a separate uncompleted acceptance test.

### Validation for this update

15 automated tests passed. Blender 4.2.0 passed the synthetic rig check (including actual changing bone pose, rendering and missing-clip rejection). A real two-second YAML-driven CPU preview rendered, with H.264 video, AAC audio, and a selectable `mov_text` caption track; its SRT ended at exactly two seconds. A repeat run reused the validated clip and completed media checks. This preview was instrumental, and no full 32-second render or third-party character-pack trial was performed.
