# Offline video production

This extends the existing runner; it does not replace the score, singing,
YAML/imported-rig, dashboard or ArcReel paths. See [audit](feature-inventory.md).
There are no mandatory paid APIs or per-video AI credits. Compute, storage,
electricity, EC2 usage and YouTube quotas still have limits and costs.

## Install and start

Use Python 3.11+, Blender 4.2+, FFmpeg and FFprobe. On Ubuntu, install the
system tools with your package manager (`sudo apt install ffmpeg blender espeak-ng`).
Packaged Blender may lack OpenImageDenoise; Lite explicitly works without it.
Quality requires a compatible official Blender distribution. Keep TLS verification
enabled and verify official archives against the official SHA256 manifest.

```bash
cd /workspace/toon-pilot
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-scenes.txt
# Optional official YouTube libraries:
.venv/bin/python -m pip install -r requirements-upload.txt
```

In this Debian 13 amd64 cloud environment, the tested rootless alternative is:

```bash
bash scripts/install-speech.sh
export PATH=/workspace/tools/bin:$PATH
.venv/bin/python dashboard.py
```

The rootless installer uses signed Debian indexes and apt's package hash checks,
extracts packages outside the checkout, and preserves system directories. It
refuses other OS/architecture combinations. Processes must restart after a cloud
snapshot; the installed files remain. Each cloud task already has an isolated
checkout: do not create a Git worktree unless requested.

In the dashboard, select English/Hindi, duration, characters and orientation;
**Plan scenes automatically**, save, and choose **Create spoken narration**.
Review the speech, confirm ACE-Step is stopped, then render a preview or full
video. Manual scene editing, complete-audio upload and optional singing remain.
The planner supports automatic 30/60/120-second timing; manual timing supports the
existing 10–120-second range. Retry a failed dashboard action using the same
button; the render cache reuses verified scenes. Progress reports stages and
verified scenes, not a guessed percentage.

## Command-line production and recovery

```bash
export PATH=/workspace/tools/bin:$PATH
.venv/bin/python production.py enqueue --request examples/production.json
.venv/bin/python production.py worker
.venv/bin/python production.py list
# Only failed jobs can be retried; completed narration and valid clips are reused:
.venv/bin/python production.py retry JOB_ID
.venv/bin/python production.py worker
```

`examples/production-small.json` is a reproducible 180×320, 6-fps acceptance run;
`examples/production.json` uses Lite defaults. For a custom Blender binary,
pass `worker --blender /absolute/path/to/blender`. `--speech` selects an eSpeak NG
executable. The SQLite WAL queue stores each immutable request and its current
stage, error and status; identical requests deduplicate. One queue worker owns a
file lock. A second lock serializes rendering across CLI, queue and dashboard.
After a worker crash, a new worker recovers running rows. An existing render
`.running` marker still blocks its job: inspect processes before removing a stale
marker. Failed jobs are not automatically retried in a loop.

The worker checkpoints plan → speech → quiet procedural backing mix → existing
video runner → decoded MP4 → thumbnail → review. It never silently substitutes
instrumental audio when speech fails. Audio/video outputs are written under the
ignored `output/` tree. Preserve projects you care about. Frame PNGs are retained
to support recovery; no automatic cleanup deletes user media. Disk space remains
the operator's responsibility.

## Characters and planning

`characters.py` defines stable `milo`/`pip` v1 metadata and references the existing
original geometry. Milo is a yellow duck with a blue scarf; Pip is a cream bunny
with mint overalls. Selecting one centers that character; selecting both uses
the existing left/right layout. No random geometry is generated.

These are **procedural starter characters**, not professional rigs. `rig=None`
accurately records that their simple body/limb gestures are not a skeletal facial
rig. The existing GLB/FBX cast importer supports licensed rigged assets with
embedded clips; see [scenes](scenes.md). No external character asset is bundled.
Current originals have one happy expression. `walk`, `run`, `idle`, `talk` and
`sing` extend the original actions with simple body gestures. Talk/sing do not
animate phonemes or establish audible singing. Proper locomotion, additional
facial expressions and lip sync remain future work.

`planner.py` preserves the user's words in order and deterministically assigns
shot durations, captions, characters, dialogue speakers, garden backgrounds,
actions, camera presets and transition instructions. It does not understand
arbitrary prose or turn unsupported settings into fake renders. The only
background/expression presets currently accepted are garden/happy.
`stories.py` supplies three original short templates in English and Hindi for
optional daily operation; the templates rotate every three days and are not an
unlimited source of unique stories. Review scripts for age suitability.

## Rendering modes and editing

| Mode | Final portrait defaults | Rendering |
|---|---|---|
| Lite | 360×640, 12 fps | CPU Cycles, 8 samples, no denoising; visibly grainy |
| Quality | 1080×1920, 24 fps | CPU Cycles, 64 samples and OpenImageDenoise; speed unmeasured |
| Legacy | 540×960, 24 fps | Existing settings and denoising |
| Preview | 256×456, 12 fps, first two seconds | Selected mode's sampling; does not preview the entire story |

