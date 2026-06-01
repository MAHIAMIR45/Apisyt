import os, re, json, random, shutil, tempfile, threading
from flask import Flask, request, Response, jsonify
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR    = os.path.join(BASE_DIR, "temp_downloads")
COOKIES_FILE= os.path.join(BASE_DIR, "cookies.json")
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
    return re.sub(r'[\\/*?:"<>|]',"_",s)[:180].strip()

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

# ── Format strings — DASH/HLS skip karo (nsig crash avoid) ───────────────────
def video_fmt(h):
    if h is None:
        return (
            "best[protocol!=dash][protocol!=m3u8]"
            "/bestvideo[protocol!=dash]+bestaudio[protocol!=dash]"
            "/best"
        )
    return (
        f"best[height<={h}][protocol!=dash][protocol!=m3u8]"
        f"/best[height<={h}]"
        f"/best[protocol!=dash][protocol!=m3u8]"
        f"/best"
    )

AUDIO_FMT = (
    "bestaudio[protocol!=dash][protocol!=m3u8][ext=m4a]"
    "/bestaudio[protocol!=dash][protocol!=m3u8]"
    "/bestaudio/best"
)

# ── yt-dlp options ─────────────────────────────────────────────────────────────
def mk_opts(proxy, cookie_file, fmt, outtmpl, audio=False):
    extractor_args = {
        "player_client": ["android"],
        "formats": ["missing_pot"],   # GVS token warning bypass
        # DASH/HLS skip — ye hi nsig crash karta tha
        "skip": ["dash", "hls", "translated_subs"],
    }
    opts = {
        "format":         fmt,
        "outtmpl":        outtmpl,
        "quiet":          True,
        "no_warnings":    False,
        "noplaylist":     True,
        "proxy":          proxy,
        "socket_timeout": 30,
        "retries":        2,
        "fragment_retries": 2,
        "extractor_args": {"youtube": extractor_args},
        "http_headers": {
            "User-Agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 13; en_US) gzip",
        },
        # Memory save
        "concurrent_fragment_downloads": 1,
        "buffersize": 16384,
    }
    if cookie_file:
        opts["cookiefile"] = cookie_file
    if audio:
        opts["postprocessors"] = [{"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":"192"}]
        # Audio ke liye web_creator bhi try karo
        extractor_args["player_client"] = ["android", "web_creator", "web"]
    return opts

def mk_opts_web(proxy, cookie_file, fmt, outtmpl, audio=False):
    """Web fallback — bhi DASH/HLS skip"""
    extractor_args = {
        "player_client": ["web_creator", "web"],
        "skip": ["dash", "hls", "translated_subs"],
    }
    opts = {
        "format":         fmt,
        "outtmpl":        outtmpl,
        "cookiefile":     cookie_file,
        "quiet":          True,
        "noplaylist":     True,
        "proxy":          proxy,
        "socket_timeout": 30,
        "retries":        2,
        "merge_output_format": "mp4",
        "extractor_args": {"youtube": extractor_args},
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
            ),
        },
        "concurrent_fragment_downloads": 1,
    }
    if audio:
        opts["postprocessors"] = [{"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":"192"}]
    return opts


def do_download(norm_url, quality, output_dir, cookie_file):
    is_audio = (quality == "audio")
    h        = QUALITY_MAP.get(quality)
    fmt      = AUDIO_FMT if is_audio else video_fmt(h)
    outtmpl  = os.path.join(output_dir, "%(title)s.%(ext)s")
    title    = "video"

    for attempt in range(3):
        proxy = rand_proxy()
        try:
            # Pass 1: Android + no DASH
            ydl_opts = mk_opts(proxy, None, fmt, outtmpl, audio=is_audio)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(norm_url, download=True)
                if info: title = info.get("title", title)
            return title
        except Exception:
            pass

        # Clean up partial files
        for f in os.listdir(output_dir):
            try: os.unlink(os.path.join(output_dir, f))
            except: pass

        try:
            # Pass 2: Web + cookies + no DASH
            ydl_opts = mk_opts_web(proxy, cookie_file, fmt, outtmpl, audio=is_audio)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(norm_url, download=True)
                if info: title = info.get("title", title)
            return title
        except Exception:
            pass

        # Clean for next attempt
        for f in os.listdir(output_dir):
            try: os.unlink(os.path.join(output_dir, f))
            except: pass

    raise Exception("3 attempts failed — please try again")


@app.route("/")
def index():
    return jsonify({
        "name": "YouTube Downloader API v4.1",
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
    url = request.args.get("url","").strip()
    if not url: return jsonify({"error":"url chahiye"}), 400
    norm_url = normalize_url(url)
    cookie_file = make_cookies(COOKIES_FILE)
    try:
        opts = mk_opts(rand_proxy(), None, "best", "/tmp/info_%(id)s.%(ext)s")
        opts["skip_download"] = True
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info_dict = ydl.extract_info(norm_url, download=False)
            except Exception:
                opts2 = mk_opts_web(rand_proxy(), cookie_file, "best", "/tmp/info2_%(id)s.%(ext)s")
                opts2["skip_download"] = True
                with yt_dlp.YoutubeDL(opts2) as ydl2:
                    info_dict = ydl2.extract_info(norm_url, download=False)

        duration = info_dict.get("duration")
        seen = set(); resolutions = []
        for fmt in info_dict.get("formats",[]):
            h = fmt.get("height")
            if h and h not in seen:
                seen.add(h); resolutions.append({"height":h,"label":f"{h}p"})
        resolutions.sort(key=lambda x: x["height"], reverse=True)

        return jsonify({
            "title":       info_dict.get("title","Unknown"),
            "duration":    duration,
            "author":      info_dict.get("uploader") or info_dict.get("channel",""),
            "views":       info_dict.get("view_count"),
            "thumbnail":   info_dict.get("thumbnail",""),
            "is_short":    "/shorts/" in url or bool(duration and duration<=60),
            "resolutions": resolutions,
            "links": {q: f"/download?url={url}&quality={q}" for q in ["1080","720","480","360","audio"]},
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
        title = do_download(norm_url, quality, output_dir, cookie_file)

        files = [f for f in os.listdir(output_dir) if not f.endswith(('.part','.ytdl'))]
        if not files:
            return jsonify({"error":"File nahi bani"}), 500

        filepath     = os.path.join(output_dir, files[0])
        is_audio     = (quality=="audio")
        safe_title   = sanitize(title)
        filename     = f"{safe_title}.mp3" if is_audio else f"{safe_title}_{quality}p.mp4"
        content_type = "audio/mpeg" if is_audio else "video/mp4"
        filesize     = os.path.getsize(filepath)

        def stream():
            try:
                with open(filepath,"rb") as f:
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

        fn = sanitize(filename).encode("ascii","ignore").decode("ascii")
        return Response(stream(), headers={
            "Content-Disposition": f'attachment; filename="{fn}"',
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
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
