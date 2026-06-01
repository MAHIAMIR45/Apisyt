import os, re, json, random, shutil, tempfile, threading
from flask import Flask, request, Response, jsonify
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR     = os.path.join(BASE_DIR, "temp_downloads")
COOKIES_FILE = os.path.join(BASE_DIR, "cookies.json")
os.makedirs(TEMP_DIR, exist_ok=True)

_U = "gpxjaoxt"; _P = "trexu8zcabdr"
PROXIES = [
    f"http://{_U}:{_P}@38.154.203.95:5863",
    f"http://{_U}:{_P}@198.105.121.200:6462",
    f"http://{_U}:{_P}@64.137.96.74:6641",
    f"http://{_U}:{_P}@209.127.138.10:5784",
    f"http://{_U}:{_P}@38.154.185.97:6370",
    f"http://{_U}:{_P}@84.247.60.125:6095",
    f"http://{_U}:{_P}@142.111.67.146:5611",
    f"http://{_U}:{_P}@191.96.254.138:6185",
    f"http://{_U}:{_P}@31.58.9.4:6077",
    f"http://{_U}:{_P}@104.239.107.47:5699",
]
def rand_proxy(): return random.choice(PROXIES)

QUALITY_MAP = {
    "2160":2160,"1440":1440,"1080":1080,"720":720,
    "480":480,"360":360,"240":240,"144":144,
    "best":None,"audio":None,
}

def sanitize(s):
    return re.sub(r'[\\/*?:"<>|]', "_", s)[:180].strip()

def normalize_url(url):
    url = url.strip()
    m = re.search(r"shorts/([A-Za-z0-9_-]{11})", url)
    if m: return f"https://www.youtube.com/watch?v={m.group(1)}"
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    if m: return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url

def make_cookies(json_path):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, dir=TEMP_DIR)
    tmp.write("# Netscape HTTP Cookie File\n\n")
    try:
        for c in json.load(open(json_path)):
            tmp.write(
                f"{c.get('domain','.youtube.com')}\t"
                f"{'FALSE' if c.get('hostOnly') else 'TRUE'}\t"
                f"{c.get('path','/')}\t"
                f"{'TRUE' if c.get('secure') else 'FALSE'}\t"
                f"{int(c.get('expirationDate',0))}\t"
                f"{c.get('name','')}\t{c.get('value','')}\n"
            )
    except: pass
    tmp.close()
    return tmp.name

# ─── Format strings ────────────────────────────────────────────────────────────
# DASH/HLS skip — nsig crash avoid (memory issue on Render free tier)
# Audio: combined format se extract karo — DASH audio streams hati hain

def fmt_video(h):
    """h = height int ya None (best)"""
    if h is None:
        return "best[protocol!=dash][protocol!=m3u8]/best"
    return (
        f"best[height<={h}][protocol!=dash][protocol!=m3u8]"
        f"/best[height<={h}]"
        f"/best[protocol!=dash][protocol!=m3u8]"
        f"/best"
    )

# Audio: combined format download karo phir FFmpeg se extract — DASH nahi chahiye
FMT_AUDIO_COMBINED = (
    "best[protocol!=dash][protocol!=m3u8][ext=mp4]"
    "/best[protocol!=dash][protocol!=m3u8]"
    "/best"
)

# ─── yt-dlp opts ───────────────────────────────────────────────────────────────
BASE_OPTS = {
    "quiet":          True,
    "noplaylist":     True,
    "socket_timeout": 20,
    "retries":        2,
    "fragment_retries": 2,
    "concurrent_fragment_downloads": 1,
    "buffersize":     16384,
    "noprogress":     True,
}

ANDROID_EXTRACTOR = {
    "player_client": ["android"],
    "formats":       ["missing_pot"],
    "skip":          ["dash", "hls", "translated_subs"],
}

WEB_EXTRACTOR = {
    "player_client": ["web_creator", "web"],
    "skip":          ["dash", "hls", "translated_subs"],
}

def opts_android(proxy, fmt, outtmpl, postprocessors=None):
    o = {**BASE_OPTS,
         "format": fmt, "outtmpl": outtmpl, "proxy": proxy,
         "extractor_args": {"youtube": ANDROID_EXTRACTOR},
         "http_headers": {"User-Agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 13; en_US) gzip"},
    }
    if postprocessors: o["postprocessors"] = postprocessors
    return o

def opts_web(proxy, cookie_file, fmt, outtmpl, postprocessors=None):
    o = {**BASE_OPTS,
         "format": fmt, "outtmpl": outtmpl,
         "proxy": proxy, "cookiefile": cookie_file,
         "merge_output_format": "mp4",
         "extractor_args": {"youtube": WEB_EXTRACTOR},
         "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"},
    }
    if postprocessors: o["postprocessors"] = postprocessors
    return o

