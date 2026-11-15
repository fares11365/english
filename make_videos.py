#!/usr/bin/env python3
"""English with Stick Man - generates animated stick-figure English lessons.

Each episode is a short dialogue between Sam and Mia with English voice-over,
subtitles, and a "listen and repeat" recap of the key phrases.

Usage:  python3 make_videos.py            # render every episode
        python3 make_videos.py cafe       # render episodes whose slug matches
        python3 make_videos.py --tiktok   # vertical 1080x1920 versions in videos/tiktok

Needs: ffmpeg, Pillow, numpy, piper-tts (pip install piper-tts).
Voices are downloaded to ./voices on first run.
"""
import hashlib, math, os, subprocess, sys, urllib.request, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "videos")
VOICES = os.path.join(ROOT, "voices")
CACHE = os.path.join(ROOT, ".cache")
W, H, S, FPS, SR = 1280, 720, 2, 24, 22050
VW, VH, SY = 720, 1280, 250  # vertical (TikTok) page, and where the stage sits on it
NAVY = (24, 30, 60)
GY = 545  # ground line
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

CAST = {
    "sam": dict(name="Sam", color=(31, 59, 115), accent=(52, 120, 220), voice="ryan"),
    "mia": dict(name="Mia", color=(120, 30, 70), accent=(230, 70, 130), voice="amy"),
}
INK = (40, 40, 48)

# ----------------------------------------------------------------- speech --
_voices = {}


def voice(name):
    if name not in _voices:
        from piper import PiperVoice
        os.makedirs(VOICES, exist_ok=True)
        base = f"en_US-{name}-medium.onnx"
        for f in (base, base + ".json"):
            p = os.path.join(VOICES, f)
            if not os.path.exists(p):
                url = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/"
                       f"en/en_US/{name}/medium/{f}")
                print("downloading", f)
                urllib.request.urlretrieve(url, p)
        _voices[name] = PiperVoice.load(os.path.join(VOICES, base))
    return _voices[name]


def speak(who, text):
    """Return mono float32 samples at SR for `text` in the character's voice."""
    vname = CAST[who]["voice"]
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, hashlib.md5(f"{vname}|{text}".encode()).hexdigest() + ".wav")
    if not os.path.exists(path):
        v = voice(vname)
        with wave.open(path, "wb") as wf:
            (v.synthesize_wav if hasattr(v, "synthesize_wav") else v.synthesize)(text, wf)
    with wave.open(path, "rb") as wf:
        assert wf.getframerate() == SR, wf.getframerate()
        a = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    return a.astype(np.float32) / 32768.0


def music(seconds):
    """A quiet plucked I-V-vi-IV loop so the video is not dead silent."""
    n = int(seconds * SR)
    out = np.zeros(n + SR, dtype=np.float32)
    chords = [(261.6, 329.6, 392.0), (196.0, 246.9, 293.7),
              (220.0, 261.6, 329.6), (174.6, 220.0, 261.6)]
    step = 0.3
    t = np.arange(int(0.9 * SR)) / SR
    i = 0
    while i * step < seconds:
        ch = chords[(i // 8) % 4]
        f = ch[(0, 1, 2, 1, 0, 2, 1, 2)[i % 8]] * (2 if i % 8 in (5, 7) else 1)
        note = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)) * np.exp(-5 * t)
        p = int(i * step * SR)
        seg = out[p:p + len(note)]
        seg += note[:len(seg)]
        i += 1
    return out[:n] * 0.035


# ---------------------------------------------------------------- drawing --
_fonts = {}


def font(size, bold=True):
    k = (size, bold)
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype(FONT_B if bold else FONT_R, int(size * S))
    return _fonts[k]


class Cv:
    """Tiny canvas that draws in stage units onto a supersampled image.

    (ox, oy) shifts everything, so the same drawing code can be placed anywhere.
    """

    def __init__(self, im, ox=0, oy=0):
        self.im, self.d, self.ox, self.oy = im, ImageDraw.Draw(im), ox, oy

    def box(self, b):
        return ((b[0] + self.ox) * S, (b[1] + self.oy) * S,
                (b[2] + self.ox) * S, (b[3] + self.oy) * S)

    def pts(self, pts):
        return [((x + self.ox) * S, (y + self.oy) * S) for x, y in pts]

    def stroke(self, pts, col, w):
        q = self.pts(pts)
        self.d.line(q, fill=col, width=int(w * S), joint="curve")
        r = w * S / 2
        for x, y in q:
            self.d.ellipse((x - r, y - r, x + r, y + r), fill=col)

    def ell(self, b, fill=None, outline=None, w=0):
        self.d.ellipse(self.box(b), fill=fill, outline=outline, width=int(w * S))

    def circle(self, c, r, fill=None, outline=None, w=0):
        self.ell((c[0] - r, c[1] - r, c[0] + r, c[1] + r), fill, outline, w)

    def arc(self, b, a0, a1, fill, w):
        self.d.arc(self.box(b), a0, a1, fill=fill, width=int(w * S))

    def rect(self, b, fill=None, outline=None, w=0, r=0):
        self.d.rounded_rectangle(self.box(b), radius=r * S, fill=fill, outline=outline,
                                 width=int(w * S))

    def poly(self, pts, fill):
        self.d.polygon(self.pts(pts), fill=fill)

    def pie(self, c, r, a0, a1, fill):
        self.d.pieslice(self.box((c[0] - r, c[1] - r, c[0] + r, c[1] + r)), a0, a1, fill=fill)

    def text(self, xy, s, size, fill=INK, anchor="la", bold=True):
        self.d.text(self.pts([xy])[0], s, font=font(size, bold), fill=fill, anchor=anchor)

    def width(self, s, size, bold=True):
        return font(size, bold).getlength(s) / S


