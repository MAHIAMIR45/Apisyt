import os
import re
import json
import random
import shutil
import tempfile
import threading
from flask import Flask, request, Response, jsonify
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp_downloads")
COOKIES_FILE = os.path.join(BASE_DIR, "cookies.json")
os.makedirs(TEMP_DIR, exist_ok=True)

_USER = "gpxjaoxt"
_PASS = "trexu8zcabdr"
PROXIES = [
    f"http://{_USER}:{_PASS}@38.154.203.95:5863",
    f"http://{_USER}:{_PASS}@198.105.121.200:6462",
    f"http://{_USER}:{_PASS}@64.137.96.74:6641",
    f"http://{_USER}:{_PASS}@209.127.138.10:5784",
    f"http://{_USER}:{_PASS}@38.154.185.97:6370",
    f"http://{_USER}:{_PASS}@84.247.60.125:6095",
    f"http://{_USER}:{_PASS}@142.111.67.146:5611",
    f"http://{_USER}:{_PASS}@191.96.254.138:6185",
    f"http://{_USER}:{_PASS}@31.58.9.4:6077",
    f"http://{_USER}:{_PASS}@104.239.107.47:5699",
]

def get_random_proxy():
    return random.choice(PROXIES)

QUALITY_MAP = {
    "2160": 2160, "1440": 1440, "1080": 1080, "720": 720,
    "480": 480, "360": 360, "240": 240, "144": 144,
    "best": None, "audio": None,
}
QUALITY_LABELS = {
    "2160": "4K Ultra HD", "1440": "2K Quad HD", "1080": "Full HD",
    "720": "HD", "480": "SD", "360": "Low", "240": "Very Low",
    "144": "Minimum", "best": "Best Available", "audio": "Audio Only (MP3)",
}


def sanitize(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    return name[:180].strip()


def normalize_url(url: str) -> str:
    url = url.strip()
    m = re.search(r"shorts/([A-Za-z0-9_-]{11})", url)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url


def json_cookies_to_netscape(json_path: str) -> str:
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, dir=TEMP_DIR)
    tmp.write("# Netscape HTTP Cookie File\n\n")
    try:
        with open(json_path) as f:
            cookies = json.load(f)
        for c in cookies:
            domain  = c.get('domain', '.youtube.com')
            flag    = 'FALSE' if c.get('hostOnly') else 'TRUE'
            path    = c.get('path', '/')
            secure  = 'TRUE' if c.get('secure') else 'FALSE'
            expires = int(c.get('expirationDate', 0))
            name    = c.get('name', '')
            value   = c.get('value', '')
            tmp.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
    except Exception:
        pass
    tmp.close()
    return tmp.name


# ─── Pass 1: Android — no SABR, no cookies needed, public videos ──────────────
def opts_android(extra=None):
    opts = {
        "quiet": True,
        "noplaylist": True,
        "proxy": get_random_proxy(),
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
            }
        },
        "http_headers": {
            "User-Agent": (
                "com.google.android.youtube/19.09.37 "
                "(Linux; U; Android 13; en_US) gzip"
            ),
        },
        "sleep_interval": 1,
        "sleep_interval_requests": 1,
    }
    if extra:
        opts.update(extra)
    return opts


# ─── Pass 2: Web Creator + cookies — age-restricted / fallback ────────────────
def opts_web(cookie_file, extra=None):
    po_token = os.environ.get("PO_TOKEN", "").strip()
    extractor_args = {
        "player_client": ["web_creator", "web"],
        "skip": ["translated_subs"],
    }
    if po_token:
        extractor_args["po_token"] = [f"web+{po_token}"]
    opts = {
        "cookiefile": cookie_file,
        "quiet": True,
        "noplaylist": True,
        "proxy": get_random_proxy(),
        "extractor_args": {"youtube": extractor_args},
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
        "sleep_interval": 1,
        "sleep_interval_requests": 1,
    }
    if extra:
        opts.update(extra)
    return opts


def extract_info_with_fallback(url, cookie_file, extra=None):
    """Android try karo, fail ho to web+cookies"""
    try:
        with yt_dlp.YoutubeDL(opts_android(extra)) as ydl:
            return ydl.extract_info(url, download=extra is not None and "outtmpl" in (extra or {}))
    except Exception as e1:
        err = str(e1)
        if "not available" in err.lower() or "format" in err.lower() or "SABR" in err:
            with yt_dlp.YoutubeDL(opts_web(cookie_file, extra)) as ydl:
                return ydl.extract_info(url, download=extra is not None and "outtmpl" in (extra or {}))
        raise


@app.route("/")
def index():
    return jsonify({
        "name": "YouTube Downloader API",
        "version": "3.4.0",
        "strategy": "android (no SABR) → web_creator+cookies fallback",
        "endpoints": {
            "GET /info?url=<youtube_url>":                        "Video info",
            "GET /qualities":                                      "Supported qualities",
            "GET /download?url=<youtube_url>&quality=<quality>":  "Download",
        },
        "supported_qualities": list(QUALITY_MAP.keys()),
    })


@app.route("/qualities")
def qualities():
    return jsonify({"supported_qualities": list(QUALITY_MAP.keys()), "descriptions": QUALITY_LABELS})


