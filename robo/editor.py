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
    if p.returncode < 0 or p.returncode in (137, 139):
        raise RuntimeError(
            "O servidor do robô ficou sem memória ao editar este vídeo (processo encerrado). "
            "Tente de novo; se repetir, aumente a memória do serviço no Railway."
        )
    if p.returncode != 0:
        lines = [l for l in p.stderr.splitlines() if l.strip()]
        useful = [l for l in lines if any(k in l.lower() for k in ("error", "invalid", "no such", "failed", "unable", "cannot", "not found", "could not"))]
        detail = " | ".join((useful or lines)[-4:])
        raise RuntimeError(f"ffmpeg falhou (código {p.returncode}): {detail[:600]}")
    return p.stdout


def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path])
    return float(json.loads(out)["format"]["duration"])


def clean_text(text):
    """Tira markdown, aspas, rótulos tipo **Desejo** e tags [excited] de um texto."""
    t = text or ""
    t = re.sub(r"^\s*\*\*[^*\n]{1,40}\*\*\s*", "", t)  # rótulo em linha própria
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = re.sub(r"[*_#`\"“”«»]", "", t)
    return re.sub(r"\s+", " ", t).strip()


FASHION = re.compile(r"vestid|blus|camis|saia|cal[çc]a|short|look|conjunto|alfaiat|cropped|top|body|moda|roupa|sutiã|lingerie|colete|jaqueta|casaco", re.I)
BAGS = re.compile(r"bolsa|mochila|carteira", re.I)
SHOES = re.compile(r"t[eê]nis|sand[aá]lia|sapat|bota|chinelo", re.I)


def emojis_for(*hints):
    h = " ".join(x for x in hints if x)
    if BAGS.search(h):
        return "👜✨"
    if SHOES.search(h):
        return "👟✨"
    if FASHION.search(h):
        return "👗✨"
    return "🛍️✨"


def fallback_headline(nome, categoria=""):
    nome = clean_text(nome) or "achadinho"
    text = f"Achei o achadinho mais lindo da Shopee" if not nome else f"Olha esse achadinho: {nome}"
    words = text.split()
    return " ".join(words[:9]), emojis_for(nome, categoria)


def extract_frames(raw, workdir, count=4):
    """Tira alguns quadros espalhados do vídeo (JPEG pequenos) para a IA olhar o produto."""
    total = duration(raw)
    paths = []
    for i in range(count):
        t = total * (i + 1) / (count + 1)
        out = f"{workdir}/frame{i}.jpg"
        run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", raw, "-frames:v", "1",
             "-vf", "scale=512:-2", "-q:v", "5", out])
        paths.append(out)
    return paths


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
        "ffmpeg", "-y", "-threads", "2", "-stream_loop", str(loops), "-i", raw, "-i", hook_png,
        "-filter_complex", vf, "-filter_complex_threads", "1", "-map", "[v]", "-an", "-t", f"{length:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
        "-threads", "2", "-x264-params", "rc-lookahead=10:ref=2:sync-lookahead=0",
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


def make_hook(path, text, emojis, template):
    text = clean_text(text)
    emojis = "".join(EMOJI_RE.findall(emojis or "")) or "✨"
    hooks.render(path, text, emojis[:4], template)
    return text + " " + emojis