def wrap(cv, text, size, maxw):
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if cv.width(t, size) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = word
    return lines + [cur]


def pose_for(action, t):
    """Arm angles are degrees from straight-down, swinging outward and up."""
    p = dict(front=(12 + 2 * math.sin(t * 2), 8), back=(12, 8), legs=(12, 12),
             dy=0.0, lean=0.0, nod=0.0)
    if action == "talk":
        p["front"] = (55 + 12 * math.sin(t * 5), 118 + 18 * math.sin(t * 7 + 1))
        p["nod"] = 1.5 * math.sin(t * 6)
    elif action == "wave":
        p["front"] = (150, 168 + 26 * math.sin(t * 12))
    elif action == "point":
        p["front"] = (96 + 3 * math.sin(t * 6), 96 + 3 * math.sin(t * 6))
    elif action == "point_back":
        p["back"] = (96 + 3 * math.sin(t * 6), 96 + 3 * math.sin(t * 6))
    elif action == "shrug":
        p["front"] = p["back"] = (38, 128 + 6 * math.sin(t * 5))
        p["dy"] = 3
    elif action == "think":
        p["front"] = (28, 168)
        p["nod"] = 3 * math.sin(t * 3)
    elif action == "jump":
        p["dy"] = 46 * abs(math.sin(t * 6))
        p["front"] = p["back"] = (150, 165)
    elif action == "give":
        p["front"] = (82, 92)
    elif action == "point_up":
        p["front"] = (150 + 3 * math.sin(t * 6), 158)
    elif action == "nod":
        p["nod"] = 5 * math.sin(t * 8)
    elif action == "walk":
        sw = math.sin(t * 9)
        p["legs"] = (28 * sw, -28 * sw)
        p["front"], p["back"] = (-25 * sw, -15 * sw), (25 * sw, 15 * sw)
        p["dy"] = 4 * abs(math.cos(t * 9))
        p["lean"] = 5
    return p


def draw_fig(cv, who, x, facing, action, t, mouth, k=1.12):
    c = CAST[who]
    col, acc = c["color"], c["accent"]
    p = pose_for(action, t)
    leg, torso, R, arm, lw = 92 * k, 92 * k, 33 * k, 47 * k, 9 * k
    hip = (x, GY - leg - p["dy"])
    neck = (x + facing * p["lean"], hip[1] - torso)
    head = (neck[0] + facing * p["lean"] * 0.3, neck[1] - R + 2 + p["nod"])
    sh = (neck[0], neck[1] + 12 * k)
    # shadow
    sw = 46 * k * (1 - p["dy"] / 120)
    cv.ell((x - sw, GY - 5, x + sw, GY + 9), fill=(0, 0, 0))

    def limb(side, a, b):
        a, b = math.radians(a), math.radians(b)
        el = (sh[0] + side * arm * math.sin(a), sh[1] + arm * math.cos(a))
        hd = (el[0] + side * arm * math.sin(b), el[1] + arm * math.cos(b))
        cv.stroke([sh, el, hd], col, lw)
        return hd

    limb(-facing, *p["back"])
    for a, side in zip(p["legs"], (1, -1)):
        if action != "walk":
            a *= side
        r = math.radians(a)
        foot = (hip[0] + leg * math.sin(r) * (facing if action == "walk" else 1),
                min(GY, hip[1] + leg * math.cos(r)) if p["dy"] == 0 else hip[1] + leg * math.cos(r))
        cv.stroke([hip, foot, (foot[0] + facing * 12 * k, foot[1])], col, lw)
    cv.stroke([hip, neck], col, lw)
    hand = limb(facing, *p["front"])
    # head
    if who == "mia":  # ponytail
        bx = head[0] - facing * R
        cv.stroke([(bx + facing * 6, head[1] - 14), (bx - facing * 20, head[1] + 4),
                   (bx - facing * 16, head[1] + 34)], acc, lw * 0.9)
    cv.circle(head, R, fill=(255, 255, 255), outline=col, w=lw * 0.8)
    if who == "mia":
        cv.pie(head, R - 1, 185, 355, acc)
        cv.circle((head[0] - facing * 20, head[1] - R + 6), 8, fill=(255, 210, 60))
    else:  # cap
        cv.pie(head, R + 2, 180, 360, acc)
        cv.stroke([(head[0], head[1] - 2), (head[0] + facing * (R + 20), head[1] - 2)], acc, 8)
    ex, ey = head[0] + facing * 9, head[1] + 8
    blink = (t * 0.9 + (0.37 if who == "mia" else 0)) % 3.1 < 0.12
    for dx in (-10, 10):
        if blink:
            cv.stroke([(ex + dx - 4, ey), (ex + dx + 4, ey)], INK, 3)
        else:
            cv.circle((ex + dx, ey), 4.2, fill=INK)
    my = ey + 14
    if mouth > 0.12:
        h = 3 + 9 * mouth
        cv.ell((ex - 8, my - h, ex + 8, my + h), fill=(150, 40, 50))
    else:
        cv.arc((ex - 9, my - 10, ex + 9, my + 4), 20, 160, INK, 3)
    return hand


