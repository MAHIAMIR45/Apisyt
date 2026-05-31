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
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, dir=TEMP_DIR)
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
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
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
        "status": "Running Smoothly",
        "supported_qualities": list(QUALITY_MAP.keys()),
    })

@app.route("/info")
def info():
    url = request.args.get("url", "").strip()
    if not url: return jsonify({"error": "url parameter zaroor chahiye"}), 400

    norm_url = normalize_url(url)
    cookie_file = json_cookies_to_netscape(COOKIES_FILE)

    info_dict, err = None, "Unknown error"
    
    # Strategy 1: Android Client (Bina cookies ke temporary check)
    try:
        opts = get_ytdlp_opts(None, extra={"extractor_args": android_extractor_args()})
        with yt_dlp.YoutubeDL(opts) as ydl:
            info_dict = ydl.extract_info(norm_url, download=False)
    except Exception as e:
        err = str(e)

    # Strategy 2: Web Client (Cookies ke sath fallback)
    if not info_dict and cookie_file:
        try:
            opts = get_ytdlp_opts(cookie_file, extra={"extractor_args": web_extractor_args()})
            with yt_dlp.YoutubeDL(opts) as ydl:
                info_dict = ydl.extract_info(norm_url, download=False)
        except Exception as e:
            err = str(e)

    if cookie_file and os.path.exists(cookie_file):
        try: os.unlink(cookie_file)
        except: pass

    if not info_dict:
        return jsonify({"error": f"Failed to get info: {err}"}), 500

    return jsonify({
        "title": info_dict.get("title", "Unknown"),
        "author": info_dict.get("uploader", "Unknown"),
        "duration": info_dict.get("duration"),
        "thumbnail": info_dict.get("thumbnail", ""),
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
        # Flexible Fallbacks: Agar alag video+audio na miley toh single standard format auto-fetch ho jaye
        format_spec = f"bestvideo[height<={th}][ext=mp4]+bestaudio[ext=m4a]/best[height<={th}][ext=mp4]/bestvideo[height<={th}]+bestaudio/best" if th else "bestvideo+bestaudio/best"
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

    # Try 1: Android Client download
    try:
        info_dict = run_download(norm_url, quality, output_dir, None, android_extractor_args())
    except Exception as e:
        err_msg = f"Android Client Error: {str(e)}"

    # Try 2: Web Client download (with cookies fallback)
    if not info_dict and cookie_file:
        try:
            info_dict = run_download(norm_url, quality, output_dir, cookie_file, web_extractor_args())
        except Exception as e:
            err_msg += f" | Web Client Error: {str(e)}"

    if cookie_file and os.path.exists(cookie_file):
        try: os.unlink(cookie_file)
        except: pass

    files = os.listdir(output_dir) if os.path.exists(output_dir) else []
    
    if not info_dict or not files:
        shutil.rmtree(output_dir, ignore_errors=True)
        return jsonify({
            "error": "Download failed.",
            "details": err_msg if err_msg else "No files generated."
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
                      
