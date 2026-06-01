from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import requests

app = FastAPI(title="YouTube Downloader API")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://app.ytdown.to/"
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
        # Updated base URL (site changed)
        base_url = "https://app.ytdown.to/en32/"   # ← Updated yahan
        session.get(base_url, timeout=10)

        payload = {"url": url}
        resp = session.post("https://app.ytdown.to/proxy.php", data=payload, timeout=20)
        
        if not resp.ok:
            raise HTTPException(status_code=502, detail="Downloader site busy hai.")

        data = resp.json()

        if not isinstance(data, dict) or "api" not in data:
            raise HTTPException(status_code=400, detail="Site se invalid response aaya.")

        api_data = data["api"]
        title = api_data.get("title", "YouTube Video")
        media_items = api_data.get("mediaItems", [])

        if not media_items:
            raise HTTPException(status_code=404, detail="Is video ke liye media nahi mila (private ya restricted ho sakti hai).")

        media_url = None
        actual_res = req_res

        # Better matching logic
        for item in media_items:
            if not isinstance(item, dict): 
                continue
            item_url = str(item.get("mediaUrl", "")).lower()
            item_type = str(item.get("type", "")).lower()
            item_ext = str(item.get("mediaExtension", "")).lower()

            if req_res == "mp3":
                if "audio" in item_type and ("mp3" in item_ext or "m4a" in item_ext):
                    media_url = item.get("mediaUrl")
                    actual_res = "mp3"
                    break
            else:
                if "video" in item_type and req_res in item_url:
                    media_url = item.get("mediaUrl")
                    actual_res = req_res
                    break

        # Strong Fallback
        if not media_url:
            if req_res == "mp3":
                for item in media_items:
                    if isinstance(item, dict) and "audio" in str(item.get("type", "")).lower():
                        media_url = item.get("mediaUrl")
                        actual_res = "mp3"
                        break
            else:
                for item in media_items:
                    if isinstance(item, dict) and "video" in str(item.get("type", "")).lower():
                        media_url = item.get("mediaUrl")
                        actual_res = "best"
                        break

        if not media_url:
            raise HTTPException(status_code=404, detail=f"{req_res} quality abhi available nahi hai.")

        # Get final direct link
        final_resp = session.post("https://app.ytdown.to/proxy.php", 
                                data={"url": media_url}, timeout=30)
        final_data = final_resp.json()

        if isinstance(final_data, dict) and "api" in final_data and "fileUrl" in final_data["api"]:
            return JSONResponse({
                "success": True,
                "title": title,
                "resolution": actual_res,
                "download_url": final_data["api"]["fileUrl"]
            })
        else:
            raise HTTPException(status_code=500, detail="Final link generate nahi ho saka.")

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server Error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
