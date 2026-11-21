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


# ------------------------------------------------------------------ anúncios (Meta pelo Zernio)
def _ads(method, path, **kw):
    headers = {**_h()}
    if method == "POST":
        headers["Idempotency-Key"] = kw.pop("idem", None) or str(uuid.uuid4())
    r = requests.request(method, f"{BASE}{path}", headers=headers, timeout=kw.pop("timeout", 120), **kw)
    if r.status_code == 403:
        raise RuntimeError("O Zernio recusou anúncios (plano sem anúncios ou cartão não cadastrado no Zernio).")
    if not r.ok:
        raise RuntimeError(f"Zernio recusou ({r.status_code}): {r.text[:300]}")
    return r.json() if r.content else {}


def create_video_ad(account_id, ad_account_id, name, video_url, body, headline, link, budget,
                    age_min=18, age_max=45, gender="female", countries=("BR",), status="ACTIVE", idem=None):
    """Anúncio de tráfego com o vídeo final e texto limpo (não usa a legenda do post)."""
    payload = {
        "accountId": account_id, "adAccountId": ad_account_id, "name": name, "goal": "traffic",
        "budgetAmount": budget, "budgetType": "daily",
        "headline": headline[:40], "body": body,
        "video": {"url": video_url},
        "callToAction": "SHOP_NOW", "linkUrl": link,
        "countries": list(countries), "gender": gender, "ageMin": age_min, "ageMax": age_max,
        "placements": {"publisherPlatforms": ["facebook", "instagram"]},
        "status": status,
    }
    return _ads("POST", "/ads/create", json=payload, idem=idem, timeout=900)["ad"]


def set_campaign_status(campaign_id, status):
    """status: 'paused' ou 'active'."""
    return _ads("PUT", f"/ads/campaigns/{campaign_id}/status", json={"status": status, "platform": "facebook"})


def set_budget(campaign_id, adset_id, amount):
    """Tenta no nível da campanha; se o orçamento estiver no conjunto, troca lá."""
    try:
        return _ads("PUT", f"/ads/campaigns/{campaign_id}",
                    json={"platform": "facebook", "budget": {"amount": amount, "type": "daily"}})
    except RuntimeError as e:
        if "409" not in str(e) or not adset_id:
            raise
        return _ads("PUT", f"/ads/ad-sets/{adset_id}",
                    json={"platform": "facebook", "budget": {"amount": amount, "type": "daily"}})


def delete_campaign(campaign_id, account_id):
    return _ads("DELETE", f"/ads/campaigns/{campaign_id}", json={"platform": "facebook", "accountId": account_id})


def ads_tree(account_id, ad_account_id, from_date, to_date):
    """Campanhas > conjuntos > anúncios com métricas por dia (timeIncrement=1)."""
    params = {"accountId": account_id, "adAccountId": ad_account_id, "fromDate": from_date,
              "toDate": to_date, "timeIncrement": 1}
    for _ in range(3):
        r = requests.get(f"{BASE}/ads/tree", headers=_h(), params=params, timeout=120)
        if r.status_code == 202:  # histórico sendo buscado no Meta
            import time
            time.sleep(10)
            continue
        if not r.ok:
            raise RuntimeError(f"Zernio recusou métricas ({r.status_code}): {r.text[:300]}")
        return r.json()
    return {}
