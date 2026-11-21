"""Acesso ao banco e aos arquivos do app (Lovable Cloud / Supabase) com a chave de serviço."""
import os
import requests

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
BUCKET = "affiliate-media"
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def select(table, params):
    r = requests.get(f"{URL}/rest/v1/{table}", headers=H, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def one(table, params):
    rows = select(table, {**params, "limit": 1})
    return rows[0] if rows else None


def update(table, filters, values):
    r = requests.patch(
        f"{URL}/rest/v1/{table}", headers={**H, "Prefer": "return=representation"},
        params=filters, json=values, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def insert(table, values):
    r = requests.post(
        f"{URL}/rest/v1/{table}", headers={**H, "Prefer": "return=representation"},
        json=values, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def download(path, dest):
    with requests.get(f"{URL}/storage/v1/object/{BUCKET}/{path}", headers=H, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return dest


def upload(path, src, content_type="video/mp4"):
    with open(src, "rb") as f:
        r = requests.post(
            f"{URL}/storage/v1/object/{BUCKET}/{path}",
            headers={**H, "Content-Type": content_type, "x-upsert": "true"},
            data=f, timeout=600,
        )
    r.raise_for_status()
    return path


def signed_url(path, seconds=3600):
    r = requests.post(
        f"{URL}/storage/v1/object/sign/{BUCKET}/{path}", headers=H,
        json={"expiresIn": seconds}, timeout=30,
    )
    r.raise_for_status()
    return URL + "/storage/v1" + r.json()["signedURL"]
