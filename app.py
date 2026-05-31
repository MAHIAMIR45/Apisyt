import os
import re
import json
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
    if not os.path.exists(json_path):
        return None
    try:
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.txt', delete=False, dir=TEMP_DIR
        )
        tmp.write("# Netscape HTTP Cookie File\n\n")
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
        tmp.close()
        return tmp.name
    except Exception:
        return None


def get_ytdlp_opts(cookie_file: str = None, extra: dict = None) -> dict:
    opts = {
        "quiet": True,
        "noplaylist": True,
        "nocheckcertificate": True,       
        "legacyserverconnect": True,      
        "socket_timeout": 30,             
        "retries": 10,                    
        "extractor_retries": 5,
        "impersonate": "chrome",          # Bot block bypass setting
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
    }
    if cookie_file:
        opts["cookiefile"] = cookie_file
    if extra:
        opts.update(extra)
    return opts


def android_extractor_args():
    return {"youtube": {"player_client": ["android"], "skip": []}}


def web_extractor_args():
    return {"youtube": {"player_client": ["web"], "skip": []}}


@app.route("/")
def index():
    return jsonify({
        "name": "YouTube Downloader API",
        "version": "3.1.5",
        "description": "YouTube videos aur shorts download karein bina errors ke",
        "supported_qualities": list(QUALITY_MAP.keys()),
    })


@app.route("/qualities")
def qualities():
    return jsonify({"supported_qualities": list(QUALITY_MAP.keys())})


def extract_info_internal(norm_url, cookie_file, ea):
    try:
        opts = get_ytdlp_opts(cookie_file, extra={"extractor_args": ea})
        with yt_dlp.YoutubeDL(opts) as ydl:
            info_dict = ydl.extract_info(norm_url, download=False)
            
        formats = info_dict.get("formats", [])
        real_formats = [f for f in formats if f.get("vcodec", "none") != "none" or f.get("acodec", "none") != "none"]
        if not real_formats:
            return None, "No formats found"
            
        return info_dict, None
    except Exception as e:
        return None, str(e)


@app.route("/info")
def info():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url parameter zaroor chahiye"}), 400

    norm_url = normalize_url(url)
    cookie_file = json_cookies_to_netscape(COOKIES_FILE)

    # Strategy 1: Android client
    info_dict, err = extract_info_internal(norm_url, None, android_extractor_args())

    # Strategy 2: Web client + Cookies
    if not info_dict and cookie_file:
        info_dict, err = extract_info_internal(norm_url, cookie_file, web_extractor_args())

    if cookie_file and os.path.exists(cookie_file):
        try: os.unlink(cookie_file)
        except: pass

    if not info_dict:
        return jsonify({"error": f"Failed to get info. Reason: {err}"}), 500

    title = info_dict.get("title", "Unknown")
    duration = info_dict.get("duration")
    author = info_dict.get("uploader") or info_dict.get("channel", "Unknown")
    views = info_dict.get("view_count")
    thumbnail = info_dict.get("thumbnail", "")

    formats = info_dict.get("formats", [])
    seen_heights = set()
    available_resolutions = []
    for fmt in formats:
        h = fmt.get("height")
        vcodec = fmt.get("vcodec", "none")
        if h and h not in seen_heights and vcodec != "none":
            seen_heights.add(h)
            available_resolutions.append({"height": h, "label": f"{h}p", "api_quality": str(h)})
    available_resolutions.sort(key=lambda x: x["height"], reverse=True)

    has_audio = any(fmt.get("acodec", "none") != "none" for fmt in formats)
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
        "download_links": {q: f"/download?url={url}&quality={q}" for q in ["1080", "720", "480", "360", "audio"]},
    })


def run_download(norm_url, quality, output_dir, cookie, ea):
    output_template = os.path.join(output_dir, "%(title)s.%(ext)s")
    if quality == "audio":
        format_spec = "bestaudio[ext=m4a]/bestaudio/best"
        ydl_opts = get_ytdlp_opts(cookie, extra={
            "format": format_spec, "outtmpl": output_template, "extractor_args": ea,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
        })
    else:
        th = QUALITY_MAP[quality]
        format_spec = f"bestvideo[height<={th}][ext=mp4]+bestaudio[ext=m4a]/best[height<={th}][ext=mp4]/best" if th else "bestvideo+bestaudio/best"
        ydl_opts = get_ytdlp_opts(cookie, extra={
            "format": format_spec, "outtmpl": output_template, "merge_output_format": "mp4", "extractor_args": ea,
        })

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(norm_url, download=True)


@app.route("/download")
def download():
    url = request.args.get("url", "").strip()
    quality = request.args.get("quality", "720").strip()

    if not url or quality not in QUALITY_MAP:
        return jsonify({"error": "Invalid URL or Quality"}), 400

    norm_url = normalize_url(url)
    output_dir = tempfile.mkdtemp(dir=TEMP_DIR)
    cookie_file = json_cookies_to_netscape(COOKIES_FILE)

    info_dict, err_msg = None, ""

    # Try Strategy 1
    try:
        info_dict = run_download(norm_url, quality, output_dir, None, android_extractor_args())
    except Exception as e:
        err_msg = f"Android Client Error: {str(e)}"

    # Try Strategy 2 if Strategy 1 fails
    if not info_dict and cookie_file:
        try:
            info_dict = run_download(norm_url, quality, output_dir, cookie_file, web_extractor_args())
        except Exception as e:
            err_msg += f" | Web Client Error: {str(e)}"

    if cookie_file and os.path.exists(cookie_file):
        try: os.unlink(cookie_file)
        except: pass

    files = os.listdir(output_dir) if os.path.exists(output_dir) else []
    
    # Agar files array khali hai toh iska matlab download crash hua hai
    if not info_dict or not files:
        shutil.rmtree(output_dir, ignore_errors=True)
        # Yahan clear message browser par dikhega
        return jsonify({
            "error": "Download failed. Video aur Audio merge nahi ho saki.",
            "details": err_msg if err_msg else "No output files created. Check if FFmpeg is installed on Render."
        }), 500

    filepath = os.path.join(output_dir, files[0])
    video_title = info_dict.get("title", "video")
    filename = f"{sanitize(video_title)}.mp3" if quality == "audio" else f"{sanitize(video_title)}_{quality}p.mp4"
    
    def stream_and_cleanup():
        try:
            with open(filepath, "rb") as f:
                while chunk := f.read(65536): yield chunk
        finally:
            threading.Thread(target=lambda: shutil.rmtree(output_dir, ignore_errors=True), daemon=True).start()

    headers = {
        "Content-Disposition": f'attachment; filename="{sanitize(filename).encode("ascii", "ignore").decode("ascii")}"',
        "Content-Type": "audio/mpeg" if quality == "audio" else "video/mp4",
        "Content-Length": str(os.path.getsize(filepath)),
    }
    return Response(stream_and_cleanup(), headers=headers)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