# ----------------------------------------------------------------- scenes --
def gradient(top, bot):
    g = np.linspace(0, 1, H * S)[:, None, None]
    a = (np.array(top) * (1 - g) + np.array(bot) * g).astype(np.uint8)
    return Image.fromarray(np.repeat(a, W * S, axis=1), "RGB").convert("RGBA")


def cloud(cv, x, y, k=1.0):
    for dx, dy, r in ((0, 0, 30), (32, -12, 36), (68, 0, 30), (34, 10, 28)):
        cv.circle((x + dx * k, y + dy * k), r * k, fill=(255, 255, 255))


def scene_park():
    im = gradient((120, 195, 245), (215, 240, 255))
    cv = Cv(im)
    cv.circle((1120, 110), 60, fill=(255, 220, 90))
    cloud(cv, 180, 120), cloud(cv, 620, 80, 0.8), cloud(cv, 900, 190, 0.6)
    cv.circle((300, 620), 330, fill=(150, 205, 130))
    cv.circle((1000, 680), 400, fill=(135, 195, 120))
    cv.rect((0, 470, W, H), fill=(110, 185, 100))
    cv.poly([(0, 520), (W, 520), (W, 580), (0, 580)], fill=(225, 205, 160))
    for tx, th in ((110, 1.0), (1180, 0.85)):
        cv.rect((tx - 14, 470 - 170 * th, tx + 14, 500), fill=(120, 85, 55), r=6)
        for dx, dy, r in ((0, -210, 80), (-55, -160, 60), (55, -160, 60)):
            cv.circle((tx + dx * th, 470 + dy * th), r * th, fill=(60, 150, 80))
    for fx in range(40, W, 97):
        cv.circle((fx, 500 - (fx * 7) % 23), 5, fill=((255, 240, 120), (255, 150, 180))[fx % 2])
    return im, None


def scene_cafe():
    im = gradient((255, 232, 200), (250, 215, 175))
    cv = Cv(im)
    cv.rect((0, 500, W, H), fill=(170, 120, 85))
    for x in range(0, W, 160):
        cv.stroke([(x, 500), (x - 60, H)], (150, 104, 72), 3)
    cv.rect((90, 110, 430, 380), fill=(175, 225, 250), outline=(120, 85, 55), w=10, r=8)
    cv.stroke([(260, 115), (260, 375)], (120, 85, 55), 8)
    cloud(cv, 130, 200, 0.5)
    cv.rect((820, 70, 1140, 250), fill=(45, 60, 55), outline=(120, 85, 55), w=10, r=8)
    cv.text((980, 100), "MENU", 30, (255, 255, 255), "ma")
    for i, row in enumerate(("Coffee ...... $3", "Tea .......... $2", "Cake ........ $2")):
        cv.text((850, 140 + i * 32), row, 22, (235, 235, 215), bold=False)
    cv.text((640, 60), "STICK CAFÉ", 44, (150, 80, 50), "ma")

    def fg(cv, st):
        cv.rect((730, 420, 1150, 560), fill=(140, 90, 60), r=10)
        cv.rect((710, 400, 1170, 432), fill=(95, 60, 40), r=8)
        cv.rect((1040, 340, 1110, 400), fill=(70, 70, 80), r=6)  # till
        if st.get("cup"):
            cv.rect((772, 362, 806, 400), fill=(255, 255, 255), outline=INK, w=3, r=4)
            cv.arc((804, 370, 822, 392), 270, 90, INK, 3)
            cv.rect((772, 372, 806, 384), fill=(150, 80, 50))
        if st.get("cake"):
            cv.poly([(830, 400), (880, 400), (880, 376)], fill=(110, 65, 40))
            cv.stroke([(832, 399), (879, 377)], (255, 240, 230), 4)
    return im, fg


def scene_street():
    im = gradient((150, 205, 245), (225, 240, 250))
    cv = Cv(im)
    cloud(cv, 250, 90, 0.8), cloud(cv, 880, 70, 0.7)
    blds = [(0, 190, (235, 170, 140)), (230, 250, (170, 190, 220)), (430, 140, (240, 215, 150)),
            (690, 230, (190, 215, 180)), (900, 170, (225, 180, 200)), (1110, 240, (180, 190, 215))]
    for i, (x, top, c) in enumerate(blds):
        x2 = blds[i + 1][0] if i + 1 < len(blds) else W
        cv.rect((x, top, x2 - 8, 480), fill=c)
        for wy in range(top + 30, 380, 62):
            for wx in range(x + 28, x2 - 60, 66):
                cv.rect((wx, wy, wx + 36, wy + 40), fill=(250, 250, 235), r=3)
        cv.rect(((x + x2) / 2 - 24, 410, (x + x2) / 2 + 16, 480), fill=(110, 80, 60), r=4)
    cv.rect((440, 330, 672, 378), fill=(40, 90, 60), r=6)
    cv.text((556, 354), "BANK", 34, (255, 255, 255), "mm")
    cv.rect((0, 480, W, 585), fill=(205, 205, 205))
    cv.rect((0, 585, W, H), fill=(90, 92, 100))
    cv.stroke([(1090, 520), (1090, 300)], (90, 90, 95), 8)
    cv.poly([(1010, 300), (1090, 300), (1090, 340), (1010, 340), (985, 320)], fill=(40, 110, 200))
    cv.text((1045, 320), "Station", 17, (255, 255, 255), "mm")
    cv.poly([(1090, 350), (1170, 350), (1195, 370), (1170, 390), (1090, 390)], fill=(60, 150, 80))
    cv.text((1135, 370), "Park", 17, (255, 255, 255), "mm")
    return im, None


