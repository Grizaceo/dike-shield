# Pitch video

`dike-shield.mp4` is a 1–4 minute English card film of the required beats:

question → invented cite caught → verified repair → offline commitment → cross-session memory → bank figure per lane → Runtime receipt (keys hidden).

## What is in the file

Cards rendered from `build_frames.py` (1920×1080) and encoded with ffmpeg.

- FAST/DEEP Nemotron receipt: live Fase 2 trace of 27 Oct 2026 morning (`nvidia/nemotron-3.5-lightning-30b-a3b` 26922 ms; `nvidia/nemotron-3-ultra-550b-a55b`).
- Console card 09: virsh framebuffer of Nightshift Console the same evening (17:26 CL), Hotspot on `192.168.122.50`, token cropped to `Bearer ***`. Source: `console-live.png`.
- `GET /models` 200 with 86 ids including Lightning 30B and Ultra 550B (17:26 CL).
- New `chat/completions` at 17:27 CL returned HTTP 502 from NVIDIA. That is on the card; we did not invent a Console chat receipt.

Rebuild:

```bash
python docs/video/build_frames.py
ffmpeg -y -framerate 1/10 -i docs/video/frames/%02d.png \
  -c:v libx264 -pix_fmt yuv420p -r 30 docs/video/dike-shield.mp4
```

Do not composite a fake Console.
