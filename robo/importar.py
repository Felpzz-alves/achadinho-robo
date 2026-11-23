"""Importação única de vídeos finais já editados (lista em import_lote.json).

Baixa cada vídeo e sobe no armazenamento do app no caminho final_path do produto.
Temporário: apague import_lote.json depois que terminar.
"""
import json
import logging
import os
import tempfile

import requests

from . import supa

log = logging.getLogger("robo.importar")
LISTA = os.path.join(os.path.dirname(__file__), "import_lote.json")


def rodar():
    if not os.path.exists(LISTA):
        return
    itens = json.load(open(LISTA))
    ok = 0
    for it in itens:
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
                with requests.get(it["url"], stream=True, timeout=300) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(1 << 20):
                        tmp.write(chunk)
                tmp.flush()
                supa.upload(it["path"], tmp.name)
            ok += 1
        except Exception:  # noqa: BLE001
            log.exception("falha ao importar %s", it.get("path"))
    log.info("importação: %d de %d vídeos enviados", ok, len(itens))