def scene_shop():
    im = gradient((225, 235, 250), (245, 235, 225))
    cv = Cv(im)
    cv.rect((0, 500, W, H), fill=(200, 185, 165))
    cv.text((640, 60), "STICK SHOP", 44, (60, 90, 150), "ma")
    cv.rect((70, 150, 300, 250), fill=(230, 60, 70), r=14)
    cv.text((185, 200), "SALE", 54, (255, 255, 255), "mm")
    cv.stroke([(900, 190), (1230, 190)], (110, 110, 120), 8)
    for x in (900, 1230):
        cv.stroke([(x, 190), (x, 520)], (110, 110, 120), 8)
    cols = [(52, 120, 220), (240, 190, 60), (60, 160, 100), (230, 90, 120)]
    for i, c in enumerate(cols):
        x = 950 + i * 76
        cv.stroke([(x, 190), (x, 212)], (110, 110, 120), 4)
        cv.poly([(x - 16, 212), (x + 16, 212), (x + 44, 236), (x + 30, 256), (x + 22, 248),
                 (x + 22, 330), (x - 22, 330), (x - 22, 248), (x - 30, 256), (x - 44, 236)], fill=c)
    cv.rect((70, 300, 250, 520), fill=(250, 250, 250), outline=(150, 120, 90), w=8, r=6)  # mirror
    cv.stroke([(110, 340), (160, 400)], (215, 230, 240), 6)
    return im, None


def scene_clinic():
    im = gradient((215, 240, 235), (240, 250, 245))
    cv = Cv(im)
    cv.rect((0, 500, W, H), fill=(190, 210, 205))
    cv.circle((640, 110), 52, fill=(255, 255, 255), outline=(220, 60, 70), w=6)
    cv.rect((628, 76, 652, 144), fill=(220, 60, 70))
    cv.rect((606, 98, 674, 122), fill=(220, 60, 70))
    cv.rect((90, 140, 330, 380), fill=(255, 255, 255), outline=(120, 140, 150), w=6, r=8)
    for i, (ch, sz) in enumerate((("E", 56), ("F P", 42), ("T O Z", 32), ("L P E D", 24))):
        cv.text((210, 185 + i * 55), ch, sz, INK, "mm")
    cv.rect((960, 400, 1240, 440), fill=(255, 255, 255), outline=(120, 140, 150), w=5, r=10)  # bed
    cv.rect((1180, 370, 1240, 404), fill=(170, 210, 240), r=10)
    for x in (980, 1220):
        cv.stroke([(x, 440), (x, 530)], (120, 140, 150), 8)
    return im, None


def scene_plain(top, bot):
    def make():
        im = gradient(top, bot)
        Cv(im).rect((0, GY - 20, W, H), fill=tuple(int(v * 0.86) for v in bot))
        return im, None
    return make


SCENES = dict(shop=scene_shop, clinic=scene_clinic, park=scene_park, cafe=scene_cafe, street=scene_street,
              title=scene_plain((255, 214, 102), (255, 240, 190)),
              board=scene_plain((200, 225, 245), (235, 245, 250)),
              end=scene_plain((160, 220, 190), (225, 245, 225)))


