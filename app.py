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

def sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)[:180].strip()

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

def build_format_string(quality: str) -> dict:
    """Har quality ke liye sahi format string — proper size difference"""
    if quality == "audio":
        return {
            "format": "bestaudio[abr>=128]/bestaudio/best",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        }
    h = QUALITY_MAP.get(quality)
    if h is None:
        # best quality
        return {"format": "bestvideo+bestaudio/best", "merge_output_format": "mp4"}
    # Android combined format — exact height match prefer karo
    fmt_android = (
        f"best[height={h}]"
        f"/best[height<={h}][height>={max(h-120,144)}]"
        f"/best[height<={h}]"
        f"/best"
    )
    # Web merge format — separate streams
    fmt_web = (
        f"bestvideo[height={h}]+bestaudio"
        f"/bestvideo[height<={h}][height>={max(h-120,144)}]+bestaudio"
        f"/bestvideo[height<={h}]+bestaudio"
        f"/best[height<={h}]"
        f"/best"
    )
    return {"fmt_android": fmt_android, "fmt_web": fmt_web}

def base_opts(proxy: str) -> dict:
    return {
        "quiet": True,
        "no_warnings": False,
        "noplaylist": True,
        "proxy": proxy,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "sleep_interval": 1,
        "max_sleep_interval": 3,
    }

def opts_android(proxy: str, fmt: str, outtmpl: str, extra_pp=None) -> dict:
    opts = base_opts(proxy)
    opts.update({
        "format": fmt,
        "outtmpl": outtmpl,
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
                # GVS PO Token missing warning bypass
                "formats": ["missing_pot"],
            }
        },
        "http_headers": {
            "User-Agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 13; en_US) gzip",
        },
    })
    if extra_pp:
        opts["postprocessors"] = extra_pp
    return opts

def opts_web(proxy: str, cookie_file: str, fmt: str, outtmpl: str, extra_pp=None) -> dict:
    opts = base_opts(proxy)
    opts.update({
        "format": fmt,
        "outtmpl": outtmpl,
        "cookiefile": cookie_file,
        "merge_output_format": "mp4",
        "extractor_args": {
            "youtube": {
                "player_client": ["web_creator", "web"],
                "skip": ["translated_subs"],
                # PO token nahi — invalid tha, hata diya
            }
        },
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    })
    if extra_pp:
        opts["postprocessors"] = extra_pp
    return opts

def download_video(norm_url: str, quality: str, output_dir: str, cookie_file: str):
    """Android try karo, fail ho to web+cookies. Returns video_title."""
    outtmpl   = os.path.join(output_dir, "%(title)s.%(ext)s")
    fmt_info  = build_format_string(quality)
    proxy     = get_random_proxy()
    video_title = "video"
    is_audio  = (quality == "audio")

    if is_audio:
        fmt       = fmt_info["format"]
        extra_pp  = fmt_info.get("postprocessors")
    else:
        fmt_android = fmt_info.get("fmt_android", "best")
        fmt_web     = fmt_info.get("fmt_web", "bestvideo+bestaudio/best")

    # ── Pass 1: Android ──────────────────────────────────────────────────────
    try:
        fmt = fmt_android if not is_audio else fmt_info["format"]
        ydl_opts = opts_android(proxy, fmt, outtmpl, extra_pp=None if not is_audio else fmt_info.get("postprocessors"))
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(norm_url, download=True)
            if info:
                video_title = info.get("title", video_title)
        return video_title

    except Exception as e1:
        err1 = str(e1)

    # ── Pass 2: Web + cookies ─────────────────────────────────────────────────
    shutil.rmtree(output_dir, ignore_errors=True)
    os.makedirs(output_dir, exist_ok=True)
    outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")

    try:
        fmt = fmt_web if not is_audio else fmt_info["format"]
        ydl_opts = opts_web(proxy, cookie_file, fmt, outtmpl,
                            extra_pp=fmt_info.get("postprocessors") if is_audio else None)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(norm_url, download=True)
            if info:
                video_title = info.get("title", video_title)
        return video_title

    except Exception as e2:
        # Pass 3: Alag proxy se retry
        proxy2 = get_random_proxy()
        shutil.rmtree(output_dir, ignore_errors=True)
        os.makedirs(output_dir, exist_ok=True)
        outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")
        fmt = fmt_web if not is_audio else fmt_info["format"]
        ydl_opts = opts_web(proxy2, cookie_file, fmt, outtmpl,
                            extra_pp=fmt_info.get("postprocessors") if is_audio else None)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(norm_url, download=True)
            if info:
                video_title = info.get("title", video_title)
        return video_title


