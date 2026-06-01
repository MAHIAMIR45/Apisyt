import time
import json
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import requests

app = FastAPI(title="YouTube Downloader API")

# Better Headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://app.ytdown.to/"
}

@app.get("/api/download")
def get_download_link(
    url: str = Query(..., description="YouTube Video URL"),
    resolution: str = Query("720", description="Resolution: 360, 480, 720, 1080, 1440, 2160, mp3")
):
    if "youtu" not in url.lower():
        raise HTTPException(status_code=400, detail="Sirf YouTube URLs support hain.")

    req_res = resolution.lower().strip()
    print(f"\n🚀 Request: {url} | Quality: {req_res}")

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # Step 1: Initial request
        session.get("https://app.ytdown.to/en23/")

        # Step 2: Send video URL
        payload = {"url": url}
        resp = session.post("https://app.ytdown.to/proxy.php", data=payload, timeout=20)
        data = resp.json()

        if "api" not in data or "mediaItems" not in data["api"]:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL ya site error.")

        title = data["api"].get("title", "YouTube Video")
        media_items = data["api"].get("mediaItems", [])

        media_url = None
        actual_res = req_res

        # Priority: Exact match first
        for item in media_items:
            item_url = str(item.get("mediaUrl", "")).lower()
            item_type = item.get("type", "")
            item_ext = str(item.get("mediaExtension", "")).lower()

            if req_res == "mp3":
                if item_type == "Audio" and ("mp3" in item_ext or "m4a" in item_ext):
                    media_url = item.get("mediaUrl")
                    actual_res = "mp3"
                    print("✅ MP3 Exact Match Mila")
                    break
            else:
                if item_type == "Video" and req_res in item_url:
                    media_url = item.get("mediaUrl")
                    actual_res = req_res
                    print(f"✅ {req_res}p Exact Match Mila")
                    break

        # Fallback logic
        if not media_url:
            if req_res == "mp3":
                # Best audio fallback
                audio_items = [item for item in media_items if item.get("type") == "Audio"]
                if audio_items:
                    media_url = audio_items[-1].get("mediaUrl")  # Best quality audio
                    actual_res = "mp3"
                    print("⚠️ MP3 Fallback use kiya")
            else:
                # Best video fallback
                video_items = [item for item in media_items if item.get("type") == "Video"]
                if video_items:
                    media_url = video_items[0].get("mediaUrl")  # Highest available
                    actual_res = "best"
                    print("⚠️ Best Quality Fallback")

        if not media_url:
            raise HTTPException(status_code=404, detail="Koi bhi quality nahi mili.")

        # Step 3: Get final download link
        final_payload = {"url": media_url}
        final_resp = session.post("https://app.ytdown.to/proxy.php", data=final_payload, timeout=25)
        final_data = final_resp.json()

        if "api" in final_data and "fileUrl" in final_data["api"]:
            return JSONResponse(content={
                "success": True,
                "title": title,
                "resolution": actual_res,
                "download_url": final_data["api"]["fileUrl"],
                "message": "Direct download link ready!"
            })
        else:
            raise HTTPException(status_code=500, detail="Final link generate nahi ho saka.")

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server Error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
