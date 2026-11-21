"""Robô de edição e postagem do Achadinho.

Laço:
 1. Pega o próximo pedido em edit_jobs (status queued), edita e entrega prévia + vídeo final.
 2. Agenda no Instagram (Zernio) os vídeos aprovados de quem ligou a postagem automática.
 3. Confere no Zernio o que já foi publicado e marca como Postado no app.
"""
import logging
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

REQUIRED = ["APP_URL", "WORKER_SECRET"]
_missing = [v for v in REQUIRED if not os.environ.get(v, "").strip()]
if _missing:
    print("FALTAM VARIÁVEIS NO RAILWAY: " + ", ".join(_missing)
          + ". Crie em Variables e clique em Deploy para aplicar.", flush=True)
    time.sleep(300)
    raise SystemExit(1)
if not os.environ.get("ZERNIO_API_KEY"):
    print("Aviso: ZERNIO_API_KEY não configurada; a postagem automática fica desligada.", flush=True)

from . import editor, subtitles, supa, voice, zernio  # noqa: E402

log = logging.getLogger("robo")
TZ = ZoneInfo("America/Sao_Paulo")
POLL = int(os.environ.get("POLL_SECONDS", "20"))

DEFAULT_CAPTION = """🚨SEGUE e coment4 “{PALAVRA-CHAVE}” que envi0 o l!nk 👇🏻

- Siga nosso perfil para que eu consiga te enviar os links corretamente no direct!

- Deixa um comentário que te envio o link automaticamente

✨Sempre olhe nas “Solicitações” lá no direct, para verificar se o link chegou por lá ok. Se não tiver chegado, só me pedir no direct que envio para você♥️

(PUBLICIDADE)

#acheinashopee {HASHTAGS}"""


def now_stamp():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- edição
def claim_job():
    jobs = supa.select("edit_jobs", {"status": "eq.queued", "order": "created_at.asc", "limit": 1})
    if not jobs:
        return None
    got = supa.update("edit_jobs", {"id": f"eq.{jobs[0]['id']}", "status": "eq.queued"},
                      {"status": "processing"})
    return got[0] if got else None


def set_product(pid, **values):
    supa.update("produtos", {"id": f"eq.{pid}"}, values)


def process_job(job):
    pid = job["product_id"]
    product = supa.one("produtos", {"id": f"eq.{pid}"})
    if not product or not product.get("raw_path"):
        raise RuntimeError("O vídeo bruto não foi encontrado.")
    profile = supa.one("profiles", {"id": f"eq.{product['user_id']}"}) or {}
    cfg = supa.one("configuracoes", {"user_id": f"eq.{product['user_id']}"}) or {}
    template = product.get("template_id") or cfg.get("template_id") or "classico"
    base = f"{product['user_id']}/edits/{pid}"
    work = tempfile.mkdtemp(prefix="job-")
    try:
        set_product(pid, pipeline="Em edição", error_message="")
        ext = product["raw_path"].rsplit(".", 1)[-1].lower()
        raw = supa.download(product["raw_path"], f"{work}/bruto.{ext}")
        hook = f"{work}/gancho.png"
        frames = []
        try:
            frames = editor.extract_frames(raw, work)
            try:
                # identifica o produto pelo vídeo (nome, categoria, subcategoria, hashtags) sem
                # sobrescrever o que o cliente já preencheu
                product.update({k: v for k, v in (supa.identify(pid, frames) or {}).items() if v})
            except Exception:  # noqa: BLE001
                log.exception("identificação automática indisponível")
            text, emojis = supa.headline(pid, frames)
        except Exception:  # noqa: BLE001 - sem IA, usa o nome do produto
            log.exception("gancho por IA indisponível; usando o nome do produto")
            text, emojis = editor.fallback_headline(product.get("nome"), product.get("categoria"))
        editor.make_hook(hook, text, emojis, template)
        handle = (profile.get("loja") or "").strip()

        preview = f"{work}/previa.mp4"
        editor.build_preview(raw, preview, hook, handle)
        supa.upload(f"{base}/previa.mp4", preview)
        set_product(pid, preview_path=f"{base}/previa.mp4", pipeline="Prévia sem voz")

        set_product(pid, pipeline="Dublagem")
        if (product.get("voice_mode") == "elevenlabs" and not (product.get("roteiro") or "").strip()
                and frames):
            # sem roteiro escrito: o robô cria a narração olhando o vídeo, começando pelo gancho
            for gancho in (text, None):
                try:
                    product["roteiro"] = supa.narration(pid, frames, gancho)
                    break
                except Exception:  # noqa: BLE001 - tenta sem gancho, depois mostra a mensagem de roteiro vazio
                    log.exception("narração automática indisponível")
        try:
            voz = voice.get_voice(product, work)
        except RuntimeError as e:
            # a prévia já está pronta; só a voz falhou (ex.: falta a chave da ElevenLabs)
            set_product(pid, pipeline="Prévia sem voz", error_message=f"Prévia pronta. {e}")
            return
        if not voz:
            # sem narração ainda: o cliente vê a prévia e pode baixar ou gravar a voz depois
            set_product(pid, pipeline="Prévia sem voz",
                        error_message="Prévia pronta. Grave ou envie a narração e mande para edição de novo para o vídeo final.")
            return
        final = f"{work}/final.mp4"
        subs = None
        if product.get("legenda_video"):
            words = product.get("_words") or subtitles.words_even(product.get("roteiro"), editor.duration(voz))
            if words:
                subs = subtitles.write_ass(words, f"{work}/legenda.ass", product.get("legenda_opcoes") or cfg.get("legenda_opcoes"))
        editor.build_final(raw, voz, final, hook, handle, subs=subs)
        supa.upload(f"{base}/final.mp4", final)
        values = {"final_path": f"{base}/final.mp4", "pipeline": "Prévia final", "error_message": ""}
        if product.get("audio_path"):
            values["audio_path"] = product["audio_path"]
        if product.get("etapa") not in ("Aprovado", "Postado"):
            values["etapa"] = "Editado"
        set_product(pid, **values)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def edit_once():
    job = claim_job()
    if not job:
        return False
    log.info("editando produto %s", job["product_id"])
    try:
        process_job(job)
        supa.update("edit_jobs", {"id": f"eq.{job['id']}"}, {"status": "done", "error_message": ""})
    except Exception as e:  # noqa: BLE001 - o erro vai para a tela do cliente
        log.exception("falha na edição")
        msg = str(e)[:400]
        supa.update("edit_jobs", {"id": f"eq.{job['id']}"}, {"status": "failed", "error_message": msg})
        set_product(job["product_id"], pipeline="Erro", error_message=msg)
    return True


