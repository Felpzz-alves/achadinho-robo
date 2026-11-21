"""Legenda queimada no vídeo: palavras com tempo -> arquivo .ass (libass)."""
import re

TAG_RE = re.compile(r"\[[^\]]*\]")


def words_from_alignment(alignment):
    """Alinhamento por caractere da ElevenLabs (with-timestamps) -> [(palavra, início, fim)]."""
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    words, cur, t0, t1, in_tag = [], "", None, None, False
    for ch, s, e in zip(chars, starts, ends):
        if ch == "[":
            in_tag = True
        if in_tag:
            if ch == "]":
                in_tag = False
            continue
        if ch.isspace():
            if cur:
                words.append((cur, t0, t1))
            cur, t0 = "", None
            continue
        if t0 is None:
            t0 = s
        cur += ch
        t1 = e
    if cur:
        words.append((cur, t0, t1))
    return words


def words_even(text, total_seconds):
    """Sem tempos reais: espalha as palavras do roteiro pela duração da narração."""
    tokens = TAG_RE.sub(" ", text or "").split()
    if not tokens or total_seconds <= 0:
        return []
    weights = [len(t) + 2 for t in tokens]
    scale = total_seconds / sum(weights)
    out, t = [], 0.0
    for tok, w in zip(tokens, weights):
        out.append((tok, t, t + w * scale))
        t += w * scale
    return out


def _ts(sec):
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc(text):
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


COLORS = {  # ASS usa &HBBGGRR
    "branco": "&H00FFFFFF", "amarelo": "&H0000E5FF", "verde": "&H0057E36B",
    "rosa": "&H00B469FF", "azul": "&H00FFB43C",
}
FONTS = {"moderna": "DejaVu Sans", "classica": "Liberation Sans", "elegante": "Liberation Serif"}
MARGIN_V = {"baixo": 560, "meio": 860, "alto": 1320}


def write_ass(words, path, opcoes=None, max_words=3):
    """Blocos de até 3 palavras no estilo escolhido pelo cliente (fora da caixa do gancho)."""
    o = opcoes or {}
    estilo = o.get("estilo") or "contorno"
    cor = COLORS.get(o.get("cor") or "branco", COLORS["branco"])
    font = FONTS.get(o.get("fonte") or "moderna", FONTS["moderna"])
    margin = MARGIN_V.get(o.get("posicao") or "baixo", MARGIN_V["baixo"])
    upper = o.get("maiusculas", True) is not False
    white = COLORS["branco"]
    if estilo == "caixa":
        # BorderStyle 3 = caixa opaca atrás do texto
        style = f"{font},74,{cor},{cor},&H00000000,&H50000000,-1,0,0,0,100,100,0,0,3,18,0"
    elif estilo == "simples":
        style = f"{font},62,{cor},{cor},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,0,3"
    elif estilo == "destaque":
        style = f"{font},80,{white},{white},&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2"
    else:
        style = f"{font},78,{cor},{cor},&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2"
    lines = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Legenda,{style},2,80,80,{margin},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    chunk = []

    def fmt(word):
        return _esc(word.upper() if upper else word)

    def flush():
        if not chunk:
            return
        end = chunk[-1][2] + 0.05
        if estilo == "destaque":
            # uma linha por palavra falada, com a palavra atual na cor escolhida
            for i, (_, s, e) in enumerate(chunk):
                e2 = chunk[i + 1][1] if i + 1 < len(chunk) else end
                text = " ".join(
                    ("{\\c" + cor + "&}" + fmt(w) + "{\\c" + white + "&}") if j == i else fmt(w)
                    for j, (w, _, _) in enumerate(chunk)
                )
                lines.append(f"Dialogue: 0,{_ts(s)},{_ts(e2)},Legenda,,0,0,0,,{text}")
        else:
            text = " ".join(fmt(w) for w, _, _ in chunk)
            lines.append(f"Dialogue: 0,{_ts(chunk[0][1])},{_ts(end)},Legenda,,0,0,0,,{text}")
        chunk.clear()

    for w in words:
        chunk.append(w)
        if len(chunk) >= max_words or re.search(r"[.!?,]$", w[0]):
            flush()
    flush()
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path