Landscape swaps dimensions (Quality becomes 1920×1080). CLI `video.py create`
accepts `--mode`, `--orientation`, `--width`, `--height`, `--fps` and `--threads`.
Dimensions must be even, 64–1920, at most 1080p pixels and match orientation;
fps is 2–30. Rendering is sequential with two CPU threads by default.
`--engine eevee` explicitly selects Eevee; it requires a working graphics/EGL
driver and has **not been validated here**. There is no silent engine switch.

FFmpeg encodes each scene once, applies per-scene fade-through-black where
requested, concatenates compatible H.264 clips with video stream copy, encodes
AAC audio, and adds selectable captions. These are not overlapping crossfades.
It validates dimensions/codec/duration and decodes video and audio, then extracts
a real thumbnail. Fingerprints include settings, source, model bytes, soundtrack
and Blender/FFmpeg binary size/mtime; changing those invalidates old clips.
Renderer subprocess logs retain the latest 1–2 MiB. Status records timing and
maximum child peak RSS; that value is not a sum of concurrent processes.

## Speech, music and singing

eSpeak NG provides offline English/Hindi speech. Boy/girl labels select synthetic
variants, not recorded children or cloned voices. Automatic scene speakers bind
Milo to a stable boy-style variant and Pip to a girl-style variant in the chosen
language. Speech is robotic and pronunciation still needs human listening.
Each utterance must fit its scene with at least 150 ms remaining; long text
fails with a specific scene number instead of clipping words or speeding up
speech. Remaining scene time is padded with silence; a sparse script has long
pauses. Shorten dense scripts or adjust their timing.

The queue mixes speech with the existing quiet backing and limits output peak.
Audio reports record `spoken_narration_not_singing`, speech duration per scene,
timeline starts, RMS and peak. Decode, duration and peak checks cannot determine
pronunciation, age suitability or whether an imported recording contains vocals.