# ---------------------------------------------------------------- postagem
def next_slot_after(stamp, horas):
    d, t = stamp.split(" ")
    hs = sorted(horas or ["12:00", "18:00", "21:00"])
    for h in hs:
        if h > t:
            return f"{d} {h}"
    nd = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    return f"{nd} {hs[0]}"


def _hashtags(product):
    tags = product.get("hashtags_list") or product.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    return " ".join(t if t.startswith("#") else "#" + t for t in (x.strip() for x in tags) if t)


def caption_for(product, cfg):
    if (product.get("legenda") or "").strip():
        return product["legenda"]
    tpl = (cfg.get("legenda_template") or "").strip() or DEFAULT_CAPTION
    kw = ((product.get("palavra") or "").strip() or (product.get("subcategoria") or "").strip()
          or (product.get("nome") or "").strip() or "PALAVRA-CHAVE").upper()
    return tpl.replace("{PALAVRA-CHAVE}", kw).replace("{HASHTAGS}", _hashtags(product)).strip()


def latest_destination(pid):
    job = supa.one("edit_jobs", {"product_id": f"eq.{pid}", "order": "created_at.desc", "select": "destination"})
    return (job or {}).get("destination") or "post"


def _post(p, account, cfg, slot):
    """Sobe o vídeo final no Zernio e agenda o Reel. Devolve True se deu certo."""
    work = tempfile.mkdtemp(prefix="post-")
    try:
        video = supa.download(p["final_path"], f"{work}/final.mp4")
        url = zernio.upload_video(video)
        post_id = zernio.schedule_reel(account, url, caption_for(p, cfg), slot)
        set_product(p["id"], zernio_post_id=post_id, scheduled_for=slot,
                    pipeline="Agendado", error_message="")
        log.info("agendado %s para %s", p["id"], slot)
        return True
    except Exception as e:  # noqa: BLE001
        log.exception("falha ao agendar")
        set_product(p["id"], error_message=f"Não consegui agendar a postagem: {str(e)[:300]}")
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _account(uid):
    profile = supa.one("profiles", {"id": f"eq.{uid}"}) or {}
    return (profile.get("zernio_account_id") or "").strip()