# --------------------------------------------------------------- episodes --
EPISODES = [
    dict(
        slug="01-nice-to-meet-you", title="Nice to Meet You", scene="park",
        cast=dict(sam=dict(x=-80), mia=dict(x=W + 80)),
        script=[
            ("walk", "sam", 470, 1.8), ("walk", "mia", 810, 1.8),
            ("say", "sam", "Hello!", "wave"),
            ("say", "mia", "Hi there!", "wave"),
            ("say", "sam", "My name is Sam. What's your name?", "talk"),
            ("say", "mia", "I'm Mia. Nice to meet you, Sam!", "talk"),
            ("say", "sam", "Nice to meet you too!", "talk"),
            ("say", "mia", "Where are you from?", "point"),
            ("say", "sam", "I'm from Canada. And you?", "talk"),
            ("say", "mia", "I'm from Egypt.", "talk"),
            ("say", "sam", "Wow, cool! How are you today?", "jump"),
            ("say", "mia", "I'm great, thanks! How about you?", "talk"),
            ("say", "sam", "I'm fine, thank you.", "talk"),
            ("say", "mia", "Well, I have to go. See you later!", "point_back"),
            ("say", "sam", "Goodbye, Mia! Have a nice day!", "wave"),
            ("walk", "mia", W + 90, 1.8, "wave"),
        ],
        phrases=["What's your name?", "Nice to meet you.", "Where are you from?",
                 "How are you today?", "See you later!"],
    ),
    dict(
        slug="02-at-the-cafe", title="At the Café", spoken_title="At the café", scene="cafe",
        cast=dict(sam=dict(x=-80), mia=dict(x=940, facing=-1)),
        script=[
            ("walk", "sam", 600, 2.2),
            ("say", "mia", "Good morning! Welcome to the Stick Café.", "wave"),
            ("say", "sam", "Good morning!", "wave"),
            ("say", "mia", "What would you like?", "talk"),
            ("say", "sam", "Can I have a coffee, please?", "talk"),
            ("say", "mia", "Sure! Small, medium, or large?", "talk"),
            ("say", "sam", "Medium, please.", "talk"),
            ("say", "mia", "Would you like anything else?", "talk"),
            ("say", "sam", "Yes. I'd like a chocolate cake, too.", "think"),
            ("say", "mia", "Good choice!", "nod"),
            ("say", "sam", "How much is it?", "talk"),
            ("say", "mia", "That's five dollars, please.", "talk"),
            ("say", "sam", "Here you are.", "give"),
            ("set", "cup", True), ("set", "cake", True),
            ("say", "mia", "Thank you! Here is your coffee and your cake.", "give"),
            ("say", "sam", "Thanks a lot! It looks delicious!", "jump"),
            ("say", "mia", "Enjoy! Have a great day!", "wave"),
        ],
        phrases=["What would you like?", "Can I have a coffee, please?", "How much is it?",
                 "Here you are.", "Thanks a lot!"],
    ),
    dict(
        slug="03-asking-for-directions", title="Asking for Directions", scene="street",
        cast=dict(sam=dict(x=-80), mia=dict(x=W + 80)),
        script=[
            ("walk", "sam", 430, 2.0),
            ("say", "sam", "Oh no. I think I'm lost.", "shrug"),
            ("walk", "mia", 780, 2.0),
            ("say", "sam", "Excuse me! Can you help me, please?", "wave"),
            ("say", "mia", "Of course! What's wrong?", "talk"),
            ("say", "sam", "Where is the train station?", "shrug"),
            ("say", "mia", "It's not far. Go straight ahead.", "point_back"),
            ("say", "mia", "Then turn left at the bank.", "point"),
            ("say", "sam", "Go straight, then turn left.", "think"),
            ("say", "mia", "Yes! The station is next to the park.", "talk"),
            ("say", "sam", "Is it far from here?", "talk"),
            ("say", "mia", "No, it's about five minutes on foot.", "talk"),
            ("say", "sam", "Great! Thank you so much!", "jump"),
            ("say", "mia", "You're welcome! Good luck!", "wave"),
            ("walk", "sam", W + 90, 2.6),
        ],
        phrases=["Excuse me!", "Where is the train station?", "Go straight ahead.",
                 "Turn left at the bank.", "You're welcome!"],
    ),
    dict(
        slug="04-going-shopping", title="Going Shopping", scene="shop",
        cast=dict(sam=dict(x=-80), mia=dict(x=790, facing=-1)),
        script=[
            ("walk", "sam", 500, 2.2),
            ("say", "mia", "Hello! Can I help you?", "wave"),
            ("say", "sam", "Yes, please. I'm looking for a T-shirt.", "talk"),
            ("say", "mia", "What size are you?", "talk"),
            ("say", "sam", "I'm a medium.", "talk"),
            ("say", "mia", "What color would you like?", "point_back"),
            ("say", "sam", "Blue, please. It's my favorite color.", "talk"),
            ("say", "mia", "Here you are. This one is very nice.", "give"),
            ("say", "sam", "Can I try it on?", "think"),
            ("say", "mia", "Sure! The mirror is over there.", "point"),
            ("say", "sam", "It fits perfectly! How much is it?", "jump"),
            ("say", "mia", "It's ten dollars.", "talk"),
            ("say", "sam", "Great! I'll take it.", "talk"),
            ("say", "mia", "Thank you! Have a nice day!", "wave"),
        ],
        phrases=["Can I help you?", "I'm looking for a T-shirt.", "What size are you?",
                 "Can I try it on?", "I'll take it."],
    ),
    dict(
        slug="05-what-do-you-like", title="What Do You Like?", scene="park",
        cast=dict(sam=dict(x=-80), mia=dict(x=W + 80)),
        script=[
            ("walk", "sam", 470, 1.8), ("walk", "mia", 810, 1.8),
            ("say", "sam", "Hi, Mia! What are you doing?", "wave"),
            ("say", "mia", "Hi, Sam! I'm going to play football.", "talk"),
            ("say", "sam", "Cool! Do you like sports?", "talk"),
            ("say", "mia", "Yes, I love sports! What about you?", "jump"),
            ("say", "sam", "I like swimming, but I don't like running.", "talk"),
            ("say", "mia", "What do you do in your free time?", "talk"),
            ("say", "sam", "I read books and listen to music.", "think"),
            ("say", "mia", "Me too! I love music.", "talk"),
            ("say", "sam", "Can you play the guitar?", "point"),
            ("say", "mia", "Yes, I can. But I can't sing!", "shrug"),
            ("say", "sam", "That's funny! Let's play football together.", "talk"),
            ("say", "mia", "Good idea! Let's go!", "jump"),
            ("walk", "mia", W + 90, 1.6), ("walk", "sam", W + 90, 2.4),
        ],
        phrases=["Do you like sports?", "I like swimming.", "I don't like running.",
                 "What do you do in your free time?", "Let's go!"],
    ),
    dict(
        slug="06-at-the-doctor", title="At the Doctor", scene="clinic",
        cast=dict(sam=dict(x=-80), mia=dict(x=800, facing=-1)),
        script=[
            ("walk", "sam", 500, 2.4),
            ("say", "mia", "Good afternoon. I'm Doctor Mia. How can I help you?", "wave"),
            ("say", "sam", "Hello, doctor. I don't feel well.", "shrug"),
            ("say", "mia", "What's the matter?", "talk"),
            ("say", "sam", "I have a headache and a sore throat.", "think"),
            ("say", "mia", "Do you have a fever?", "talk"),
            ("say", "sam", "Yes, I think so. I feel very tired.", "talk"),
            ("say", "mia", "Let me see. Open your mouth, please.", "point"),
            ("say", "sam", "Okay.", "nod"),
            ("say", "mia", "You have a cold. Don't worry.", "talk"),
            ("say", "mia", "Take this medicine twice a day.", "give"),
            ("say", "sam", "Thank you, doctor.", "talk"),
            ("say", "mia", "Drink a lot of water and get some rest.", "talk"),
            ("say", "sam", "I will. Thanks a lot!", "wave"),
            ("say", "mia", "Get well soon!", "wave"),
            ("walk", "sam", -90, 2.4),
        ],
        phrases=["I don't feel well.", "What's the matter?", "I have a headache.",
                 "Take this medicine twice a day.", "Get well soon!"],
    ),
]
NUM = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def build(ep, n):
    """Turn an episode script into timed segments with audio."""
    segs = []
    pos = {w: dict(x=c["x"], facing=c.get("facing", 1), vis=True) for w, c in ep["cast"].items()}
    state = {}

    def add(kind, dur, **kw):
        segs.append(dict(kind=kind, dur=dur, pos={w: dict(p) for w, p in pos.items()},
                         state=dict(state), **kw))

    def say(kind, who, text, action, pre=0.15, post=0.4, **kw):
        a = speak(who, text)
        add(kind, pre + len(a) / SR + post, who=who, text=text, action=action,
            audio=a, pre=pre, **kw)

    say("title", "mia", f"English with Stick Man. Episode {NUM[n]}. "
        f"{ep.get('spoken_title', ep['title'])}.", "wave", post=0.7)
    for ev in ep["script"]:
        if ev[0] == "walk":
            who, x1, dur = ev[1], ev[2], ev[3]
            x0 = pos[who]["x"]
            pos[who]["facing"] = 1 if x1 > x0 else -1
            add("walk", dur, who=who, x0=x0, x1=x1, action=ev[4] if len(ev) > 4 else "walk")
            pos[who]["x"] = x1
            if 0 < x1 < W:
                pos[who]["facing"] = 1 if x1 < 640 else -1
        elif ev[0] == "say":
            say("say", ev[1], ev[2], ev[3])
        elif ev[0] == "set":
            state[ev[1]] = ev[2]
    say("recap", "mia", "Now, listen and repeat.", "talk", idx=-1, turn=False)
    for i, ph in enumerate(ep["phrases"]):
        say("recap", "mia", ph, "point", idx=i, turn=False, post=0.25)
        add("recap", segs[-1]["dur"] + 0.5, who="mia", action="nod", idx=i, turn=True)
    say("end", "sam", "Great job! See you next time!", "jump", post=1.2)
    t = 0.0
    for s in segs:
        s["t0"] = t
        t += s["dur"]
        if "audio" in s:  # mouth envelope, one value per frame
            hop = SR // FPS
            a = s["audio"]
            rms = np.array([np.sqrt(np.mean(a[i:i + hop] ** 2) + 1e-9)
                            for i in range(0, len(a), hop)])
            s["env"] = np.clip(rms / (rms.max() + 1e-9) * 1.6, 0, 1)
    return segs, t


