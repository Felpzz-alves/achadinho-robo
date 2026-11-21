"""Montagem do vídeo no padrão Achadinho com ffmpeg."""
import json
import re
import subprocess

from . import hooks

W, H, FPS = 1080, 1920, 30
HOOK_TOP = int(H * 0.11)
WATERMARK_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF️‍]+"
)


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {p.stderr[-800:]}")
    return p.stdout


def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path])
    return float(json.loads(out)["format"]["duration"])


def headline_from(roteiro, nome):
    """Primeira frase do roteiro vira a headline; sem roteiro, usa o nome do produto."""
    text = (roteiro or "").strip()
    text = re.sub(r"\[[^\]]*\]", "", text).strip()  # tira tags do eleven_v4
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0] if text else ""
    first = first.strip(" .!?")
    if not first:
        first = f"Olha esse achadinho: {nome}" if nome else "Olha esse achadinho da Shopee"
    emojis = "".join(EMOJI_RE.findall(first)) or "🏠✨"
    first = EMOJI_RE.sub("", first).strip()
    words = first.split()
    if len(words) > 10:
        first = " ".join(words[:10])
    return first, emojis[:4]


def _watermark_filter(handle):
    if not handle:
        return ""
    h = handle if handle.startswith("@") else "@" + handle
    h = h.replace("\\", "").replace("'", "").replace(":", "\\:")
    # muda de posição a cada 2,5 s, sempre fora dos 14% de cima e 35% de baixo
    xs = ["w*0.08", "w-tw-w*0.08", "(w-tw)/2", "w*0.12"]
    ys = ["h*0.30", "h*0.42", "h*0.55", "h*0.36"]
    def pick(vals):
        k = "mod(floor(t/2.5),4)"
        return "+".join(f"eq({k},{i})*({v})" for i, v in enumerate(vals))
    return (
        f",drawtext=fontfile={WATERMARK_FONT}:text='{h}':fontsize=40:"
        f"fontcolor=white@0.75:shadowcolor=black@0.4:shadowx=2:shadowy=2:"
        f"x='{pick(xs)}':y='{pick(ys)}'"
    )


def build_preview(raw, out, hook_png, handle, target_seconds=None):
    """Vídeo 9:16 sem áudio, com gancho e marca d'água. Se target_seconds, faz loop até a duração."""
    src = duration(raw)
    length = target_seconds or src
    loops = max(0, int(length // src)) if target_seconds else 0
    vf = (
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
        f"eq=contrast=1.05:saturation=1.08,setsar=1{_watermark_filter(handle)}[base];"
        f"[base][1:v]overlay=0:{HOOK_TOP}[v]"
    )
    run([
        "ffmpeg", "-y", "-stream_loop", str(loops), "-i", raw, "-i", hook_png,
        "-filter_complex", vf, "-map", "[v]", "-an", "-t", f"{length:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
        "-map_metadata", "-1", "-movflags", "+faststart", out,
    ])


def build_final(raw, voice, out, hook_png, handle):
    """Duração = narração + 0,4 s; o bruto repete se for mais curto. Áudio em -14 LUFS."""
    target = duration(voice) + 0.4
    silent = out + ".silent.mp4"
    build_preview(raw, silent, hook_png, handle, target_seconds=target)
    run([
        "ffmpeg", "-y", "-i", silent, "-i", voice,
        "-filter_complex", "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,apad[a]",
        "-map", "0:v", "-map", "[a]", "-t", f"{target:.2f}",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-map_metadata", "-1", "-movflags", "+faststart", out,
    ])


def make_hook(path, roteiro, nome, template):
    text, emojis = headline_from(roteiro, nome)
    hooks.render(path, text, emojis, template)
    return text + " " + emojis
