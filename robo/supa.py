"""Acesso ao banco e aos arquivos do app pela API do robô (/api/public/worker), protegida por WORKER_SECRET."""
import os
import requests

APP = os.environ["APP_URL"].strip().rstrip("/")
SECRET = os.environ["WORKER_SECRET"].strip()


def _call(op, **body):
    r = requests.post(f"{APP}/api/public/worker", json={"op": op, **body}, timeout=60,
                      headers={"Authorization": f"Bearer {SECRET}"})
    if r.status_code == 404 and op == "elevenlabs_key":
        return None
    if not r.ok:
        raise requests.HTTPError(f"API do app recusou {op} ({r.status_code}): {r.text[:300]}", response=r)
    return r.json()


def select(table, params):
    params = dict(params)
    body = {"table": table, "filters": {}}
    for k in ("order", "limit"):
        if k in params:
            body[k] = params.pop(k)
    if "select" in params:
        body["columns"] = params.pop("select")
    body["filters"] = params
    return _call("select", **body)


def one(table, params):
    rows = select(table, {**params, "limit": 1})
    return rows[0] if rows else None


def update(table, filters, values):
    return _call("update", table=table, filters=filters, values=values)


def insert(table, values):
    return _call("insert", table=table, values=values)


def elevenlabs_key(user_id):
    got = _call("elevenlabs_key", user_id=user_id)
    return got["key"] if got else None


def download(path, dest):
    url = _call("download_url", path=path)["url"]
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return dest


def upload(path, src, content_type="video/mp4"):
    url = _call("upload_url", path=path)["url"]
    with open(src, "rb") as f:
        r = requests.put(url, data=f, headers={"Content-Type": content_type, "x-upsert": "true"}, timeout=600)
    r.raise_for_status()
    return path


def _frames(frame_paths):
    import base64
    frames = []
    for fp in frame_paths:
        with open(fp, "rb") as f:
            frames.append(base64.b64encode(f.read()).decode())
    return frames


def headline(product_id, frame_paths):
    got = _call("headline", product_id=product_id, frames=_frames(frame_paths))
    return got["text"], got.get("emojis", "")


def narration(product_id, frame_paths, hook=None):
    """Pede ao app uma narração no padrão de edição (o app também salva em produtos.roteiro)."""
    body = {"product_id": product_id, "frames": _frames(frame_paths)}
    if hook:
        body["hook"] = hook
    return _call("narration", **body)["text"]