def mouth_of(s, who, lt):
    if s.get("who") != who or "env" not in s:
        return 0.0
    i = int((lt - s["pre"]) * FPS)
    return float(s["env"][i]) if 0 <= i < len(s["env"]) else 0.0


def subtitle(cv, who, text):
    c = CAST[who]
    cv.rect((90, 596, W - 90, 704), fill=(255, 255, 255), outline=c["accent"], w=4, r=22)
    cv.rect((120, 578, 120 + cv.width(c["name"], 24) + 36, 616), fill=c["accent"], r=14)
    cv.text((138, 597), c["name"], 24, (255, 255, 255), "lm")
    lines = wrap(cv, text, 36, W - 260)
    y = 656 - (len(lines) - 1) * 21
    for ln in lines:
        cv.text((W / 2, y), ln, 36, INK, "mm")
        y += 42


def render_frame(ep, n, s, t, bgs):
    lt = t - s["t0"]
    kind = s["kind"]
    scene = {"title": "title", "recap": "board", "end": "end"}.get(kind, ep["scene"])
    bg, fg = bgs[scene]
    im = bg.copy()
    cv = Cv(im)
    if kind == "title":
        cv.text((W / 2, 110), f"ENGLISH WITH STICK MAN  ·  EPISODE {n}", 30, (150, 90, 20), "mm")
        cv.text((W / 2, 205), ep["title"], 84, INK, "mm")
        pop = min(1.0, 0.4 + lt * 3)
        draw_fig(cv, "sam", 520, 1, "wave", t, 0, k=1.12 * pop)
        draw_fig(cv, "mia", 760, -1, "wave", t, mouth_of(s, "mia", lt), k=1.12 * pop)
    elif kind == "end":
        cv.text((W / 2, 85), "Great job!", 80, INK, "mm")
        cv.text((W / 2, 165), "See you next time!", 40, (40, 120, 80), "mm")
        draw_fig(cv, "sam", 520, 1, "jump", t, mouth_of(s, "sam", lt))
        draw_fig(cv, "mia", 760, -1, "jump", t + 0.25, 0)
    elif kind == "recap":
        cv.rect((380, 50, 1220, 520), fill=(255, 255, 255), outline=(110, 120, 135), w=10, r=14)
        cv.text((800, 100), "Key Phrases — Listen and Repeat", 34, (60, 90, 150), "mm")
        for i, ph in enumerate(ep["phrases"]):
            y = 180 + i * 66
            if i == s["idx"]:
                cv.rect((410, y - 30, 1190, y + 30), fill=(255, 235, 130), r=12)
            done = i < s["idx"] or (i == s["idx"] and s["turn"])
            cv.text((440, y), "✓" if done else "•", 36,
                    (50, 160, 90) if done else (150, 150, 160), "lm")
            cv.text((490, y), ph, 38, INK if i <= s["idx"] else (165, 170, 180), "lm")
        draw_fig(cv, "mia", 210, 1, s["action"], t, mouth_of(s, "mia", lt))
        if s["turn"]:
            cv.rect((90, 596, W - 90, 704), fill=(255, 250, 225), outline=(240, 170, 40), w=4, r=22)
            cv.text((W / 2, 636), "Your turn!  " + ep["phrases"][s["idx"]], 36, INK, "mm")
            cv.rect((240, 672, W - 240, 684), fill=(235, 225, 190), r=6)
            cv.rect((240, 672, 240 + (W - 480) * min(1, lt / s["dur"]), 684), fill=(240, 170, 40), r=6)
        elif "text" in s:
            subtitle(cv, "mia", s["text"])
    else:
        speaker = s.get("who")
        for who in sorted(s["pos"], key=lambda w: w == speaker):
            p = s["pos"][who]
            x, facing, action = p["x"], p["facing"], "idle"
            if who == speaker:
                action = s["action"]
                if kind == "walk":
                    u = min(1.0, lt / s["dur"])
                    x = s["x0"] + (s["x1"] - s["x0"]) * u
                    facing = 1 if s["x1"] > s["x0"] else -1
                    if action != "walk":  # e.g. waving while leaving
                        draw_fig(cv, who, x, facing, "walk", t, 0)
                        continue
            elif kind == "say" and int(s["t0"] * 7) % 3 == 0:
                action = "nod"
            draw_fig(cv, who, x, facing, action, t, mouth_of(s, who, lt))
        if fg:
            fg(cv, s["state"])
        cv.rect((24, 20, 24 + cv.width(f"English with Stick Man · Ep {n}", 20) + 32, 60),
                fill=(255, 255, 255), r=20)
        cv.text((40, 40), f"English with Stick Man · Ep {n}", 20, (90, 90, 100), "lm")
        if kind == "say":
            subtitle(cv, speaker, s["text"])
    return im.convert("RGB").resize((W, H), Image.LANCZOS)