@app.route("/")
def index():
    return jsonify({
        "name": "YouTube Downloader API",
        "version": "4.0.0",
        "strategy": "Android → Web+Cookies → Retry different proxy",
        "endpoints": {
            "/info?url=": "Video info + available qualities",
            "/download?url=&quality=": "Download video/audio",
            "/qualities": "All supported qualities",
        },
        "qualities": list(QUALITY_MAP.keys()),
        "examples": {
            "720p":  "/download?url=https://youtu.be/VIDEO_ID&quality=720",
            "360p":  "/download?url=https://youtu.be/VIDEO_ID&quality=360",
            "audio": "/download?url=https://youtu.be/VIDEO_ID&quality=audio",
        }
    })


@app.route("/qualities")
def qualities():
    return jsonify({"qualities": list(QUALITY_MAP.keys())})


@app.route("/info")
def info():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url parameter chahiye"}), 400

    norm_url    = normalize_url(url)
    cookie_file = json_cookies_to_netscape(COOKIES_FILE)
    proxy       = get_random_proxy()

    try:
        # Android se info try karo
        try:
            with yt_dlp.YoutubeDL({
                **base_opts(proxy),
                "extractor_args": {"youtube": {"player_client": ["android"], "formats": ["missing_pot"]}},
                "http_headers": {"User-Agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 13; en_US) gzip"},
            }) as ydl:
                info_dict = ydl.extract_info(norm_url, download=False)
        except Exception:
            with yt_dlp.YoutubeDL({
                **base_opts(proxy),
                "cookiefile": cookie_file,
                "extractor_args": {"youtube": {"player_client": ["web_creator", "web"], "skip": ["translated_subs"]}},
                "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            }) as ydl:
                info_dict = ydl.extract_info(norm_url, download=False)

        duration = info_dict.get("duration")
        seen = set()
        resolutions = []
        for fmt in info_dict.get("formats", []):
            h = fmt.get("height")
            if h and h not in seen:
                seen.add(h)
                resolutions.append({"height": h, "label": f"{h}p"})
        resolutions.sort(key=lambda x: x["height"], reverse=True)

        return jsonify({
            "title":      info_dict.get("title", "Unknown"),
            "duration":   duration,
            "author":     info_dict.get("uploader") or info_dict.get("channel", "Unknown"),
            "views":      info_dict.get("view_count"),
            "thumbnail":  info_dict.get("thumbnail", ""),
            "is_short":   "/shorts/" in url or bool(duration and duration <= 60),
            "resolutions": resolutions,
            "download_links": {
                q: f"/download?url={url}&quality={q}"
                for q in ["1080", "720", "480", "360", "audio"]
            },
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try: os.unlink(cookie_file)
        except: pass


@app.route("/download")
def download():
    url     = request.args.get("url", "").strip()
    # 720p / 720 / 720P — sab accept
    quality = request.args.get("quality", "720").strip().lower().rstrip("p")

    if not url:
        return jsonify({"error": "url parameter chahiye"}), 400
    if quality not in QUALITY_MAP:
        return jsonify({"error": f"Quality '{quality}' nahi hai", "valid": list(QUALITY_MAP.keys())}), 400

    norm_url    = normalize_url(url)
    output_dir  = tempfile.mkdtemp(dir=TEMP_DIR)
    cookie_file = json_cookies_to_netscape(COOKIES_FILE)

    try:
        video_title = download_video(norm_url, quality, output_dir, cookie_file)

        files = [f for f in os.listdir(output_dir) if not f.endswith(('.part', '.ytdl'))]
        if not files:
            return jsonify({"error": "File nahi bani — download failed"}), 500

        filepath     = os.path.join(output_dir, files[0])
        safe_title   = sanitize(video_title)
        is_audio     = (quality == "audio")
        filename     = f"{safe_title}.mp3" if is_audio else f"{safe_title}_{quality}p.mp4"
        content_type = "audio/mpeg" if is_audio else "video/mp4"
        filesize     = os.path.getsize(filepath)

        def stream_and_cleanup():
            try:
                with open(filepath, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk: break
                        yield chunk
            finally:
                def _clean():
                    try: shutil.rmtree(output_dir, ignore_errors=True)
                    except: pass
                    try: os.unlink(cookie_file)
                    except: pass
                threading.Thread(target=_clean, daemon=True).start()

        ascii_fn = sanitize(filename).encode("ascii", "ignore").decode("ascii")
        return Response(stream_and_cleanup(), headers={
            "Content-Disposition": f'attachment; filename="{ascii_fn}"',
            "Content-Type":        content_type,
            "Content-Length":      str(filesize),
            "X-Video-Quality":     quality,
        }, status=200)

    except Exception as e:
        shutil.rmtree(output_dir, ignore_errors=True)
        try: os.unlink(cookie_file)
        except: pass
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"\n{'='*55}")
    print(f"  YouTube Downloader API v4.0")
    print(f"  http://localhost:{port}/")
    print(f"  Strategy: Android → Web+Cookies → Retry")
    print(f"{'='*55}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