def soon_stamp(minutes=3):
    return (datetime.now(TZ) + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")


def schedule_once():
    if not os.environ.get("ZERNIO_API_KEY"):
        return
    # 1) o cliente escolheu "Postar agora" ou um horário na aba Postagem
    for modo in ("agora", "agendado"):
        try:
            pedidos = supa.select("produtos", {"modo_postagem": f"eq.{modo}", "final_path": "neq.",
                                               "zernio_post_id": "eq."})
        except Exception:  # noqa: BLE001 - coluna ainda não existe no app
            pedidos = []
        for p in pedidos:
            account = _account(p["user_id"])
            if not account:
                set_product(p["id"], error_message="Conecte seu Instagram em Conectar contas para postar.")
                continue
            cfg = supa.one("configuracoes", {"user_id": f"eq.{p['user_id']}"}) or {}
            when = (p.get("postar_em") or "").replace("T", " ")[:16]
            slot = when if modo == "agendado" and when > now_stamp() else soon_stamp()
            if not _post(p, account, cfg, slot):
                # não fica tentando sem parar: o cliente vê o erro e pede de novo na aba Postagem
                set_product(p["id"], modo_postagem="", pipeline="Erro")
    # 2) fila: vídeos escolhidos em "Selecione os vídeos para postagem" (modo "fila") e, para quem
    #    ligou a postagem automática, todos os aprovados; um vídeo por horário, na ordem
    filas = {}
    try:
        for p in supa.select("produtos", {"modo_postagem": "eq.fila", "final_path": "neq.",
                                          "zernio_post_id": "eq.", "order": "ordem.asc"}):
            filas.setdefault(p["user_id"], []).append(p)
    except Exception:  # noqa: BLE001 - coluna ainda não existe no app
        pass
    for cfg in supa.select("configuracoes", {"automatic_posting": "is.true"}):
        queue = filas.setdefault(cfg["user_id"], [])
        ids = {p["id"] for p in queue}
        for p in supa.select("produtos", {
            "user_id": f"eq.{cfg['user_id']}", "etapa": "eq.Aprovado", "final_path": "neq.",
            "zernio_post_id": "eq.", "order": "ordem.asc",
        }):
            if p["id"] not in ids and (p.get("modo_postagem") or "") == "" \
                    and latest_destination(p["id"]) != "download":
                queue.append(p)
    for uid, queue in filas.items():
        if not queue:
            continue
        account = _account(uid)
        if not account:
            for p in queue:
                if p.get("modo_postagem") == "fila":
                    set_product(p["id"], error_message="Conecte seu Instagram em Conectar contas para postar.")
            continue
        cfg = supa.one("configuracoes", {"user_id": f"eq.{uid}"}) or {}
        taken = supa.select("produtos", {"user_id": f"eq.{uid}", "scheduled_for": "neq.",
                                         "select": "scheduled_for", "order": "scheduled_for.desc", "limit": 1})
        last = max(now_stamp(), taken[0]["scheduled_for"] if taken else "")
        for p in queue:
            slot = next_slot_after(max(last, p.get("aprovado_em") or ""), cfg.get("horarios"))
            if _post(p, account, cfg, slot):
                last = slot
            elif p.get("modo_postagem") == "fila":
                set_product(p["id"], modo_postagem="", pipeline="Erro")


def sync_published():
    if not os.environ.get("ZERNIO_API_KEY"):
        return
    since = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    for status in ("published", "failed", "partial"):
        for post in zernio.recent_posts(status, since):
            p = supa.one("produtos", {"zernio_post_id": f"eq.{post['_id']}", "etapa": "neq.Postado"})
            if not p:
                continue
            ig = next((x for x in post.get("platforms", []) if x.get("platform") == "instagram"), {})
            if status == "published" or ig.get("status") == "published":
                link = ig.get("platformPostUrl") or ""
                set_product(p["id"], etapa="Postado", pipeline="Postado", reel_link=link,
                            data=datetime.now(TZ).strftime("%Y-%m-%d"), error_message="")
                supa.insert("postagens", {"user_id": p["user_id"], "produto_id": p["id"],
                                          "produto": p.get("nome") or "", "horario": p.get("scheduled_for") or now_stamp(),
                                          "reel_link": link})
            elif p.get("pipeline") != "Erro":
                set_product(p["id"], pipeline="Erro", zernio_post_id="", scheduled_for="",
                            error_message="O Instagram recusou a postagem. Confira a conta conectada e tente de novo.")


# ---------------------------------------------------------------- laço
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("robô iniciado")
    last_post_check = 0.0
    while True:
        try:
            busy = edit_once()
            if time.time() - last_post_check > 120:
                schedule_once()
                sync_published()
                last_post_check = time.time()
        except requests.RequestException:
            log.exception("erro de rede; tento de novo")
            busy = False
        except Exception:  # noqa: BLE001
            log.exception("erro inesperado")
            busy = False
        if not busy:
            time.sleep(POLL)


if __name__ == "__main__":
    main()