def fit(cv, text, size, maxw):
    while cv.width(text, size) > maxw:
        size -= 1
    return size


def render_frame_v(ep, n, s, t, bgs):
    """9:16 layout. Text stays clear of TikTok's bottom caption and right-hand buttons."""
    lt = t - s["t0"]
    kind = s["kind"]
    scene = {"title": "title", "recap": "board", "end": "end"}.get(kind, ep["scene"])
    bg, fg = bgs[scene]
    x0 = ep["vx0"] if kind in ("say", "walk") else 0
    im = Image.new("RGBA", (VW * S, VH * S), NAVY)
    im.paste(bg.crop((x0 * S, 0, (x0 + VW) * S, H * S)), (0, SY * S))
    top = Cv(im)
    top.text((VW / 2, 125), "ENGLISH WITH STICK MAN", 26, (255, 214, 102), "mm")
    head = f"Ep {n} · {ep['title']}"
    top.text((VW / 2, 185), head, fit(top, head, 42, 640), (255, 255, 255), "mm")
    top.text((VW / 2, 1010), "Listen · Read · Repeat", 24, (140, 150, 195), "mm")
    cv, pg = Cv(im, -x0, SY), Cv(im, 0, SY)  # scrolled stage / fixed stage
    if kind == "title":
        pg.text((360, 45), f"EPISODE {n}", 28, (150, 90, 20), "mm")
        for i, ln in enumerate(wrap(pg, ep["title"], 62, 640)):
            pg.text((360, 115 + i * 72), ln, 62, INK, "mm")
        pop = min(1.0, 0.4 + lt * 3)
        draw_fig(pg, "sam", 250, 1, "wave", t, 0, k=1.12 * pop)
        draw_fig(pg, "mia", 470, -1, "wave", t, mouth_of(s, "mia", lt), k=1.12 * pop)
    elif kind == "end":
        pg.text((360, 85), "Great job!", 70, INK, "mm")
        pg.text((360, 160), "See you next time!", 36, (40, 120, 80), "mm")
        draw_fig(pg, "sam", 250, 1, "jump", t, mouth_of(s, "sam", lt))
        draw_fig(pg, "mia", 470, -1, "jump", t + 0.25, 0)
    elif kind == "recap":
        pg.rect((30, 10, 690, 335), fill=(255, 255, 255), outline=(110, 120, 135), w=8, r=14)
        pg.text((360, 48), "Listen and Repeat", 30, (60, 90, 150), "mm")
        for i, ph in enumerate(ep["phrases"]):
            y = 105 + i * 50
            if i == s["idx"]:
                pg.rect((46, y - 23, 674, y + 23), fill=(255, 235, 130), r=10)
            done = i < s["idx"] or (i == s["idx"] and s["turn"])
            pg.text((62, y), "✓" if done else "•", 28,
                    (50, 160, 90) if done else (150, 150, 160), "lm")
            pg.text((100, y), ph, fit(pg, ph, 32, 560),
                    INK if i <= s["idx"] else (165, 170, 180), "lm")
        act = "point_up" if s["action"] == "point" else s["action"]
        draw_fig(pg, "mia", 360, 1, act, t, mouth_of(s, "mia", lt), k=0.8)
        if s["turn"]:
            ph = ep["phrases"][s["idx"]]
            pg.rect((30, 596, 610, 704), fill=(255, 250, 225), outline=(240, 170, 40), w=4, r=22)
            pg.text((320, 624), "Your turn!", 26, (215, 140, 20), "mm")
            pg.text((320, 660), ph, fit(pg, ph, 34, 540), INK, "mm")
            pg.rect((60, 684, 580, 692), fill=(235, 225, 190), r=4)
            pg.rect((60, 684, 60 + 520 * min(1, lt / s["dur"]), 692), fill=(240, 170, 40), r=4)
        elif s["idx"] < 0:
            pg.rect((30, 606, 610, 694), fill=(255, 255, 255), outline=CAST["mia"]["accent"], w=4, r=22)
            pg.text((320, 650), s["text"], 34, INK, "mm")
    else:
        speaker = s.get("who")
        for who in sorted(s["pos"], key=lambda w: w == speaker):
            p = s["pos"][who]
            x, facing, action = p["x"], p["facing"], "idle"
            if who == speaker:
                action = s["action"]
                if kind == "walk":
                    x = s["x0"] + (s["x1"] - s["x0"]) * min(1.0, lt / s["dur"])
                    facing = 1 if s["x1"] > s["x0"] else -1
                    action = "walk"
            elif kind == "say" and int(s["t0"] * 7) % 3 == 0:
                action = "nod"
            draw_fig(cv, who, x, facing, action, t, mouth_of(s, who, lt))
        if fg:
            fg(cv, s["state"])
        if kind == "say":
            c = CAST[speaker]
            pg.rect((30, 24, 690, 164), fill=(255, 255, 255), outline=c["accent"], w=4, r=22)
            pg.rect((56, 6, 56 + pg.width(c["name"], 24) + 36, 44), fill=c["accent"], r=14)
            pg.text((74, 25), c["name"], 24, (255, 255, 255), "lm")
            lines = wrap(pg, s["text"], 36, 610)
            y = 98 - (len(lines) - 1) * 21
            for ln in lines:
                pg.text((360, y), ln, 36, INK, "mm")
                y += 42
    # keep the stage from spilling onto the header/footer bands
    top.rect((0, SY + H, VW, VH), fill=NAVY)
    top.text((VW / 2, 1010), "Listen · Read · Repeat", 24, (140, 150, 195), "mm")
    return im.convert("RGB").resize((1080, 1920), Image.LANCZOS)


