# فيديو: فوائد الصلاة

- `prayer_benefits.mp4`: الفيديو النهائي (عمودي 1080×1920، مدته 81 ثانية، مناسب لـ Reels / TikTok / Shorts).
- `make_video.py`: السكربت الذي ينتج الفيديو (Pillow مع libraqm + ffmpeg).
- `fonts/`: خط Amiri (رخصة OFL).

لإعادة توليد الفيديو بعد تعديل النصوص في قائمة `SCENES`:

```bash
python3 make_video.py fonts prayer_benefits.mp4
```
