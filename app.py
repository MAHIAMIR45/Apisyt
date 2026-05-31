import os
import re
import json
import shutil
import tempfile
import threading
import subprocess
from flask import Flask, request, Response, jsonify
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp_downloads")
COOKIES_FILE = os.path.join(BASE_DIR, "cookies.json")
os.makedirs(TEMP_DIR, exist_ok=True)

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
    """Convert Cookie Editor JSON format to Netscape cookie file format."""
    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.txt', delete=False, dir=TEMP_DIR
    )
    tmp.write("# Netscape HTTP Cookie File\n\n")
    try:
        with open(json_path) as f:
            cookies = json.load(f)
        for c in cookies:
            domain = c.get('domain', '.youtube.com')
            flag = 'FALSE' if c.get('hostOnly') else 'TRUE'
            path = c.get('path', '/')
            secure = 'TRUE' if c.get('secure') else 'FALSE'
            expires = int(c.get('expirationDate', 0))
            name = c.get('name', '')
            value = c.get('value', '')
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
        # FIX #1: js_runtimes hata diya — invalid option tha, crash ka asli wajah
        # Render ke liye web client use karo jo bina Node.js ke kaam karta hai
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "android"],
            }
        },
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    }
    if extra:
        opts.update(extra)
    return opts


@app.route("/")
def index():
    return jsonify({
        "name": "YouTube Downloader API",
        "version": "3.1.0",
        "description": "YouTube videos (Shorts + long) download karo — koi bhi quality",
        "endpoints": {
            "GET /info?url=<youtube_url>": "Video info aur available qualities dekho",
            "GET /qualities": "Saari supported qualities ki list",
            "GET /download?url=<youtube_url>&quality=<quality>": "Video download karo",
        },
        "supported_qualities": list(QUALITY_MAP.keys()),
        "quality_descriptions": QUALITY_LABELS,
        "examples": {
            "info": "/info?url=https://youtube.com/shorts/Ibw50eCG6bQ",
            "download_720p": "/download?url=https://youtube.com/shorts/Ibw50eCG6bQ&quality=720",
            "download_1080p": "/download?url=https://youtu.be/jNQXAC9IVRw&quality=1080",
            "download_audio": "/download?url=https://youtu.be/jNQXAC9IVRw&quality=audio",
        },
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
        return jsonify({
            "error": "url parameter zaroor chahiye",
            "example": "/info?url=https://youtube.com/shorts/Ibw50eCG6bQ",
        }), 400

    norm_url = normalize_url(url)
    cookie_file = json_cookies_to_netscape(COOKIES_FILE)
    try:
        opts = get_ytdlp_opts(cookie_file)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info_dict = ydl.extract_info(norm_url, download=False)

        title = info_dict.get("title", "Unknown")
        duration = info_dict.get("duration")
        author = info_dict.get("uploader") or info_dict.get("channel", "Unknown")
        views = info_dict.get("view_count")
        thumbnail = info_dict.get("thumbnail", "")

        seen_heights = set()
        available_resolutions = []
        for fmt in info_dict.get("formats", []):
            h = fmt.get("height")
            if h and h not in seen_heights:
                seen_heights.add(h)
                available_resolutions.append({
                    "height": h,
                    "label": f"{h}p",
                    "api_quality": str(h),
                })
        available_resolutions.sort(key=lambda x: x["height"], reverse=True)

        has_audio = any(
            fmt.get("acodec", "none") != "none" and fmt.get("vcodec", "none") == "none"
            for fmt in info_dict.get("formats", [])
        )

        is_short = "/shorts/" in url or (duration is not None and duration <= 60)

        return jsonify({
            "title": title,
            "duration_seconds": duration,
            "author": author,
            "views": views,
            "thumbnail_url": thumbnail,
            "is_short": is_short,
            "available_resolutions": available_resolutions,
            "audio_available": has_audio,
            "api_qualities": list(QUALITY_MAP.keys()),
            "download_links": {
                q: f"/download?url={url}&quality={q}"
                for q in ["1080", "720", "480", "360", "audio"]
            },
        })

    except Exception as e:
        err = str(e)
        if "Private video" in err or "not available" in err.lower():
            return jsonify({"error": "Video unavailable ya private hai"}), 404
        return jsonify({"error": err}), 500
    finally:
        try:
            os.unlink(cookie_file)
        except Exception:
            pass


@app.route("/download")
def download():
    url = request.args.get("url", "").strip()
    quality = request.args.get("quality", "720").strip()

    if not url:
        return jsonify({
            "error": "url parameter zaroor chahiye",
            "example": "/download?url=https://youtube.com/shorts/Ibw50eCG6bQ&quality=720",
        }), 400

    if quality not in QUALITY_MAP:
        return jsonify({
            "error": f"Quality '{quality}' supported nahi hai",
            "supported_qualities": list(QUALITY_MAP.keys()),
            "descriptions": QUALITY_LABELS,
        }), 400

    norm_url = normalize_url(url)
    output_dir = tempfile.mkdtemp(dir=TEMP_DIR)
    cookie_file = json_cookies_to_netscape(COOKIES_FILE)

    try:
        output_template = os.path.join(output_dir, "%(title)s.%(ext)s")

        if quality == "audio":
            format_spec = "bestaudio[ext=m4a]/bestaudio/best"
            ydl_opts = get_ytdlp_opts(cookie_file, {
                "format": format_spec,
                "outtmpl": output_template,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            target_height = QUALITY_MAP[quality]
            if target_height is None:
                format_spec = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best"
            else:
                format_spec = (
                    f"bestvideo[height<={target_height}][ext=mp4]+bestaudio[ext=m4a]"
                    f"/bestvideo[height<={target_height}]+bestaudio"
                    f"/best[height<={target_height}][ext=mp4]"
                    f"/best[height<={target_height}]"
                    f"/bestvideo[ext=mp4]+bestaudio[ext=m4a]"
                    f"/best[ext=mp4]/best"
                )
            ydl_opts = get_ytdlp_opts(cookie_file, {
                "format": format_spec,
                "outtmpl": output_template,
                "merge_output_format": "mp4",
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

        # FIX #2: .part / .ytdl temp files filter karo — pehle galat file stream ho sakti thi
        files = [
            f for f in os.listdir(output_dir)
            if not f.endswith('.part') and not f.endswith('.ytdl')
        ]
        if not files:
            return jsonify({"error": "Download failed — koi file nahi bani"}), 500

        filepath = os.path.join(output_dir, files[0])

        if quality == "audio":
            safe_title = sanitize(video_title)
            filename = f"{safe_title}.mp3"
            content_type = "audio/mpeg"
        else:
            safe_title = sanitize(video_title)
            filename = f"{safe_title}_{quality}p.mp4"
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
                # FIX #3: cleanup dono cheezein — output_dir aur cookie_file
                def cleanup():
                    try:
                        shutil.rmtree(output_dir, ignore_errors=True)
                    except Exception:
                        pass
                    try:
                        os.unlink(cookie_file)
                    except Exception:
                        pass
                t = threading.Thread(target=cleanup, daemon=True)
                t.start()

        ascii_title = sanitize(video_title).encode("ascii", "ignore").decode("ascii")[:100]
        ascii_filename = sanitize(filename).encode("ascii", "ignore").decode("ascii")

        headers = {
            "Content-Disposition": f'attachment; filename="{ascii_filename}"',
            "Content-Type": content_type,
            "Content-Length": str(filesize),
            "X-Video-Quality": quality,
            "X-Video-Title": ascii_title,
        }

        return Response(stream_and_cleanup(), headers=headers, status=200)

    except Exception as e:
        shutil.rmtree(output_dir, ignore_errors=True)
        try:
            os.unlink(cookie_file)
        except Exception:
            pass
        err = str(e)
        if "Private video" in err or "not available" in err.lower():
            return jsonify({"error": "Video unavailable ya private hai"}), 404
        return jsonify({"error": err}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"\n{'='*55}")
    print(f"  YouTube Downloader API v3.1")
    print(f"  http://localhost:{port}/")
    print(f"{'='*55}")
    print(f"  Info:     /info?url=<youtube_url>")
    print(f"  Download: /download?url=<youtube_url>&quality=720")
    print(f"  Qualities: /qualities")
    print(f"{'='*55}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