@app.route("/info")
def info():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url parameter zaroor chahiye"}), 400

    norm_url    = normalize_url(url)
    cookie_file = json_cookies_to_netscape(COOKIES_FILE)
    try:
        # info fetch — download=False, so extra=None
        try:
            with yt_dlp.YoutubeDL(opts_android()) as ydl:
                info_dict = ydl.extract_info(norm_url, download=False)
        except Exception:
            with yt_dlp.YoutubeDL(opts_web(cookie_file)) as ydl:
                info_dict = ydl.extract_info(norm_url, download=False)

        duration = info_dict.get("duration")
        seen = set()
        resolutions = []
        for fmt in info_dict.get("formats", []):
            h = fmt.get("height")
            if h and h not in seen:
                seen.add(h)
                resolutions.append({"height": h, "label": f"{h}p", "api_quality": str(h)})
        resolutions.sort(key=lambda x: x["height"], reverse=True)

        return jsonify({
            "title":                 info_dict.get("title", "Unknown"),
            "duration_seconds":      duration,
            "author":                info_dict.get("uploader") or info_dict.get("channel", "Unknown"),
            "views":                 info_dict.get("view_count"),
            "thumbnail_url":         info_dict.get("thumbnail", ""),
            "is_short":              "/shorts/" in url or bool(duration and duration <= 60),
            "available_resolutions": resolutions,
            "audio_available":       any(
                fmt.get("acodec", "none") != "none" and fmt.get("vcodec", "none") == "none"
                for fmt in info_dict.get("formats", [])
            ),
            "download_links": {q: f"/download?url={url}&quality={q}" for q in ["1080","720","480","360","audio"]},
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try: os.unlink(cookie_file)
        except Exception: pass


@app.route("/download")
def download():
    url     = request.args.get("url", "").strip()
    quality = request.args.get("quality", "720").strip().lower().replace("p", "")

    if not url:
        return jsonify({"error": "url parameter zaroor chahiye"}), 400
    if quality not in QUALITY_MAP:
        return jsonify({"error": f"Quality '{quality}' nahi hai", "supported": list(QUALITY_MAP.keys())}), 400

    norm_url    = normalize_url(url)
    output_dir  = tempfile.mkdtemp(dir=TEMP_DIR)
    cookie_file = json_cookies_to_netscape(COOKIES_FILE)

    try:
        output_template = os.path.join(output_dir, "%(title)s.%(ext)s")

        if quality == "audio":
            extra = {
                "format": "bestaudio/best",
                "outtmpl": output_template,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
            }
            extra_web = extra
        else:
            h = QUALITY_MAP[quality]
            # Android ke liye: combined format (Shorts mein separate streams nahi hote)
            fmt_android = (
                f"best[height<={h}]/best" if h else "best"
            )
            # Web fallback ke liye: merge approach
            fmt_web = (
                f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/bestvideo+bestaudio/best"
                if h else "bestvideo+bestaudio/best"
            )
            extra = {
                "format": fmt_android,
                "outtmpl": output_template,
            }
            extra_web = {
                "format": fmt_web,
                "outtmpl": output_template,
                "merge_output_format": "mp4",
            }

        video_title = "video"

        # Pass 1: Android — Shorts ke liye best (combined format)
        try:
            ydl_opts = opts_android(extra)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(norm_url, download=True)
                if info_dict:
                    video_title = info_dict.get("title", video_title)
        except Exception:
            # Pass 2: Web + cookies — merge format
            shutil.rmtree(output_dir, ignore_errors=True)
            output_dir = tempfile.mkdtemp(dir=TEMP_DIR)
            fallback_extra = extra_web if quality != "audio" else extra
            fallback_extra["outtmpl"] = os.path.join(output_dir, "%(title)s.%(ext)s")
            ydl_opts = opts_web(cookie_file, fallback_extra)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(norm_url, download=True)
                if info_dict:
                    video_title = info_dict.get("title", video_title)

        files = [f for f in os.listdir(output_dir) if not f.endswith(('.part', '.ytdl'))]
        if not files:
            return jsonify({"error": "Download failed — koi file nahi bani"}), 500

        filepath     = os.path.join(output_dir, files[0])
        safe_title   = sanitize(video_title)
        filename     = f"{safe_title}.mp3" if quality == "audio" else f"{safe_title}_{quality}p.mp4"
        content_type = "audio/mpeg" if quality == "audio" else "video/mp4"
        filesize     = os.path.getsize(filepath)

        def stream_and_cleanup():
            try:
                with open(filepath, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk: break
                        yield chunk
            finally:
                def cleanup():
                    try: shutil.rmtree(output_dir, ignore_errors=True)
                    except: pass
                    try: os.unlink(cookie_file)
                    except: pass
                threading.Thread(target=cleanup, daemon=True).start()

        ascii_fn = sanitize(filename).encode("ascii", "ignore").decode("ascii")
        return Response(stream_and_cleanup(), headers={
            "Content-Disposition": f'attachment; filename="{ascii_fn}"',
            "Content-Type":        content_type,
            "Content-Length":      str(filesize),
            "X-Video-Quality":     quality,
            "X-Video-Title":       safe_title.encode("ascii","ignore").decode("ascii")[:100],
        }, status=200)

    except Exception as e:
        shutil.rmtree(output_dir, ignore_errors=True)
        try: os.unlink(cookie_file)
        except: pass
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"\n{'='*60}")
    print(f"  YouTube Downloader API v3.4")
    print(f"  Strategy: Android → Web+Cookies fallback")
    print(f"  http://localhost:{port}/")
    print(f"{'='*60}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
