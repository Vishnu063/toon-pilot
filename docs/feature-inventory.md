# Audit and implementation inventory

Audit baseline: `397bb59`. The repository already has one Blender → FFmpeg runner;
new production orchestration must call it rather than add another renderer.

| Area | Reusable baseline | Gap / improvement |
|---|---|---|
| Audio | UST score, procedural backing, PCM mixing, imported complete soundtracks | No speech engine; singing only through optional ACE-Step or manual OpenUtau |
| Scenes | JSON/YAML, captions, cast GLB/FBX import with embedded skeletal clip | No automatic planner or versioned built-in character metadata |
| Blender | Original Milo/Pip geometry, four actions/cameras, lights/garden | Starter geometry; no facial rig or phoneme lip sync; fixed Cycles settings |
| Video | Sequential rendering, scene/frame cache, failure/resume, FFmpeg concat, subtitles | Fixed portrait output; no thumbnail or measured resource report |
| Dashboard | Local HTTP UI, project history, upload, serialized jobs, downloads | Manual scenes; no narration/planning controls or scheduling |
| Integrations | Optional ArcReel brief handoff and ACE-Step HTTP client | No YouTube OAuth/uploader, GPU video backend or scheduler |
| Tests | 30 passing tests including real FFmpeg and HTTP fixtures | Real default Blender fails because distro build lacks OpenImageDenoise |
| CI | No GitHub Actions found | Add a lightweight media/test workflow |

Working baseline checks do not validate natural singing, provider inference,
visual quality, a live YouTube upload or an 8 GB EC2 memory ceiling. Preserve all
existing ignored output and user media. See automation.md for implementation and
current validation results.
