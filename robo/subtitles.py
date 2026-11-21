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


def write_ass(words, path, max_words=3):
    """Blocos de até 3 palavras, brancos com contorno preto, na faixa de baixo (fora do gancho)."""
    lines = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Legenda,DejaVu Sans,78,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,"
        "-1,0,0,0,100,100,0,0,1,6,2,2,80,80,560,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    chunk = []

    def flush():
        if not chunk:
            return
        text = " ".join(w for w, _, _ in chunk).upper()
        lines.append(f"Dialogue: 0,{_ts(chunk[0][1])},{_ts(chunk[-1][2] + 0.05)},Legenda,,0,0,0,,{_esc(text)}")
        chunk.clear()

    for w in words:
        chunk.append(w)
        if len(chunk) >= max_words or re.search(r"[.!?,]$", w[0]):
            flush()
    flush()
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path