# ─── Download logic ────────────────────────────────────────────────────────────
def do_download(norm_url, quality, output_dir, cookie_file):
    is_audio = (quality == "audio")
    h        = QUALITY_MAP.get(quality)

    if is_audio:
        fmt = FMT_AUDIO_COMBINED
        pps = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else:
        fmt = fmt_video(h)
        pps = None

    outtmpl = os.path.join(output_dir, "%(title)s___%(height)s.%(ext)s")

    def clean_dir():
        for f in os.listdir(output_dir):
            try: os.unlink(os.path.join(output_dir, f))
            except: pass

    for attempt in range(3):
        proxy = rand_proxy()

        # Pass A: Android
        try:
            with yt_dlp.YoutubeDL(opts_android(proxy, fmt, outtmpl, pps)) as ydl:
                info = ydl.extract_info(norm_url, download=True)
                return info.get("title","video"), info.get("height") or info.get("width")
        except Exception:
            clean_dir()

        # Pass B: Web + cookies
        try:
            with yt_dlp.YoutubeDL(opts_web(proxy, cookie_file, fmt, outtmpl, pps)) as ydl:
                info = ydl.extract_info(norm_url, download=True)
                return info.get("title","video"), info.get("height") or info.get("width")
        except Exception:
            clean_dir()

    raise Exception("Download failed after 3 attempts — try another video or quality")


@app.route("/")
def index():
    return jsonify({
        "name": "YouTube Downloader API v4.2",
        "qualities": list(QUALITY_MAP.keys()),
        "note": "Shorts sirf 1 quality mein hoti hain — actual quality filename mein show hogi",
        "examples": {
            "720p":  "/download?url=https://youtu.be/ID&quality=720",
            "360p":  "/download?url=https://youtu.be/ID&quality=360",
            "audio": "/download?url=https://youtu.be/ID&quality=audio",
        }
    })

@app.route("/qualities")
def qualities():
    return jsonify({"qualities": list(QUALITY_MAP.keys())})

@app.route("/info")
def info_route():
    url = request.args.get("url","").strip()
    if not url: return jsonify({"error":"url chahiye"}), 400
    norm_url    = normalize_url(url)
    cookie_file = make_cookies(COOKIES_FILE)
    proxy       = rand_proxy()
    try:
        try:
            with yt_dlp.YoutubeDL({**BASE_OPTS,"proxy":proxy,"extractor_args":{"youtube":ANDROID_EXTRACTOR},"http_headers":{"User-Agent":"com.google.android.youtube/19.09.37 (Linux; U; Android 13; en_US) gzip"}}) as ydl:
                d = ydl.extract_info(norm_url, download=False)
        except Exception:
            with yt_dlp.YoutubeDL({**BASE_OPTS,"proxy":proxy,"cookiefile":cookie_file,"extractor_args":{"youtube":WEB_EXTRACTOR},"http_headers":{"User-Agent":"Mozilla/5.0"}}) as ydl:
                d = ydl.extract_info(norm_url, download=False)

        duration = d.get("duration")
        seen = set(); res = []
        for f in d.get("formats",[]):
            hh = f.get("height")
            if hh and hh not in seen:
                seen.add(hh); res.append({"height":hh,"label":f"{hh}p"})
        res.sort(key=lambda x: x["height"], reverse=True)

        return jsonify({
            "title":       d.get("title","Unknown"),
            "duration":    duration,
            "author":      d.get("uploader") or d.get("channel",""),
            "views":       d.get("view_count"),
            "thumbnail":   d.get("thumbnail",""),
            "is_short":    "/shorts/" in url or bool(duration and duration<=60),
            "resolutions": res,
            "links": {q:f"/download?url={url}&quality={q}" for q in ["1080","720","480","360","audio"]},
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try: os.unlink(cookie_file)
        except: pass

@app.route("/download")
def download():
    url     = request.args.get("url","").strip()
    quality = request.args.get("quality","720").strip().lower().rstrip("p")

    if not url:
        return jsonify({"error":"url chahiye"}), 400
    if quality not in QUALITY_MAP:
        return jsonify({"error":f"Quality '{quality}' galat","valid":list(QUALITY_MAP.keys())}), 400

    norm_url    = normalize_url(url)
    output_dir  = tempfile.mkdtemp(dir=TEMP_DIR)
    cookie_file = make_cookies(COOKIES_FILE)

    try:
        title, actual_h = do_download(norm_url, quality, output_dir, cookie_file)

        files = [f for f in os.listdir(output_dir)
                 if not f.endswith(('.part','.ytdl','.json'))]
        if not files:
            return jsonify({"error":"File nahi bani"}), 500

        filepath   = os.path.join(output_dir, files[0])
        is_audio   = (quality == "audio")
        safe_title = sanitize(title)

        # Actual downloaded quality filename mein — same size issue clear hogi
        if is_audio:
            filename     = f"{safe_title}.mp3"
            content_type = "audio/mpeg"
        else:
            # Actual height use karo agar available ho
            q_label = f"{actual_h}p" if actual_h else f"{quality}p"
            filename     = f"{safe_title}_{q_label}.mp4"
            content_type = "video/mp4"

        filesize = os.path.getsize(filepath)

        def stream():
            try:
                with open(filepath,"rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk: break
                        yield chunk
            finally:
                def _c():
                    try: shutil.rmtree(output_dir, ignore_errors=True)
                    except: pass
                    try: os.unlink(cookie_file)
                    except: pass
                threading.Thread(target=_c, daemon=True).start()

        fn = sanitize(filename).encode("ascii","ignore").decode("ascii")
        return Response(stream(), headers={
            "Content-Disposition": f'attachment; filename="{fn}"',
            "Content-Type":        content_type,
            "Content-Length":      str(filesize),
            "X-Video-Quality":     quality,
            "X-Actual-Height":     str(actual_h or ""),
        }, status=200)

    except Exception as e:
        shutil.rmtree(output_dir, ignore_errors=True)
        try: os.unlink(cookie_file)
        except: pass
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
