# Rhyme Studio dashboard

Rhyme Studio is a local interface for this repository's existing `song.py` and `video.py` commands. It does not load an AI model itself or use a paid API. Start it on Linux or macOS with Python 3; no extra dashboard packages are required:

```bash
git pull
python3 dashboard.py
```

On your own computer, open **http://127.0.0.1:8768**. For EC2, leave the dashboard running there and open a second terminal **on your computer**:

```bash
ssh -i /path/to/your-key.pem -N -L 8768:127.0.0.1:8768 ubuntu@YOUR_EC2_PUBLIC_IP
```

Replace the key path and public IP, keep this tunnel open, then visit the same local URL. You do not need to open port 8768 in an EC2 security group. The dashboard binds only to loopback and is intended for one trusted local user over SSH, not public hosting.

## Write, listen, animate

1. Enter an English rhyme, project name, song duration (10–120 seconds), tempo, and music/voice direction. Direction is a prompt, not a guaranteed voice selection or cloning feature.
2. Open **Scene timing & camera movement** to set movement, camera, duration and optional captions. Scene durations must add up to the song duration; **Split time evenly** helps. Timings use half-second steps. Both procedural characters appear together in this first version.
3. Click **Save rhyme & timing**. Choose a saved project from the menu to return to it later. Editing and saving makes a new project, preserving earlier audio and jobs.
4. Click **Generate song** after starting the separately installed ACE-Step server, or upload your own complete audio file. Uploads are limited to 64 MiB and must match the full song duration within one second. FFmpeg validates and converts uploads to a real WAV without mixing in procedural backing.
5. Listen using the audio player. Check that the words, singing, pronunciation and music are suitable. File validation is not a singing-quality assessment.
6. Stop the ACE-Step server with Ctrl+C in its terminal. Confirm this in the dashboard, then create a two-second preview. The server port is also checked before rendering. A preview without audio uses simple instrumental backing; the full-video button requires a complete song.
7. Review the video and download the song, preview or full video directly from the dashboard.

Install and start ACE-Step separately as described in [the music guide](ace-step.md):

```bash
bash scripts/install-music.sh --download-models
# Later, in a separate terminal:
bash scripts/start-music.sh
```

Generation, uploads and rendering are serialized within the dashboard. It does not manage manually started jobs outside the dashboard. Avoid running Blender and ACE-Step together on 8 GB RAM. No actual singing or 8 GB memory benchmark has been completed. The UI does not include spoken narration, voice cloning, precise lyric/phoneme alignment, or automatic publishing.

## Saved files and recovery

Projects live under `output/dashboard/<project-id>/`. This ignored directory contains lyrics, prompts, scene plans, timing scores, state, logs, audio and videos. They stay on your computer/EC2; back up the output directory yourself if needed. The timing score is rest-only because actual music comes from the complete uploaded/generated song. Scene captions are selectable subtitle tracks, not guaranteed word-level lyric timings.

Status and logs update while a job runs. There is no guessed progress percentage. Technical success is labelled as needing review. A missing engine or failed subprocess is shown as failure, never replaced with pretend singing. Retry **Generate song** on the same project to continue polling its saved upstream task; a timeout or dashboard shutdown does not cancel an ACE-Step server job. The existing adapter's handling of ambiguous submissions and stale locks still applies; see [recovery instructions](ace-step.md#resume-and-failure-handling).

Ctrl+C stops the dashboard and its local client/render process group. Starting again marks unfinished dashboard jobs as interrupted. After a hard kill, check for existing workers and follow the existing `.lock`/`.running` instructions before retrying. Do not remove locks while jobs are active. A single-instance lock prevents two dashboard processes sharing the same output directory.

Optional startup settings:

```bash
python3 dashboard.py --port 8768 --out output/dashboard --blender /path/to/blender
```

`--music-url` selects another loopback-only ACE-Step endpoint for an existing custom setup. It does not permit remote paid services. If you change the dashboard port, update the SSH tunnel and browser URL too.

## Validation

Run `python3 -m unittest discover -s tests -v`. Dashboard tests cover invalid/mismatched timing, unavailable workers, busy/full-video gates, real audio upload/decoding and cleanup, request origin/path restrictions, byte-range media downloads, restart state, and the actual song client subprocess against a fixture HTTP engine. Fixture audio is synthetic, not model singing.

The 25-test suite passed locally. An additional HTTP run created a project, uploaded a synthetic 10-second WAV, rendered a real two-second Blender 4.2.0 preview, and downloaded that MP4. DOM interaction checks covered timing errors, saving, scene splitting, engine failure, audio player/download controls and disabled actions after edits. A visual browser check was blocked by this execution environment's browser socket restrictions; page layout still needs an actual browser review. No ACE-Step model inference or EC2 memory benchmark was run.
