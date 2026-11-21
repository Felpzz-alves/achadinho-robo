"""Narração: voz do cliente (áudio enviado), biblioteca ou ElevenLabs com a chave do próprio cliente."""
import base64
import hashlib
import os
import re

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import supa

DEFAULT_VOICE = "ORgG8rwdAiMYRug8RJwR"  # Ana Alice - Friendly and Clear
MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_v4")


def decrypt_user_key(ciphertext):
    """Mesmo formato do app: base64(iv[12] + AES-GCM), chave = SHA-256 do segredo."""
    secret = os.environ["USER_CREDENTIAL_ENCRYPTION_SECRET"].encode()
    raw = base64.b64decode(ciphertext)
    return AESGCM(hashlib.sha256(secret).digest()).decrypt(raw[:12], raw[12:], None).decode()


def elevenlabs(user_id, text, dest, voice_id=None):
    cred = supa.one("user_credentials", {"user_id": f"eq.{user_id}", "select": "ciphertext"})
    if not cred:
        raise RuntimeError("Conecte sua conta ElevenLabs em Conectar contas para gerar a voz.")
    key = decrypt_user_key(cred["ciphertext"])
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id or DEFAULT_VOICE}",
        headers={"xi-api-key": key, "Accept": "audio/mpeg"},
        json={"text": text, "model_id": MODEL},
        timeout=180,
    )
    if r.status_code == 401:
        raise RuntimeError("A chave da ElevenLabs foi recusada. Salve a chave de novo em Conectar contas.")
    if r.status_code == 400 and MODEL != "eleven_multilingual_v2":
        # modelo indisponível na conta do cliente: tenta o multilíngue, sem tags de direção
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id or DEFAULT_VOICE}",
            headers={"xi-api-key": key, "Accept": "audio/mpeg"},
            json={"text": re.sub(r"\[[^\]]*\]", "", text), "model_id": "eleven_multilingual_v2"},
            timeout=180,
        )
    if not r.ok:
        raise RuntimeError(f"ElevenLabs recusou a geração ({r.status_code}). Confira seus créditos.")
    with open(dest, "wb") as f:
        f.write(r.content)
    return dest


def get_voice(product, workdir):
    """Devolve o caminho do áudio da narração, ou None quando ainda não há narração."""
    mode = product.get("voice_mode") or "minha"
    if mode in ("minha", "biblioteca"):
        if not product.get("audio_path"):
            return None
        ext = product["audio_path"].rsplit(".", 1)[-1]
        return supa.download(product["audio_path"], f"{workdir}/voz.{ext}")
    if mode == "elevenlabs":
        text = (product.get("roteiro") or "").strip()
        if not text:
            raise RuntimeError("Escreva ou gere o roteiro antes de criar a voz com ElevenLabs.")
        path = elevenlabs(product["user_id"], text, f"{workdir}/voz.mp3", product.get("voice_id"))
        stored = f"{product['user_id']}/edits/{product['id']}/voz.mp3"
        supa.upload(stored, path, "audio/mpeg")
        product["audio_path"] = stored
        return path
    return None
