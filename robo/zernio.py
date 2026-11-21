"""Postagem no Instagram (Reels) pelo Zernio. Um vídeo sozinho vira Reel automaticamente."""
import os
import uuid

import requests

BASE = "https://zernio.com/api/v1"


def _h():
    return {"Authorization": f"Bearer {os.environ['ZERNIO_API_KEY']}"}


def upload_video(path, filename="reel.mp4"):
    size = os.path.getsize(path)
    r = requests.post(f"{BASE}/media/presign", headers=_h(), timeout=30,
                      json={"filename": filename, "contentType": "video/mp4", "size": size})
    r.raise_for_status()
    pre = r.json()
    with open(path, "rb") as f:
        up = requests.put(pre["uploadUrl"], data=f, headers={"Content-Type": "video/mp4"}, timeout=600)
    up.raise_for_status()
    return pre["publicUrl"]


def schedule_reel(account_id, video_url, caption, when_local, timezone="America/Sao_Paulo"):
    """when_local: 'YYYY-MM-DD HH:MM' no fuso do cliente."""
    body = {
        "content": caption,
        "mediaItems": [{"url": video_url, "type": "video"}],
        "platforms": [{"platform": "instagram", "accountId": account_id,
                       "platformSpecificData": {"shareToFeed": True}}],
        "scheduledFor": when_local.replace(" ", "T") + ":00",
        "timezone": timezone,
    }
    r = requests.post(f"{BASE}/posts", headers={**_h(), "Idempotency-Key": str(uuid.uuid4())},
                      json=body, timeout=120)
    if not r.ok:
        raise RuntimeError(f"Zernio recusou o agendamento ({r.status_code}): {r.text[:300]}")
    return r.json()["post"]["_id"]


def recent_posts(status, since_iso=None):
    params = {"status": status, "platform": "instagram", "limit": 100}
    if since_iso:
        params["updatedSince"] = since_iso
    r = requests.get(f"{BASE}/posts", headers=_h(), params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("posts", [])
