"""Extrai o Sub ID da Shopee do link de destino de um anúncio (inclusive link curto s.shopee)."""
import re
from urllib.parse import urlparse, parse_qs

import requests

_cache = {}
_CURTOS = ("s.shopee.com.br", "shope.ee", "s.shopee.com", "shp.ee")


def _expandir(url):
    if url in _cache:
        return _cache[url]
    final = url
    try:
        r = requests.get(url, allow_redirects=True, timeout=20, stream=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        final = r.url
        r.close()
    except requests.RequestException:
        pass
    _cache[url] = final
    return final


def de_link(url):
    """Retorna o Sub ID ('' se não houver). Shopee guarda os Sub IDs em utm_content=sub1-sub2-..."""
    url = (url or "").strip()
    if not url:
        return ""
    host = (urlparse(url).hostname or "").lower()
    if host in _CURTOS:
        url = _expandir(url)
    qs = parse_qs(urlparse(url).query)
    for key in ("sub_id", "subid", "sub_id1", "subId", "subid1"):
        if qs.get(key) and qs[key][0].strip():
            return qs[key][0].strip()
    content = (qs.get("utm_content") or [""])[0]
    partes = [p for p in re.split(r"-+", content) if p.strip()]
    return "-".join(partes)
