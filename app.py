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

# ─── Webshare Proxy List (rotating) ───────────────────────────────────────────
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

def get_random_proxy() -> str:
    return random.choice(PROXIES)

# ──────────────────────────────────────────────────────────────────────────────

QUALITY_MAP = {
    "2160": 2160,
    "1440": 1440,
    "1080": 1080,
    "720": 720,
    "480": 480,
    "360": 360,
    "240": 240,
    "144": 144,
    "best": None,
    "audio": None,
}

QUALITY_LABELS = {
    "2160": "4K Ultra HD",
    "1440": "2K Quad HD",
    "1080": "Full HD",
    "720": "HD",
    "480": "SD",
    "360": "Low",
    "240": "Very Low",
    "144": "Minimum",
    "best": "Best Available",
    "audio": "Audio Only (MP3)",
}


def sanitize(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    return name[:180].strip()


def normalize_url(url: str) -> str:
    url = url.strip()
    short_match = re.search(r"shorts/([A-Za-z0-9_-]{11})", url)
    if short_match:
        return f"https://www.youtube.com/watch?v={short_match.group(1)}"
    watch_match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    if watch_match:
        return f"https://www.youtube.com/watch?v={watch_match.group(1)}"
    return url


def json_cookies_to_netscape(json_path: str) -> str:
    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.txt', delete=False, dir=TEMP_DIR
    )
    tmp.write("# Netscape HTTP Cookie File\n\n")
    try:
        with open(json_path) as f:
            cookies = json.load(f)
        for c in cookies:
            domain   = c.get('domain', '.youtube.com')
            flag     = 'FALSE' if c.get('hostOnly') else 'TRUE'
            path     = c.get('path', '/')
            secure   = 'TRUE' if c.get('secure') else 'FALSE'
            expires  = int(c.get('expirationDate', 0))
            name     = c.get('name', '')
            value    = c.get('value', '')
            tmp.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
    except Exception:
        pass
    tmp.close()
    return tmp.name


def get_ytdlp_opts(cookie_file: str, extra: dict = None) -> dict:
    opts = {
        "cookiefile": cookie_file,
        "quiet": True,
        "noplaylist": True,
        "proxy": get_random_proxy(),          # har request pe random proxy
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web", "ios"],
                "skip": ["translated_subs"],
            }
        },
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/116.0.0.0 Mobile Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
        "sleep_interval_requests": 1,
        "sleep_interval": 1,
        "max_sleep_interval": 3,
    }
    if extra:
        opts.update(extra)
    return opts


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return jsonify({
        "name": "YouTube Downloader API",
        "version": "3.3.0",
        "proxy": "rotating (10 proxies)",
        "endpoints": {
            "GET /info?url=<youtube_url>":                       "Video info",
            "GET /qualities":                                     "Supported qualities",
            "GET /download?url=<youtube_url>&quality=<quality>": "Video download",
        },
        "supported_qualities": list(QUALITY_MAP.keys()),
        "quality_descriptions": QUALITY_LABELS,
    })


@app.route("/qualities")
def qualities():
    return jsonify({
        "supported_qualities": list(QUALITY_MAP.keys()),
        "descriptions": QUALITY_LABELS,
    })


