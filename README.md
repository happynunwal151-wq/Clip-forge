# ClipForge AI — local creator studio

A local-first full-stack video clipping studio. The browser UI talks to a FastAPI backend; source videos are processed on the computer/server where ClipForge is running.

## What works in this build

- Responsive dashboard, clip studio, clips library, caption/service settings.
- Upload MP4/MOV/MKV/WebM/M4V/AVI files to the local backend.
- FFmpeg metadata inspection and video rendering.
- Export clips in 9:16, 1:1, 4:5 or 16:9.
- Create custom remixes from the original source with editable start/end times, aspect ratio and caption-burn setting.
- Generate a poster thumbnail for each rendered clip/remix.
- Transcript-aware highlight heuristics when Faster-Whisper is installed.
- Optional Gemini-based highlight selection when `GEMINI_API_KEY` is configured.
- Evenly spaced fallback clips when no transcript/AI is available (clearly labelled as fallback).
- Optional local Faster-Whisper transcription with word timestamps.
- Upload an existing SRT/VTT transcript when you do not want to install Whisper.
- SRT sidecar downloads and burned-in subtitles when a transcript exists.
- Original browser-only ClipForge editor preserved at `/static/legacy-browser-editor.html`.

## Requirements

- Python 3.10+
- FFmpeg and FFprobe installed and available on PATH
- A modern browser

## Run on Windows

1. Install Python and FFmpeg.
2. Extract this ZIP to a normal folder.
3. Double-click `run.bat`.
4. Open http://127.0.0.1:8000 in Chrome or Edge.

## Run on macOS/Linux

```bash
chmod +x run.sh
./run.sh
```

Then open http://127.0.0.1:8000.

## Optional AI transcription and ranking

After the first run, edit `.env`:

```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash
WHISPER_MODEL=small
MAX_UPLOAD_MB=2048
```

Restart the server after changing `.env`.

To install local transcription:

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install faster-whisper
```

To enable Gemini ranking:

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install google-genai
```

If either optional package/key is absent, the application still runs using its documented fallback. You can upload an existing SRT/VTT transcript to enable transcript-based clip selection and subtitles without Whisper. AI selection quality depends on transcript quality and model availability.

## API

- `GET /api/health` — service readiness
- `POST /api/jobs` — upload and create a clip job
- `GET /api/jobs` — list jobs
- `GET /api/jobs/{id}` — job status and outputs
- `GET /api/jobs/{id}/transcript` — transcript JSON
- `POST /api/jobs/{id}/remix` — render a custom time range from the original source
- `GET /api/clips/{id}/{filename}` — download MP4/SRT/thumbnail

Interactive API docs: http://127.0.0.1:8000/docs

## Storage and privacy

Uploads are stored in `data/uploads/`; outputs and transcripts are stored in `data/outputs/`. This is a single-user local deployment with no authentication. Do not expose it to the public internet without adding authentication, HTTPS, request limits and a proper job queue. Back up files you want to keep.

## Not yet integrated

Direct publishing to Instagram/TikTok/YouTube, multi-user cloud accounts, team workspaces, live-stream recording, B-roll search, face tracking, speaker diarization, animated caption templates, analytics ingestion, billing and production-grade distributed job processing are not implemented in this build. Platform publishing needs approved developer apps, OAuth credentials and platform policy compliance. The interface does not pretend those functions are live.

## Repository and licence notes

This project is an original integration. It does not copy SupoClip source code. The current SupoClip release describes a noncommercial source licence and says commercial/team/client use requires written permission. PeakCut and OpenSource Clipping identify MIT licences; review each repository's complete licence and notices before copying or redistributing their source/assets. Feature inspiration is not a substitute for licence review.

- https://github.com/NaufalRizqullah/opensource-clipping
- https://github.com/FujiwaraChoki/supoclip
- https://github.com/haziqahmedqasmi/PeakCut

## Run with Docker

1. Install Docker Desktop or Docker Engine.
2. Copy `.env.example` to `.env` (optional keys can remain blank).
3. From this folder run `docker compose up --build`.
4. Open http://127.0.0.1:8000.

The `data/` folder is mounted so uploaded files, exports and the SQLite workspace database persist across container restarts.

## Creator spaces, queue and analytics

Creator Spaces stores local channel labels/handles. Publishing Queue stores draft/planned posts and links to generated clips. Analytics reports only local ClipForge project/export/queue totals. Neither page claims that social accounts are connected or that content was actually published.