`narration.py --engine piper --model /path/voice.onnx` is an optional local
adapter requiring its `.onnx.json` config; **model inference is untested here**.
The maintained [Piper project](https://github.com/OHF-Voice/piper1-gpl) and every
voice model have separate license obligations. Match language/voice to your model;
the adapter does not infer its suitability or choose a model automatically.
Edge-TTS is not required because it depends on a hosted service and its terms.

For actual singing use the existing [ACE-Step path](ace-step.md) or approved
OpenUtau/prerecorded vocals. ACE-Step code/model licensing and alternatives are
documented there; no model was downloaded or inferred in this upgrade. Its
MIT labeling does not establish rights to arbitrary other voices or weights.
Natural singing, exact lyric alignment and spoken-to-sung conversion remain
unverified. Instrumental-only output is never described as singing.

## Private YouTube OAuth

Uploads are opt-in, use the official YouTube Data API, request **private**
visibility and mark this children's content as made for kids. There is no public
publishing option. Account quotas, upload restrictions and OAuth app verification
still apply. Do not bypass restrictions or CAPTCHAs.

1. Enable YouTube Data API v3 in your Google Cloud project and configure its OAuth
   consent screen/test users as appropriate. Create an OAuth **Desktop** client.
2. Store its JSON securely at `output/private/client.json`, which is ignored;
   never put credentials in Git or chat. Install `requirements-upload.txt`.
3. Run from a trusted desktop or through an SSH tunnel forwarding port 8769:

```bash
.venv/bin/python youtube_upload.py connect --client output/private/client.json
```

OAuth opens an explicit browser consent flow with loopback callback port 8769;
there is no headless password or device-code workaround. The ignored token file
is written mode 0600. Restart the dashboard to refresh its connection indicator.
The token-present indicator does not prove current authorization or quota.
Then review a full video and click **Upload privately to YouTube**, or:

```bash
.venv/bin/python youtube_upload.py upload \
  --video /path/to/completed/video.mp4 \
  --receipt output/private/my-video-upload.json \
  --title 'Milo and Pip share a sunny day'
```

Title and description come from the saved project; tags are conservative fixed
animation/story tags. A thumbnail is extracted locally; automatic thumbnail
upload is not implemented. Each upload receipt records media SHA256, status and
the returned video ID. Repeating a completed receipt returns its recorded ID.
Any ambiguous attempt, network failure or lost response blocks automatic
resubmission; inspect YouTube Studio before manually resolving it. Do not delete
the receipt and blindly retry. Automatic resumable-session recovery is not
implemented; duplicate prevention takes priority.

Cloud networking needs `accounts.google.com`, `oauth2.googleapis.com`,
`youtube.googleapis.com` and `www.googleapis.com` allowed. TLS trust and inherited
proxy settings are preserved. No YouTube account/OAuth client was supplied, so
only fixture upload behavior and dependency installation were tested.

## Optional daily operation

```bash
# Enqueue today's original template, deduplicated by calendar date in this zone:
.venv/bin/python production.py daily --timezone Asia/Kolkata
# Or supply your own original 30-second script:
.venv/bin/python production.py daily --request examples/production.json
.venv/bin/python production.py worker
```

To opt into a scheduler, invoke `bash scripts/daily-production.sh` using your
existing cron/systemd scheduler. No recurring job is installed automatically.
For a server configured in UTC, this example runs at 09:00 India time and keeps
only the latest scheduler log (SQLite/per-job history remains):

```cron
30 3 * * * cd /workspace/toon-pilot && bash scripts/daily-production.sh > output/daily.log 2>&1
```

Create `output/` first. Default operation never uploads. To enable private uploads
for reviewed automation, explicitly add `"upload_private": true` to a request
and invoke `worker --allow-private-upload --youtube-token /secure/token.json`
after configuring OAuth and quotas. Both opt-ins are required. Without the
worker flag, rendering completes and upload remains disabled/pending review.
An uncertain upload receipt still blocks duplicates on retry. The stock daily
wrapper does not enable uploads. The scheduler clock/daemon is not tested here;
two repeated daily commands were tested to create exactly one queue row.

## Optional AI investigation

`python capabilities.py` reports CPU count, available system memory, disk and
NVIDIA name/VRAM when `nvidia-smi` works. No GPU was detected here. There is no
AI inference backend installed or represented as working, and no large-model
downloads occur automatically. Blender remains independent of all such engines.

Upstream docs/licenses were read on 2026-10-24:

| Project | Upstream resource example | Decision |
|---|---|---|
| [Wan 2.2](https://github.com/Wan-Video/Wan2.2) | TI2V-5B example: at least 24 GB VRAM; larger examples: 80 GB | Apache-2.0 code; adapter deferred without compatible GPU/models |
| [FramePack](https://github.com/lllyasviel/FramePack) | At least 6 GB GPU memory; CUDA setup | Apache-2.0 code; adapter deferred, model licenses also require review |
| [AnimateDiff](https://github.com/guoyww/AnimateDiff) | Documented high-resolution example: about 13 GB VRAM | Apache-2.0 code; base/personalized/motion models require their own review |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | Workflow/model-dependent; CPU support is not a practical video-speed guarantee | GPL-3.0 code; no arbitrary-workflow adapter or unaudited custom nodes added |

These are upstream configuration examples, not measured requirements or promises
for every model. An 8 GB system RAM machine is not a 6/8 GB VRAM GPU.

## Verification and remaining work

Run `PATH=/workspace/tools/bin:$PATH .venv/bin/python -m unittest discover -s tests -v`.
All 40 tests passed: the original 30 tests plus 10 production tests exercise real FFmpeg assembly,
failure/resume, HTTP fixtures, deterministic planning, real English/Hindi eSpeak
speech, overflow rejection, durable queue retry and private/ambiguous upload
contracts. CI installs FFmpeg/eSpeak and runs these tests; cloud GitHub Actions
execution is not claimed until it runs remotely.

The optional DOM test uses a running dashboard and jsdom installed outside the
checkout (`npm install --prefix /tmp/toon-ui-check --ignore-scripts jsdom@26`):
`NODE_PATH=/tmp/toon-ui-check/node_modules node tests/dashboard_dom_smoke.cjs`.
It saves a planned project, generates real speech, renders/downloads a real
landscape preview and checks disconnected-upload gating. This is DOM/HTTP
validation, not a visual browser-layout review.

Measured real acceptance run: 30 seconds, three scenes, 180×320, 6 fps, CPU Cycles,
8 samples, two threads, eSpeak narration and procedural backing. It produced
H.264/AAC/`mov_text`, passed complete video/audio decoding, and yielded a real
thumbnail. Latest wall time: **2:22.11**; GNU time maximum RSS: **282,524 KiB (~276 MiB)**.
An earlier run took 2:43.03 and 280,268 KiB.
Maximum RSS is the largest measured process/child value, not total machine RAM
or a concurrent-process sum. The host reports ~33 GiB RAM; no 8 GB EC2 benchmark
or 1080p speed measurement was performed. A repeat reused all three clips and
revalidated media in ~2.75 seconds. These measurements describe this sample only.

![Actual low-resolution starter render](assets/production-small.jpg)

Current sample output is retained under `output/acceptance-final/` (and the earlier `output/acceptance-30/`) in this cloud
workspace, alongside JSON audio/resource/media reports. Those ignored files are
not pushed to Git. The screenshot above is a genuine extracted frame; its
visible grain reflects Lite settings. Human speech/visual review remains required.

Remaining work: professional rigs and expressions, real phoneme lip sync,
additional backgrounds/SFX, model-backed singing and Piper trials, GPU adapters,
real YouTube authorization/upload, automatic thumbnail upload, visual dashboard
review, 1080p and target 8 GB benchmarks, and bounded retention/cleanup policy
for long-running daily production. The optional timer must be enabled and
observed on the user's actual deployment machine.