@app.route("/info")
def info():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url parameter zaroor chahiye"}), 400

    norm_url    = normalize_url(url)
    cookie_file = json_cookies_to_netscape(COOKIES_FILE)
    try:
        with yt_dlp.YoutubeDL(get_ytdlp_opts(cookie_file)) as ydl:
            info_dict = ydl.extract_info(norm_url, download=False)

        duration = info_dict.get("duration")
        seen_heights = set()
        available_resolutions = []
        for fmt in info_dict.get("formats", []):
            h = fmt.get("height")
            if h and h not in seen_heights:
                seen_heights.add(h)
                available_resolutions.append({"height": h, "label": f"{h}p", "api_quality": str(h)})
        available_resolutions.sort(key=lambda x: x["height"], reverse=True)

        has_audio = any(
            fmt.get("acodec", "none") != "none" and fmt.get("vcodec", "none") == "none"
            for fmt in info_dict.get("formats", [])
        )

        return jsonify({
            "title":                info_dict.get("title", "Unknown"),
            "duration_seconds":     duration,
            "author":               info_dict.get("uploader") or info_dict.get("channel", "Unknown"),
            "views":                info_dict.get("view_count"),
            "thumbnail_url":        info_dict.get("thumbnail", ""),
            "is_short":             "/shorts/" in url or (duration is not None and duration <= 60),
            "available_resolutions": available_resolutions,
            "audio_available":      has_audio,
            "api_qualities":        list(QUALITY_MAP.keys()),
            "download_links": {
                q: f"/download?url={url}&quality={q}"
                for q in ["1080", "720", "480", "360", "audio"]
            },
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            os.unlink(cookie_file)
        except Exception:
            pass


@app.route("/download")
def download():
    url     = request.args.get("url", "").strip()
    quality = request.args.get("quality", "720").strip()

    if not url:
        return jsonify({"error": "url parameter zaroor chahiye"}), 400
    if quality not in QUALITY_MAP:
        return jsonify({
            "error": f"Quality '{quality}' supported nahi hai",
            "supported_qualities": list(QUALITY_MAP.keys()),
        }), 400

    norm_url   = normalize_url(url)
    output_dir = tempfile.mkdtemp(dir=TEMP_DIR)
    cookie_file = json_cookies_to_netscape(COOKIES_FILE)

    try:
        output_template = os.path.join(output_dir, "%(title)s.%(ext)s")

        if quality == "audio":
            ydl_opts = get_ytdlp_opts(cookie_file, {
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "outtmpl": output_template,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            target_height = QUALITY_MAP[quality]
            # Shorts aur normal videos dono ke liye reliable fallback chain
            if target_height is None:
                fmt = "bestvideo+bestaudio/best"
            else:
                fmt = (
                    f"bestvideo[height<={target_height}]+bestaudio"
                    f"/best[height<={target_height}]"
                    f"/bestvideo+bestaudio"   # height match na ho to best available lo
                    f"/best"                  # last resort — koi bhi format
                )
            ydl_opts = get_ytdlp_opts(cookie_file, {
                "format": fmt,
                "outtmpl": output_template,
                "merge_output_format": "mp4",
                # mp4 prefer karo lekin zaroor nahi
                "format_sort": ["res", "ext:mp4:m4a", "size"],
            })

        video_title = "video"

        def progress_hook(d):
            nonlocal video_title
            if d.get("info_dict", {}).get("title"):
                video_title = d["info_dict"]["title"]

        ydl_opts["progress_hooks"] = [progress_hook]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(norm_url, download=True)
            if info_dict:
                video_title = info_dict.get("title", video_title)

        files = [
            f for f in os.listdir(output_dir)
            if not f.endswith('.part') and not f.endswith('.ytdl')
        ]
        if not files:
            return jsonify({"error": "Download failed — koi file nahi bani"}), 500

        filepath = os.path.join(output_dir, files[0])
        safe_title = sanitize(video_title)

        if quality == "audio":
            filename     = f"{safe_title}.mp3"
            content_type = "audio/mpeg"
        else:
            filename     = f"{safe_title}_{quality}p.mp4"
            content_type = "video/mp4"

        filesize = os.path.getsize(filepath)

        def stream_and_cleanup():
            try:
                with open(filepath, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        yield chunk
            finally:
                def cleanup():
                    try: shutil.rmtree(output_dir, ignore_errors=True)
                    except Exception: pass
                    try: os.unlink(cookie_file)
                    except Exception: pass
                threading.Thread(target=cleanup, daemon=True).start()

        ascii_title    = safe_title.encode("ascii", "ignore").decode("ascii")[:100]
        ascii_filename = sanitize(filename).encode("ascii", "ignore").decode("ascii")

        return Response(
            stream_and_cleanup(),
            headers={
                "Content-Disposition": f'attachment; filename="{ascii_filename}"',
                "Content-Type":        content_type,
                "Content-Length":      str(filesize),
                "X-Video-Quality":     quality,
                "X-Video-Title":       ascii_title,
            },
            status=200,
        )

    except Exception as e:
        shutil.rmtree(output_dir, ignore_errors=True)
        try: os.unlink(cookie_file)
        except Exception: pass
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"\n{'='*55}")
    print(f"  YouTube Downloader API v3.3  —  10 rotating proxies")
    print(f"  http://localhost:{port}/")
    print(f"{'='*55}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
