# Optional ACE-Step 1.5 song generation

This adapter talks to a **separately installed local ACE-Step server**. It requests English singing and music together. No hosted paid API or paid API key is required. Software is free; compute, electricity, and any EC2 charges are yours. **Actual model inference, peak RAM, singing quality, and an end-to-end sung video are not validated yet.**

## Why this engine

ACE-Step can generate songs from a style prompt and lyrics. Its official install guide documents CPU inference, albeit significantly slower than GPU inference. We start with a 10-second, one-song request and the extra 5Hz language model disabled. This trades enhanced generation features for a smaller starting configuration; it does not establish an 8 GB RAM guarantee.

The repository and official `ACE-Step/Ace-Step1.5` model distribution are marked MIT. YuE2.cpp's MIT code does not override the underlying YuE2 weights' CC-BY-NC-4.0 label, so YuE2 is not our default for a potentially monetized channel. HeartMuLa is an alternative, but its standard configuration is oriented toward CUDA and multiple substantial models.

Sources checked:

- https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/INSTALL.md
- https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/API.md
- https://huggingface.co/ACE-Step/Ace-Step1.5
- https://huggingface.co/m-a-p/YuE2-3B
- https://github.com/HeartMuLa/heartlib

## Install the server separately

ACE-Step currently documents stable Python 3.11–3.12 and about 10 GB disk for core models, plus environment/download overhead. Do not reuse VoiceStudio's Python environment. Install `uv` through its [official instructions](https://docs.astral.sh/uv/getting-started/installation/) and Git, then on Linux/macOS:

```bash
git clone https://github.com/ace-step/ACE-Step-1.5.git
cd ACE-Step-1.5
uv sync --python 3.12
```

Start the experimental CPU-only server in this directory:

```bash
ACESTEP_DEVICE=cpu ACESTEP_INIT_LLM=false ACESTEP_LM_BACKEND=pt ACESTEP_USE_FLASH_ATTENTION=false ACESTEP_API_HOST=127.0.0.1 ACESTEP_API_PORT=8001 ACESTEP_QUEUE_WORKERS=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 uv run acestep-api
```

For Windows PowerShell, set the equivalent variables before the same launch command:

```powershell
$env:ACESTEP_DEVICE="cpu"
$env:ACESTEP_INIT_LLM="false"
$env:ACESTEP_LM_BACKEND="pt"
$env:ACESTEP_USE_FLASH_ATTENTION="false"
$env:ACESTEP_API_HOST="127.0.0.1"
$env:ACESTEP_API_PORT="8001"
$env:ACESTEP_QUEUE_WORKERS="1"
$env:OMP_NUM_THREADS="2"
$env:MKL_NUM_THREADS="2"
uv run acestep-api
```

The configuration explicitly avoids loading the extra LM. It does not mean PyTorch or the DiT/VAE necessarily fit on your machine. Initial model downloads may be large. Install and CPU-launch commands follow upstream documentation/source but have not been executed with model weights here; dependency or platform failures may require upstream troubleshooting.

## Generate a short sample

In a second terminal, return to `toon-pilot`. FFmpeg and FFprobe must be on PATH:

```bash
python3 song.py
```

This submits `examples/ace_sample.json` to `http://127.0.0.1:8001` and saves `output/music/sample.wav`. It uses batch size 1, eight inference steps, a fixed seed, supplied metadata, and disables LM thinking, caption rewriting, language detection, format enhancement, and sample mode. Server-side `ACESTEP_INIT_LLM=false` is also necessary; request flags alone do not control which models the server loads.

The JSON example is an original nursery-song prompt, not a request to copy a reference recording or singer. Listen for intelligible words, appropriate singing tone, timing, and balanced music. Passing file checks does not prove that vocals exist or sound good.

After the sample is satisfactory:

```bash
python3 song.py --request examples/ace_happy_feet.json --out output/music/happy_feet.wav
```

The second example requests 32 seconds. It uses different lyrics/tempo from the old manually notated score: they are alternative audio paths. The generated lyrics may not align with the existing video action timings; review and edit your scene plan after listening.

## Use a complete song in the video

```bash
python3 video.py create --preview --soundtrack output/music/happy_feet.wav
python3 video.py create --soundtrack output/music/happy_feet.wav
```

`--soundtrack` uses the complete song directly, preserving the source stereo/rate through to AAC encoding. Do not pass it via `--vocals`: that older option expects a mono vocal-only file and mixes in our procedural backing. `--soundtrack` cannot be combined with `--vocals` or `--instrumental`.

A complete soundtrack must match the full plan within one second even when previewing only its first two seconds. No automatic stretching or looping is applied. The old score/plan duration check remains in place; keep those durations matched too. The runner still prepares the tiny procedural score/backing files for compatibility but does not mix them into a supplied soundtrack.

## Resume and failure handling

A `.wav.job.json` file next to your output stores the request fingerprint and server task ID. If waiting times out or you stop the client, repeat the exact command to poll the same task. `--timeout 3600` allows a longer client wait. CPU time is unknown; increasing the timeout does not accelerate generation.

A failed generation, missing task, invalid audio, duration mismatch, or unreachable server is reported as failure. The client does not replace failure with instrumental music. The server's job store may be lost on restart: inspect the server before deleting a saved job record and submitting a replacement. Changing a request requires a different `--out` or deliberate removal of its job record after the old job is finished. No automatic retry of submission occurs; if the submit response itself is lost, inspect server jobs/logs to avoid duplicates.

Only one client can use the same output at once. After a hard kill, remove its `.lock` file only once no client is active. The adapter has no server cancellation command: stopping the client does not stop server generation. Requests/downloads use loopback HTTP and refuse redirects and off-server download URLs. For EC2, run both programs there or use your own SSH tunnel to the loopback server. This adapter expects the local server without API authentication; a 401 response needs server configuration review.

Do not run Blender and the ACE-Step server simultaneously on an 8 GB machine. After audio generation finishes, stop ACE-Step normally to release model memory, then render the video. This sequential workflow still needs a real target-machine memory benchmark.

## Validation boundary

Automated adapter tests use a local HTTP fixture server and synthetic WAV audio, not model-generated singing. They cover low-memory request flags, timeout/resume without duplicate submission, failed jobs, corrupt downloads, caching, and refusal of remote URLs. Real FFmpeg validates and decodes the fixture audio. The video integration test additionally checks an imported stereo 48 kHz soundtrack survives assembly. No claim of CoComelon-like quality is made without listening evidence.
