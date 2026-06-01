from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import requests

app = FastAPI(title="YouTube Downloader API")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://app.ytdown.to/en32/",
    "Origin": "https://app.ytdown.to"
}

@app.get("/download")
@app.get("/api/download")
def get_download_link(
    url: str = Query(..., description="YouTube Video URL"),
    resolution: str = Query("720", description="360, 480, 720, 1080, mp3")
):
    if "youtu" not in url.lower():
        raise HTTPException(status_code=400, detail="Sirf YouTube URLs support hain.")

    req_res = resolution.lower().strip()
    print(f"\n🚀 Request: {url} | Quality: {req_res}")

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        base_url = "https://app.ytdown.to/en32/"
        session.get(base_url, timeout=10)

        # First request
        payload = {"url": url}
        resp = session.post("https://app.ytdown.to/proxy.php", data=payload, timeout=20)
        data = resp.json()

        if not isinstance(data, dict) or "api" not in data:
            raise HTTPException(status_code=400, detail="Site se response nahi mila.")

        api_data = data["api"]
        title = api_data.get("title", "YouTube Video")
        media_items = api_data.get("mediaItems", []) or api_data.get("formats", [])

        if not media_items:
            raise HTTPException(status_code=404, detail="Video ke formats nahi mile. Video private/restricted ho sakti hai.")

        media_url = None
        actual_res = req_res

        # Improved matching
        for item in media_items:
            if not isinstance(item, dict):
                continue
            m_url = item.get("mediaUrl") or item.get("url")
            m_type = str(item.get("type", "")).lower()
            m_ext = str(item.get("mediaExtension", "")).lower()
            m_res = str(item.get("resolution", "")).lower()

            if req_res == "mp3":
                if "audio" in m_type or "m4a" in m_ext or "mp3" in m_ext:
                    media_url = m_url
                    actual_res = "mp3"
                    break
            else:
                if req_res in m_res or req_res in str(item):
                    media_url = m_url
                    actual_res = req_res
                    break

        # Fallback
        if not media_url:
            if req_res == "mp3":
                for item in media_items:
                    if isinstance(item, dict) and ("audio" in str(item.get("type", "")).lower() or "m4a" in str(item.get("mediaExtension", "")).lower()):
                        media_url = item.get("mediaUrl") or item.get("url")
                        break
            else:
                for item in media_items:
                    if isinstance(item, dict):
                        media_url = item.get("mediaUrl") or item.get("url")
                        break

        if not media_url:
            raise HTTPException(status_code=404, detail=f"{req_res} quality nahi mili.")

        # Final direct link
        final_resp = session.post("https://app.ytdown.to/proxy.php", data={"url": media_url}, timeout=25)
        final_data = final_resp.json()

        if isinstance(final_data, dict) and "api" in final_data and "fileUrl" in final_data["api"]:
            return JSONResponse({
                "success": True,
                "title": title,
                "resolution": actual_res,
                "download_url": final_data["api"]["fileUrl"]
            })
        else:
            raise HTTPException(status_code=500, detail="Final link nahi bana.")

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Site busy hai ya temporary error. Thodi der baad try karo.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
