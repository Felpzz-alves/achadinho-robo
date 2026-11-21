"""Caixas de gancho (headline) dos 10 modelos do app, desenhadas como PNG 1080 de largura.

O drawtext do ffmpeg não desenha emoji colorido, por isso tudo vira imagem aqui.
"""
from PIL import Image, ImageDraw, ImageFont

FONTS = {
    "sans": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "serif_italic": "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    "serif_bold": "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
}
EMOJI_FONT = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"

# id do modelo -> fundo, cor do texto, fonte, raio da borda, contorno
STYLES = {
    "classico": dict(bg=(255, 255, 255, 255), fg=(0, 0, 0), font="sans", radius=26),
    "editorial": dict(bg=(255, 255, 255, 255), fg=(0, 0, 0), font="serif_italic", radius=0),
    "shopee": dict(bg=(238, 77, 45, 255), fg=(255, 255, 255), font="sans", radius=0),
    "preco": dict(bg=(255, 214, 0, 255), fg=(20, 20, 20), font="sans", radius=40),
    "neon": dict(bg=(255, 46, 147, 255), fg=(255, 255, 255), font="sans", radius=30),
    "luxo": dict(bg=(250, 246, 238, 245), fg=(60, 45, 30), font="serif_italic", radius=4),
    "postit": dict(bg=(255, 241, 118, 255), fg=(30, 30, 30), font="sans", radius=2),
    "preto": dict(bg=(15, 15, 15, 235), fg=(255, 255, 255), font="serif_bold", radius=18),
    "contorno": dict(bg=(255, 255, 255, 255), fg=(0, 0, 0), font="sans", radius=22, outline=(238, 77, 45), outline_w=10),
    "selo": dict(bg=(255, 255, 255, 255), fg=(0, 0, 0), font="sans", radius=26, badge="ACHADINHO"),
}


def _emojis(text, size):
    ef = ImageFont.truetype(EMOJI_FONT, 109)
    out = []
    for ch in text:
        if ch.isspace() or ch in "️‍":
            continue
        t = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        ImageDraw.Draw(t).text((0, 0), ch, font=ef, embedded_color=True)
        bb = t.getbbox()
        if not bb:
            continue
        t = t.crop(bb)
        out.append(t.resize((max(1, int(size * t.width / t.height)), size), Image.LANCZOS))
    return out


def split_lines(text, max_chars=24):
    words = text.split()
    if len(" ".join(words)) <= max_chars:
        return [" ".join(words)]
    best, best_diff = None, 10**9
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        diff = abs(len(a) - len(b))
        if diff < best_diff:
            best, best_diff = [a, b], diff
    return best


def render(out_path, text, emojis, template="classico", width=1080):
    """Desenha a caixa e devolve a altura do PNG."""
    st = STYLES.get(template, STYLES["classico"])
    lines = split_lines(text)
    fs = 58 if st["font"] == "sans" else 62
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    while True:
        f = ImageFont.truetype(FONTS[st["font"]], fs)
        es = int(fs * 1.05)
        ems = _emojis(emojis, es)
        def lw(i):
            w = probe.textlength(lines[i], font=f)
            if i == len(lines) - 1 and ems:
                w += sum(e.width + 6 for e in ems) + 10
            return w
        maxw = max(lw(i) for i in range(len(lines)))
        if maxw <= width - 2 * 40 - 2 * 36 or fs <= 34:
            break
        fs -= 2
    lh = int(fs * 1.3)
    padx, pady = 36, int(fs * 0.5)
    badge_h = 44 if st.get("badge") else 0
    bw = int(min(width - 80, max(maxw + 2 * padx, width * 0.72)))
    bh = lh * len(lines) + 2 * pady
    img = Image.new("RGBA", (width, bh + badge_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0 = (width - bw) // 2
    box = [x0, badge_h, x0 + bw - 1, badge_h + bh - 1]
    if st.get("outline"):
        d.rounded_rectangle(box, radius=st["radius"], fill=st["bg"], outline=st["outline"], width=st["outline_w"])
    else:
        d.rounded_rectangle(box, radius=st["radius"], fill=st["bg"])
    if st.get("badge"):
        bf = ImageFont.truetype(FONTS["sans"], 28)
        tw = d.textlength(st["badge"], font=bf)
        bx = (width - tw) // 2 - 18
        d.rounded_rectangle([bx, 0, bx + tw + 36, badge_h + 10], radius=14, fill=(238, 77, 45, 255))
        d.text((bx + 18, 6), st["badge"], font=bf, fill=(255, 255, 255))
    for i, txt in enumerate(lines):
        x = (width - lw(i)) / 2
        y = badge_h + pady + i * lh
        d.text((x, y + (lh - fs) // 2 - 4), txt, font=f, fill=st["fg"])
        if i == len(lines) - 1:
            x += probe.textlength(txt, font=f) + 10
            for e in ems:
                img.alpha_composite(e, (int(x), int(y + (lh - es) // 2)))
                x += e.width + 6
    img.save(out_path)
    return img.height
