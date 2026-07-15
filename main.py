"""
Linkstream API
--------------
A small FastAPI service that wraps yt-dlp to:
  1. GET /api/formats   -> list available quality/format options for a URL
  2. GET /api/download  -> download the chosen format and stream it back

Run locally:
  pip install -r requirements.txt
  uvicorn main:app --reload --port 8000

Requires ffmpeg on PATH for merging separate video/audio streams
(e.g. `apt install ffmpeg` / `brew install ffmpeg`).
"""

import os
import uuid
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
import yt_dlp

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("linkstream")

app = FastAPI(title="Linkstream API", version="0.1.0")

# In production, replace "*" with your actual frontend origin(s).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Safety limits — tune for your deployment.
MAX_DURATION_SECONDS = 60 * 60 * 3  # 3 hours


def _human_size(num_bytes):
    if not num_bytes:
        return None
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.0f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/formats")
def list_formats(url: str):
    """Return basic info + a simplified list of downloadable formats for a URL."""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="That doesn't look like a valid link.")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"Couldn't read this link: {e}")
    except Exception as e:
        log.exception("Unexpected error probing %s", url)
        raise HTTPException(status_code=500, detail="Something went wrong reading that link.")

    duration = info.get("duration")
    if duration and duration > MAX_DURATION_SECONDS:
        raise HTTPException(status_code=413, detail="This video is too long for this service.")

    seen_labels = set()
    formats = []

    for f in info.get("formats", []):
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")

        if vcodec == "none" and acodec == "none":
            continue  # storyboard / metadata-only entries

        if vcodec != "none" and acodec != "none":
            kind = "video"
            label = f"{f.get('height', '?')}p"
        elif vcodec != "none":
            kind = "video-only"
            label = f"{f.get('height', '?')}p"
        else:
            kind = "audio"
            abr = f.get("abr")
            label = f"Audio · {int(abr)}kbps" if abr else "Audio"

        # de-duplicate near-identical entries (many sites list several
        # encodings of the same resolution)
        dedupe_key = (kind, label, f.get("ext"))
        if dedupe_key in seen_labels:
            continue
        seen_labels.add(dedupe_key)

        formats.append({
            "format_id": f["format_id"],
            "label": label,
            "ext": f.get("ext", "mp4"),
            "kind": kind,  # "video" (has audio), "video-only", or "audio"
            "size": _human_size(f.get("filesize") or f.get("filesize_approx")),
        })

    # Sort: combined video first (highest res first), then video-only, then audio
    kind_order = {"video": 0, "video-only": 1, "audio": 2}
    formats.sort(key=lambda f: (kind_order.get(f["kind"], 3), -(int(f["label"].rstrip("p")) if f["label"].rstrip("p").isdigit() else 0)))

    return {
        "title": info.get("title", "Untitled"),
        "thumbnail": info.get("thumbnail"),
        "duration": duration,
        "uploader": info.get("uploader"),
        "formats": formats,
    }


@app.get("/api/download")
def download(url: str, format_id: str):
    """Download the chosen format (merging audio if needed) and return the file."""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="That doesn't look like a valid link.")

    # Probe again to find out whether the chosen format already includes audio.
    probe_opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(probe_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"Couldn't read this link: {e}")

    chosen = next((f for f in info.get("formats", []) if f["format_id"] == format_id), None)
    if chosen is None:
        raise HTTPException(status_code=404, detail="That format is no longer available — try analyzing the link again.")

    if chosen.get("vcodec") != "none" and chosen.get("acodec") == "none":
        # Video-only stream: merge with the best available audio.
        format_selector = f"{format_id}+bestaudio/best"
    else:
        format_selector = format_id

    job_id = uuid.uuid4().hex
    outtmpl = str(DOWNLOAD_DIR / f"{job_id}.%(ext)s")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": format_selector,
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(result)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"Download failed: {e}")
    except Exception:
        log.exception("Unexpected error downloading %s (%s)", url, format_id)
        raise HTTPException(status_code=500, detail="Something went wrong during download.")

    # If ffmpeg merged streams, the final file may have a different extension.
    if ydl_opts.get("merge_output_format"):
        base, _ = os.path.splitext(filename)
        merged_path = f"{base}.{ydl_opts['merge_output_format']}"
        if os.path.exists(merged_path):
            filename = merged_path

    if not os.path.exists(filename):
        raise HTTPException(status_code=500, detail="The downloaded file could not be found.")

    title = result.get("title", "download")
    safe_title = "".join(c for c in title if c.isalnum() or c in " ._-").strip()[:80] or "download"
    ext = os.path.splitext(filename)[1]

    def cleanup():
        try:
            os.remove(filename)
        except OSError:
            pass

    return FileResponse(
        path=filename,
        filename=f"{safe_title}{ext}",
        media_type="application/octet-stream",
        background=BackgroundTask(cleanup),
    )