def render(ep, n, vertical=False):
    out_dir = os.path.join(OUT, "tiktok") if vertical else OUT
    os.makedirs(out_dir, exist_ok=True)
    xs = [c["x"] for c in ep["cast"].values()] + [e[2] for e in ep["script"] if e[0] == "walk"]
    xs = [x for x in xs if 0 < x < W]
    ep["vx0"] = int(max(0, min(W - VW, (min(xs) + max(xs)) / 2 - 330)))
    frame, size = (render_frame_v, "1080x1920") if vertical else (render_frame, f"{W}x{H}")
    segs, total = build(ep, n)
    audio = music(total)
    fade = np.minimum(1, np.minimum(np.arange(len(audio)), len(audio) - np.arange(len(audio))) / SR)
    audio *= fade
    for s in segs:
        if "audio" in s:
            i = int((s["t0"] + s["pre"]) * SR)
            audio[i:i + len(s["audio"])] += s["audio"][:len(audio) - i] * 0.9
    wav = os.path.join(CACHE, ep["slug"] + ".wav")
    with wave.open(wav, "wb") as wf:
        wf.setnchannels(1), wf.setsampwidth(2), wf.setframerate(SR)
        wf.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    out = os.path.join(out_dir, ep["slug"] + ".mp4")
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", size, "-r", str(FPS), "-i", "-", "-i", wav,
         "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-shortest", out],
        stdin=subprocess.PIPE)
    bgs = {k: f() for k, f in SCENES.items() if k in ("title", "board", "end", ep["scene"])}
    si = 0
    for f in range(int(total * FPS)):
        t = f / FPS
        while si + 1 < len(segs) and t >= segs[si + 1]["t0"]:
            si += 1
        ff.stdin.write(frame(ep, n, segs[si], t, bgs).tobytes())
    ff.stdin.close()
    if ff.wait():
        raise SystemExit("ffmpeg failed")
    print(f"{out}  ({total:.0f}s)")


if __name__ == "__main__":
    vertical = "--tiktok" in sys.argv
    pick = [a for a in sys.argv[1:] if not a.startswith("--")]
    for n, ep in enumerate(EPISODES, 1):
        if not pick or any(p in ep["slug"] for p in pick):
            render(ep, n, vertical)
