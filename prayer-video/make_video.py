#!/usr/bin/env python3
"""يولّد فيديو قصير (1080x1920) عن فوائد الصلاة باستخدام Pillow + ffmpeg."""
import math, random, subprocess, sys, os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1080, 1920, 30
FONT_DIR = sys.argv[1] if len(sys.argv) > 1 else "fonts"
OUT = sys.argv[2] if len(sys.argv) > 2 else "prayer_benefits.mp4"
REG = os.path.join(FONT_DIR, "Amiri-Regular.ttf")
BOLD = os.path.join(FONT_DIR, "Amiri-Bold.ttf")
RAQM = ImageFont.Layout.RAQM

GOLD = (232, 196, 110)
CREAM = (250, 244, 228)
MUTED = (180, 200, 190)

def font(path, size):
    return ImageFont.truetype(path, size, layout_engine=RAQM)

# ---------------- المحتوى ----------------
SCENES = [
    dict(kind="title", dur=5.5),
    dict(kind="verse", dur=7, label="قال الله تعالى",
         body="إِنَّ الصَّلَاةَ تَنْهَىٰ عَنِ الْفَحْشَاءِ وَالْمُنكَرِ",
         ref="[العنكبوت: 45]"),
    dict(kind="benefit", dur=7, n="١", title="صلة بين العبد وربه",
         body="خمس مرات في اليوم تقف بين يدي الله، تناجيه وتدعوه، فيقرب منك وتقرب منه"),
    dict(kind="benefit", dur=7.5, n="٢", title="طمأنينة القلب",
         body="أَلَا بِذِكْرِ اللَّهِ تَطْمَئِنُّ الْقُلُوبُ",
         ref="[الرعد: 28]", quran=True),
    dict(kind="benefit", dur=9.5, n="٣", title="تكفير الذنوب",
         body="أرأيتم لو أن نهرًا بباب أحدكم يغتسل فيه كل يوم خمس مرات، هل يبقى من دَرَنه شيء؟ … فذلك مثل الصلوات الخمس، يمحو الله بهن الخطايا",
         ref="متفق عليه"),
    dict(kind="benefit", dur=7.5, n="٤", title="تنظيم الوقت والحياة",
         body="إِنَّ الصَّلَاةَ كَانَتْ عَلَى الْمُؤْمِنِينَ كِتَابًا مَّوْقُوتًا",
         ref="[النساء: 103]", quran=True),
    dict(kind="benefit", dur=7.5, n="٥", title="عون على الهموم والصعاب",
         body="وَاسْتَعِينُوا بِالصَّبْرِ وَالصَّلَاةِ",
         ref="[البقرة: 45]", quran=True),
    dict(kind="benefit", dur=7, n="٦", title="الطهارة والنظافة",
         body="الوضوء خمس مرات يوميًا يحفظ نظافة الجسد، ويجدد النشاط والحيوية"),
    dict(kind="benefit", dur=7, n="٧", title="فوائد للجسد",
         body="القيام والركوع والسجود حركات لطيفة تنشّط الدورة الدموية وتليّن المفاصل"),
    dict(kind="benefit", dur=9, n="٨", title="أول ما يُحاسَب عليه العبد",
         body="إن أول ما يُحاسَب به العبد يوم القيامة من عمله صلاتُه، فإن صلحت فقد أفلح وأنجح",
         ref="رواه الترمذي"),
    dict(kind="closing", dur=7),
]

# ---------------- أدوات الرسم ----------------
def wrap(draw, text, fnt, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=fnt, direction="rtl") <= maxw or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines

def center_text(draw, y, text, fnt, fill, maxw=900, spacing=1.55, shadow=True):
    lines = wrap(draw, text, fnt, maxw)
    lh = int(fnt.size * spacing)
    for ln in lines:
        tw = draw.textlength(ln, font=fnt, direction="rtl")
        x = (W - tw) / 2
        if shadow:
            draw.text((x + 3, y + 4), ln, font=fnt, fill=(0, 0, 0, 120), direction="rtl")
        draw.text((x, y), ln, font=fnt, fill=fill, direction="rtl")
        y += lh
    return y

def text_block_height(draw, text, fnt, maxw=900, spacing=1.55):
    return len(wrap(draw, text, fnt, maxw)) * int(fnt.size * spacing)

