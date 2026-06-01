from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import subprocess
import json

app = FastAPI(title="YouTube Downloader API")

@app.get("/download")
@app.get("/api/download")
def get_download_link(
    url: str = Query(..., description="YouTube Video URL"),
    resolution: str = Query("720", description="360, 480, 720, 1080, 1440, 2160, mp3")
):
    if "youtu" not in url.lower():
        raise HTTPException(status_code=400, detail="Sirf YouTube URLs support hain.")

    req_res = resolution.lower().strip()
    print(f"\n🚀 Request: {url} | Quality: {req_res}")

    try:
        # yt-dlp command
        cmd = ["yt-dlp", "--dump-json", url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            raise HTTPException(status_code=400, detail="Video info nahi mili.")

        info = json.loads(result.stdout)

        title = info.get("title", "YouTube Video")
        formats = info.get("formats", [])

        download_url = None
        actual_res = req_res

        if req_res == "mp3":
            # Best audio
            audio_formats = [f for f in formats if f.get("acodec") != "none" and f.get("vcodec") == "none"]
            if audio_formats:
                best_audio = max(audio_formats, key=lambda x: x.get("abr", 0) or 0)
                download_url = best_audio.get("url")
                actual_res = "mp3"
        else:
            # Video with specific resolution
            target_height = int(req_res) if req_res.isdigit() else 720
            video_formats = [f for f in formats if f.get("vcodec") != "none" and f.get("height")]
            
            # Exact match
            for f in sorted(video_formats, key=lambda x: x.get("height", 0), reverse=True):
                if f.get("height") == target_height and f.get("ext") in ["mp4", "webm"]:
                    download_url = f.get("url")
                    actual_res = str(f.get("height"))
                    break
            
            # Fallback to best
            if not download_url and video_formats:
                best = max(video_formats, key=lambda x: x.get("height", 0))
                download_url = best.get("url")
                actual_res = "best"

        if not download_url:
            raise HTTPException(status_code=404, detail=f"{req_res} quality nahi mili.")

        return JSONResponse({
            "success": True,
            "title": title,
            "resolution": actual_res,
            "download_url": download_url
        })

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server Error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
