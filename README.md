# Toon Pilot

Free-software building blocks for original animated stories and nursery rhymes.

**Current version: audio preparation starter.** It prepares a singing score and a simple instrumental backing, then mixes vocals you export from OpenUtau. It does not yet generate vocals automatically, animate characters, render video, or upload to YouTube. There is no LLM or autonomous agent in this version.

## Quick start (no Python packages or paid API)

Install Python 3.11+ and Git, then run:

```bash
git clone https://github.com/Vishnu063/toon-pilot.git
cd toon-pilot
python3 audio.py prepare examples/happy_feet.json
```

Windows: use `python` instead of `python3` if needed.

Outputs in `output/audio/`:

- `singing.ust`: 32-second melody with English lyric syllables, intended for OpenUtau import.
- `backing.wav`: quiet, procedural bell-like accompaniment; **not singing**.
- `timing.json`: duration, tempo, and explicit `prepared_not_sung` status.

Preparation replaces these generated files when rerun. Keep custom edits elsewhere.

## Add singing with OpenUtau

1. Download [OpenUtau](https://github.com/openutau/OpenUtau/releases) for your computer. Follow its [getting started guide](https://github.com/openutau/OpenUtau/wiki/Getting-Started).
2. Install an English voicebank whose terms allow your intended use, including monetized YouTube if applicable. No voicebank or model is bundled here. A voicebank is the singer's recorded samples or trained model; the editor alone cannot sing.
3. Open/import `output/audio/singing.ust`, select your singer, and choose its required English phonemizer and renderer. See [phonemizers](https://github.com/openutau/OpenUtau/wiki/Phonemizers). Prefer a lightweight sample-based voicebank for the first 8 GB CPU trial.
4. Preview and correct pronunciation, note splits, pauses, and pitch. The example has one beat per syllable at 60 BPM, plus a rest after each line. Its literal syllables are a starting point, not guaranteed input for every English phonemizer.
5. Export vocals as WAV with the complete timeline, including rests, starting at time zero. Preserve the 32-second alignment.
6. Convert your exported WAV if necessary. With FFmpeg installed:

```bash
ffmpeg -i vocals-export.wav -ar 22050 -ac 1 -c:a pcm_s16le vocals.wav
python3 audio.py mix --vocals vocals.wav --backing output/audio/backing.wav --out output/audio/song.wav
```

Keep vocals and backing within one second of each other; the tool rejects larger mismatches rather than silently truncating. Inputs must be mono 16-bit PCM WAV at 22050 Hz. Output cannot overwrite an input. Listen to the final result before publishing. Automated checks do not judge pronunciation or singing quality.

**OpenUtau import and actual singing have not been tested in this project yet.** Manual export is required; no undocumented headless OpenUtau command is assumed.

## Existing repos we reuse or plan to connect

| Project | Role | Integration status |
|---|---|---|
| [OpenUtau](https://github.com/openutau/OpenUtau) | Singing editor and voicebank renderer | UST preparation and manual vocal handoff implemented; app import unverified |
| [OpenVPI DiffSinger](https://github.com/openvpi/DiffSinger) | Optional neural singing through compatible OpenUtau voicebanks | Not bundled or tested; optional, model-dependent memory requirements |
| [Your VoiceStudio](https://github.com/Vishnu063/VoiceStudio) | Character speech, narration, and dialogue | Existing separate project; no adapter added yet; not our singing engine |
| [Blender](https://github.com/blender/blender) | Character animation and camera control | Planned; no video renderer implemented yet |
| [FFmpeg](https://github.com/FFmpeg/FFmpeg) | Audio conversion and later video assembly | Optional external conversion command above |

OpenUtau is free software. Voicebanks and model weights have separate licenses; inspect their own terms. This starter does not download third-party voices, imitate a real speaker, or bundle third-party assets. Heavy prompt-to-song models such as [ACE-Step](https://github.com/ace-step/ACE-Step-1.5) are deferred until memory requirements are verified; GPU VRAM figures do not establish compatibility with 8 GB system RAM.

## Your 8 GB computer and EC2

The Python score/backing preparation uses no model or GPU. Generate audio and render animation sequentially when video support is added. OpenUtau performance depends on the voicebank and renderer; 8 GB operation is a target, not a measured guarantee. Use the desktop for the manual singing editor. An EC2 machine without a desktop cannot complete that GUI step using this starter alone. There is no promise of free EC2 compute or unlimited cloud rendering.

## Change the song

Edit `examples/happy_feet.json`: `bpm`, and each note's `lyric`, MIDI `pitch` (60 = middle C), and `ticks` (480 = one beat). `R` represents a rest. English ASCII only in this UST starter. Duration is derived from note lengths and tempo, with a ten-minute cap. Longer scores are supported by preparation, but long vocal generation is untested.

## Verification

```bash
python3 -m unittest discover -s tests -v
```

Four local tests cover 32-second output, score fields, invalid tempo/lyric input, WAV format, duration mismatch, silent vocals, peak limiting, and preserving inputs. These tests do not run OpenUtau, a voicebank, VoiceStudio, or Blender. The first acceptance milestone remains an audible exported song followed by a reviewed 32-second animation.