def ornament(draw, cy, width=420, color=GOLD):
    cx = W // 2
    draw.line([(cx - width // 2, cy), (cx - 30, cy)], fill=color + (220,), width=3)
    draw.line([(cx + 30, cy), (cx + width // 2, cy)], fill=color + (220,), width=3)
    r = 16
    draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], outline=color + (255,), width=3)
    draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=color + (255,))
    for s in (-1, 1):
        x = cx + s * (width // 2 + 12)
        draw.ellipse([x - 5, cy - 5, x + 5, cy + 5], fill=color + (255,))

def star_points(cx, cy, r_out, r_in, n=8, rot=0):
    pts = []
    for i in range(n * 2):
        r = r_out if i % 2 == 0 else r_in
        a = rot + math.pi * i / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts

# ---------------- الخلفية ----------------
def make_background():
    bg = Image.new("RGB", (W, H))
    px = bg.load()
    top, bot = (6, 30, 38), (8, 62, 58)
    for y in range(H):
        t = y / H
        c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        for x in range(W):
            px[x, y] = c
    bg = bg.convert("RGBA")
    # نقش هندسي إسلامي خفيف
    pat = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(pat)
    step = 180
    for gy in range(-step, H + step, step):
        for gx in range(-step, W + step, step):
            ox = step // 2 if (gy // step) % 2 else 0
            cx, cy = gx + ox, gy
            d.polygon(star_points(cx, cy, 70, 38, 8, math.pi / 8), outline=(232, 196, 110, 26), width=2)
            d.ellipse([cx - 22, cy - 22, cx + 22, cy + 22], outline=(232, 196, 110, 18), width=2)
    bg = Image.alpha_composite(bg, pat)
    # توهج ناعم في الوسط
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([W * 0.05, H * 0.22, W * 0.95, H * 0.72], fill=(40, 120, 100, 70))
    bg = Image.alpha_composite(bg, glow.filter(ImageFilter.GaussianBlur(160)))
    # هلال
    moon = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    md = ImageDraw.Draw(moon)
    mx, my, mr = 830, 230, 70
    md.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=GOLD + (235,))
    md.ellipse([mx - mr + 32, my - mr - 14, mx + mr + 32, my + mr - 14], fill=(0, 0, 0, 0))
    moon_glow = moon.filter(ImageFilter.GaussianBlur(25))
    bg = Image.alpha_composite(bg, moon_glow)
    bg = Image.alpha_composite(bg, moon)
    # صورة ظلية لمسجد في الأسفل
    sil = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sil)
    col = (3, 18, 22, 255)
    base = H - 110
    sd.rectangle([0, base, W, H], fill=col)
    sd.rectangle([300, base - 150, 780, base], fill=col)
    sd.ellipse([390, base - 370, 690, base - 70], fill=col)          # القبة الكبرى
    sd.polygon([(540, base - 450), (528, base - 368), (552, base - 368)], fill=col)
    sd.ellipse([240, base - 230, 390, base - 80], fill=col)        # قباب جانبية
    sd.ellipse([690, base - 230, 840, base - 80], fill=col)
    for mxp in (110, 970):                                          # المآذن
        sd.rectangle([mxp - 26, base - 520, mxp + 26, base], fill=col)
        sd.rectangle([mxp - 40, base - 400, mxp + 40, base - 385], fill=col)
        sd.polygon([(mxp - 30, base - 520), (mxp + 30, base - 520), (mxp, base - 610)], fill=col)
    # نوافذ مضاءة
    for wx in range(340, 760, 60):
        sd.rounded_rectangle([wx, base - 110, wx + 26, base - 50], radius=15, fill=(232, 196, 110, 150))
    bg = Image.alpha_composite(bg, sil)
    return bg

# ---------------- طبقات المشاهد ----------------
def render_scene(sc):
    L = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(L)
    k = sc["kind"]
    if k == "title":
        center_text(d, 520, "بسم الله الرحمن الرحيم", font(REG, 54), MUTED)
        ornament(d, 680)
        center_text(d, 740, "فوائد الصلاة", font(BOLD, 150), GOLD)
        ornament(d, 1030)
        center_text(d, 1080, "عمود الدين ونور المؤمن", font(REG, 64), CREAM)
    elif k == "verse":
        center_text(d, 470, sc["label"], font(REG, 60), MUTED)
        ornament(d, 600)
        fb = font(BOLD, 96)
        y = center_text(d, 680, sc["body"], fb, GOLD, maxw=880, spacing=1.7)
        center_text(d, y + 30, sc["ref"], font(REG, 54), MUTED)
    elif k == "benefit":
        # شارة الرقم
        cx, cy = W // 2, 380
        d.polygon(star_points(cx, cy, 95, 72, 8, math.pi / 8), fill=(10, 50, 52, 255), outline=GOLD + (255,), width=4)
        nf = font(BOLD, 84)
        tw = d.textlength(sc["n"], font=nf)
        d.text((cx - tw / 2, cy - 72), sc["n"], font=nf, fill=GOLD)
        y = center_text(d, 510, sc["title"], font(BOLD, 96), GOLD, maxw=950)
        ornament(d, y + 30)
        quran = sc.get("quran")
        fb = font(BOLD if quran else REG, 80 if quran else 62)
        y = center_text(d, y + 90, sc["body"], fb, CREAM, maxw=900, spacing=1.75 if quran else 1.7)
        if sc.get("ref"):
            center_text(d, y + 20, sc["ref"], font(REG, 50), MUTED)
    elif k == "closing":
        center_text(d, 430, "قال رسول الله ﷺ", font(REG, 60), MUTED)
        ornament(d, 560)
        center_text(d, 620, "أرِحْنا بها يا بلال", font(BOLD, 110), GOLD)
        center_text(d, 820, "رواه أبو داود", font(REG, 48), MUTED)
        ornament(d, 950)
        center_text(d, 1010, "حافظ على صلاتك", font(BOLD, 100), CREAM)
        center_text(d, 1170, "فهي راحة قلبك ونور دربك", font(REG, 64), CREAM)
    return L

# ---------------- الجزيئات ----------------
random.seed(7)
PARTS = [dict(x=random.uniform(0, W), y=random.uniform(0, H), r=random.uniform(1.5, 4.5),
              v=random.uniform(12, 40), ph=random.uniform(0, 6.28)) for _ in range(70)]

def particles(t):
    L = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(L)
    for p in PARTS:
        y = (p["y"] - p["v"] * t) % H
        x = p["x"] + 18 * math.sin(t * 0.6 + p["ph"])
        a = int(110 + 90 * math.sin(t * 1.5 + p["ph"]))
        r = p["r"]
        d.ellipse([x - r, y - r, x + r, y + r], fill=GOLD + (max(a, 0),))
    return L

def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)

def main():
    bg = make_background()
    layers = [render_scene(s) for s in SCENES]
    total = sum(s["dur"] for s in SCENES)
    nframes = int(total * FPS)
    starts, acc = [], 0.0
    for s in SCENES:
        starts.append(acc); acc += s["dur"]

    # صوت هادئ: نسيم ناعم (ضوضاء مفلترة) مع تلاشي في البداية والنهاية
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-f", "lavfi", "-i", f"anoisesrc=color=brown:amplitude=0.25:d={total}",
           "-filter_complex",
           f"[1:a]lowpass=f=500,highpass=f=60,volume=0.35,tremolo=f=0.12:d=0.5,"
           f"afade=t=in:d=2,afade=t=out:st={total-2.5}:d=2.5[a]",
           "-map", "0:v", "-map", "[a]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", OUT]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    fade = 0.8
    for f in range(nframes):
        t = f / FPS
        frame = Image.alpha_composite(bg, particles(t))
        for i, s in enumerate(SCENES):
            lt = t - starts[i]
            if lt < -0.01 or lt > s["dur"]:
                continue
            a = ease(lt / fade) * ease((s["dur"] - lt) / fade)
            if i == 0: a = ease((s["dur"] - lt) / fade) * ease(lt / 1.2)
            if i == len(SCENES) - 1: a = ease(lt / fade) * ease((s["dur"] - lt) / 1.5)
            if a <= 0: continue
            off = int((1 - ease(lt / 1.0)) * 40)          # انزلاق خفيف للأعلى
            lay = layers[i]
            if off:
                lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); lay.paste(layers[i], (0, off))
            if a < 1:
                al = lay.getchannel("A").point(lambda v, a=a: int(v * a))
                lay = lay.copy(); lay.putalpha(al)
            frame = Image.alpha_composite(frame, lay)
        ff.stdin.write(frame.convert("RGB").tobytes())
        if f % 300 == 0:
            print(f"{f}/{nframes}", flush=True)
    ff.stdin.close(); ff.wait()
    print("done:", OUT)

if __name__ == "__main__":
    main()
