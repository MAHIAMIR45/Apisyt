import time
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import requests

app = FastAPI(title="YouTube Downloader API")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://app.ytdown.to/"
}

# Dono routes support karne ke liye
@app.get("/api/download")
@app.get("/download")   # ← Yeh naya add kiya
def get_download_link(
    url: str = Query(..., description="YouTube Video URL"),
    resolution: str = Query("720", description="360, 480, 720, 1080, 1440, 2160, mp3")
):
    if "youtu" not in url.lower():
        raise HTTPException(status_code=400, detail="Sirf YouTube URLs support hain.")

    req_res = resolution.lower().strip()
    print(f"\n🚀 Request: {url} | Quality: {req_res}")

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        session.get("https://app.ytdown.to/en23/", timeout=10)

        payload = {"url": url}
        resp = session.post("https://app.ytdown.to/proxy.php", data=payload, timeout=20)
        
        if not resp.ok:
            raise HTTPException(status_code=500, detail="Site se response nahi mila.")

        data = resp.json()

        # Safety check
        if not isinstance(data, dict) or "api" not in data:
            raise HTTPException(status_code=400, detail="Invalid response from downloader site.")

        api_data = data.get("api")
        if not isinstance(api_data, dict):
            raise HTTPException(status_code=400, detail="Unexpected response format.")

        title = api_data.get("title", "YouTube Video")
        media_items = api_data.get("mediaItems", [])

        if not media_items:
            raise HTTPException(status_code=404, detail="Koi media nahi mila. Video private/private ho sakti hai.")

        media_url = None
        actual_res = req_res

        # Exact match
        for item in media_items:
            if not isinstance(item, dict):
                continue
                
            item_url = str(item.get("mediaUrl", "")).lower()
            item_type = item.get("type", "")
            item_ext = str(item.get("mediaExtension", "")).lower()

            if req_res == "mp3":
                if item_type == "Audio" and ("mp3" in item_ext or "m4a" in item_ext):
                    media_url = item.get("mediaUrl")
                    actual_res = "mp3"
                    print("✅ MP3 Found")
                    break
            else:
                if item_type == "Video" and req_res in item_url:
                    media_url = item.get("mediaUrl")
                    actual_res = req_res
                    print(f"✅ {req_res} Found")
                    break

        # Fallback
        if not media_url:
            if req_res == "mp3":
                audio_items = [item for item in media_items if isinstance(item, dict) and item.get("type") == "Audio"]
                if audio_items:
                    media_url = audio_items[-1].get("mediaUrl")
                    actual_res = "mp3"
            else:
                video_items = [item for item in media_items if isinstance(item, dict) and item.get("type") == "Video"]
                if video_items:
                    media_url = video_items[0].get("mediaUrl")
                    actual_res = "best"

        if not media_url:
            raise HTTPException(status_code=404, detail=f"{req_res} quality nahi mili.")

        # Final link
        final_resp = session.post("https://app.ytdown.to/proxy.php", 
                                data={"url": media_url}, timeout=25)
        final_data = final_resp.json()

        if isinstance(final_data, dict) and "api" in final_data and "fileUrl" in final_data["api"]:
            return JSONResponse({
                "success": True,
                "title": title,
                "resolution": actual_res,
                "download_url": final_data["api"]["fileUrl"]
            })
        else:
            raise HTTPException(status_code=500, detail="Final download link nahi bana.")

    except HTTPException as e:
        raise
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server Error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
