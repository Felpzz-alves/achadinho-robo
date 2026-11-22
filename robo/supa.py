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


_CAMPOS = "nome,nome_provisorio,categoria,subcategoria,hashtags_list,beneficios,palavra,hook_text,falar_preco,preco"


def _produto(product_id):
    return one("produtos", {"id": f"eq.{product_id}", "select": _CAMPOS}) or {}


def headline(product_id, frame_paths):
    from . import ia
    if not ia.ativo():
        got = _call("headline", product_id=product_id, frames=_frames(frame_paths))
        return got["text"], got.get("emojis", "")
    p = _produto(product_id)
    if (p.get("hook_text") or "").strip():
        return p["hook_text"].strip(), "✨"
    return ia.gancho(p, frame_paths)


def narration(product_id, frame_paths, hook=None):
    """Narração no padrão de edição; também fica salva em produtos.roteiro."""
    from . import ia
    if not ia.ativo():
        body = {"product_id": product_id, "frames": _frames(frame_paths)}
        if hook:
            body["hook"] = hook
        return _call("narration", **body)["text"]
    p = _produto(product_id)
    if (p.get("hook_text") or "").strip():
        hook = p["hook_text"].strip()
    text = ia.narracao(p, frame_paths, hook)
    update("produtos", {"id": f"eq.{product_id}"}, {"roteiro": text})
    return text


def identify(product_id, frame_paths):
    """Reconhece o produto pelos frames e preenche só os campos vazios. Devolve o que salvou."""
    from . import ia
    if not ia.ativo():
        return _call("identify", product_id=product_id, frames=_frames(frame_paths))
    cur = _produto(product_id)
    got = ia.identificar(frame_paths)
    patch = {}
    if not cur.get("nome") or cur.get("nome") == cur.get("nome_provisorio"):
        patch["nome"] = got["nome"]
    if not cur.get("categoria"):
        patch["categoria"] = got["categoria"]
    if not cur.get("subcategoria"):
        patch["subcategoria"] = got["subcategoria"]
    if not cur.get("hashtags_list") and got["hashtags"]:
        patch["hashtags_list"] = got["hashtags"]
        patch["hashtags"] = " ".join(got["hashtags"])
    if patch:
        update("produtos", {"id": f"eq.{product_id}"}, patch)
    return patch


def upsert(table, values, on_conflict):
    return _call("upsert", table=table, values=values, on_conflict=on_conflict)


def shopee_conversions(user_id, date):
    """Comissões do dia (YYYY-MM-DD) pela API de afiliados da Shopee do cliente: [{sub_id, comissao, pedidos}]."""
    return _call("shopee_conversions", user_id=user_id, date=date).get("rows", [])
