"""Narração: voz do cliente (áudio enviado), biblioteca ou ElevenLabs com a chave do próprio cliente."""
import os
import re

import base64

import requests

from . import supa, subtitles

DEFAULT_VOICE = "ORgG8rwdAiMYRug8RJwR"  # Ana Alice - Friendly and Clear
MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_v4")  # padrão da skill edicao-achadinho
# modelos que entendem tags de direção como [excited]
_TAG_MODELS = ("eleven_v3", "eleven_v4")


def _settings(model):
    """Voz de blogueira empolgada: pouca estabilidade = mais emoção e variação."""
    if model in _TAG_MODELS:
        return {"stability": 0.0, "similarity_boost": 0.75, "use_speaker_boost": True}
    return {"stability": 0.3, "similarity_boost": 0.75, "style": 0.65, "use_speaker_boost": True}


def animar(text):
    """Põe tags de empolgação quando o roteiro não traz nenhuma."""
    if re.search(r"\[[a-z ]{2,20}\]", text):
        return text
    frases = re.split(r"(?<=[!?.])\s+", text.strip())
    out = []
    for i, f in enumerate(frases):
        if i == 0:
            out.append(f"[excited] {f}")
        elif i == 2 and f.endswith("!"):
            out.append(f"[impressed] {f}")
        elif i == len(frases) - 1:
            out.append(f"[playful] {f}")
        else:
            out.append(f)
    return " ".join(out)


def _tts(key, voice_id, text, model):
    if model in _TAG_MODELS:
        text = animar(text)
    else:
        text = re.sub(r"\[[^\]]*\]\s*", "", text)
    return requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id or DEFAULT_VOICE}/with-timestamps",
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        json={"text": text, "model_id": model, "voice_settings": _settings(model)},
        timeout=180,
    )


def elevenlabs(user_id, text, dest, voice_id=None):
    """Gera a voz e devolve (caminho, palavras com tempo) para a legenda."""
    key = supa.elevenlabs_key(user_id)
    if not key:
        raise RuntimeError("Conecte sua conta ElevenLabs em Conectar contas para gerar a voz.")
    r = _tts(key, voice_id, text, MODEL)
    if r.status_code == 401:
        raise RuntimeError("A chave da ElevenLabs foi recusada. Salve a chave de novo em Conectar contas.")
    for alt in ("eleven_v4", "eleven_v3", "eleven_multilingual_v2"):
        if r.status_code not in (400, 422) or alt == MODEL:
            continue
        # modelo indisponível na conta do cliente: tenta o próximo
        r = _tts(key, voice_id, text, alt)
    if not r.ok:
        raise RuntimeError(f"ElevenLabs recusou a geração ({r.status_code}). Confira seus créditos.")
    data = r.json()
    with open(dest, "wb") as f:
        f.write(base64.b64decode(data["audio_base64"]))
    words = subtitles.words_from_alignment(data.get("alignment") or data.get("normalized_alignment") or {})
    return dest, words


def transcribe(user_id, audio_path):
    """Tempos das palavras de uma voz gravada, pela ElevenLabs do cliente. Sem chave: None."""
    try:
        key = supa.elevenlabs_key(user_id)
    except Exception:  # noqa: BLE001
        key = None
    if not key:
        return None
    with open(audio_path, "rb") as f:
        r = requests.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": key},
            data={"model_id": "scribe_v1", "language_code": "por"},
            files={"file": f},
            timeout=300,
        )
    if not r.ok:
        return None
    return [(w["text"].strip(), w["start"], w["end"]) for w in r.json().get("words", [])
            if w.get("type", "word") == "word" and w.get("text", "").strip()]


def get_voice(product, workdir):
    """Devolve o caminho do áudio da narração, ou None quando ainda não há narração."""
    mode = product.get("voice_mode") or "minha"
    if mode in ("minha", "biblioteca"):
        if not product.get("audio_path"):
            return None
        ext = product["audio_path"].rsplit(".", 1)[-1]
        path = supa.download(product["audio_path"], f"{workdir}/voz.{ext}")
        if product.get("legenda_video"):
            product["_words"] = transcribe(product["user_id"], path)
        return path
    if mode == "elevenlabs":
        from .editor import clean_text
        raw_text = product.get("roteiro") or ""
        # mantém as tags de direção do eleven_v4 ([excited]...), tira markdown e aspas
        text = re.sub(r"^\s*\*\*[^*\n]{1,40}\*\*\s*", "", raw_text)
        text = re.sub(r"[*_#`\"“”«»]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            raise RuntimeError("Escreva ou gere o roteiro antes de criar a voz com ElevenLabs.")
        path, product["_words"] = elevenlabs(product["user_id"], text, f"{workdir}/voz.mp3", product.get("voice_id"))
        import time
        # nome único: cada narração gerada fica guardada na biblioteca de áudios do cliente
        stored = f"{product['user_id']}/edits/{product['id']}/voz-{int(time.time())}.mp3"
        supa.upload(stored, path, "audio/mpeg")
        product["audio_path"] = stored
        return path
    return None
