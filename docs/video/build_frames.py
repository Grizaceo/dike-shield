#!/usr/bin/env python3
"""Render 1920×1080 title cards for the 1–4 min pitch video."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "frames"
W, H = 1920, 1080
INK = (27, 23, 18)
PAPER = (255, 253, 248)
BURGUNDY = (122, 31, 31)
BRASS = (196, 163, 90)
MUTED = (90, 78, 66)
GREEN = (47, 74, 60)
CARD = (244, 239, 228)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def card(bg: tuple[int, int, int]) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", (W, H), bg)
    return im, ImageDraw.Draw(im)


def kicker(draw, text: str, y: int, color=BRASS) -> None:
    draw.text((120, y), text.upper(), font=font(28, True), fill=color)


def title(draw, text: str, y: int, color=PAPER, size: int = 72) -> int:
    fnt = font(size, True)
    lines = wrap(draw, text, fnt, W - 240)
    for i, line in enumerate(lines):
        draw.text((120, y + i * (size + 12)), line, font=fnt, fill=color)
    return y + len(lines) * (size + 12) + 24


def body(draw, text: str, y: int, color=PAPER, size: int = 36) -> int:
    fnt = font(size)
    lines = wrap(draw, text, fnt, W - 240)
    for i, line in enumerate(lines):
        draw.text((120, y + i * (size + 14)), line, font=fnt, fill=color)
    return y + len(lines) * (size + 14)


def save(im: Image.Image, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    im.save(OUT / name, "PNG")


def frame_dark(k: str, t: str, b: str, name: str) -> None:
    im, draw = card(INK)
    draw.rectangle((0, 0, 18, H), fill=BURGUNDY)
    kicker(draw, k, 140)
    y = title(draw, t, 220)
    body(draw, b, y + 20, color=(230, 222, 210), size=34)
    save(im, name)


def frame_light(k: str, t: str, b: str, name: str, footnote: str | None = None) -> None:
    im, draw = card(PAPER)
    draw.rectangle((0, 0, 18, H), fill=BURGUNDY)
    kicker(draw, k, 100, color=BURGUNDY)
    y = title(draw, t, 170, color=INK, size=60)
    body(draw, b, y + 10, color=MUTED, size=32)
    if footnote:
        draw.text((120, 980), footnote, font=font(22), fill=MUTED)
    save(im, name)


def main() -> None:
    frame_dark(
        "Open Agent Hackathon 2026",
        "Diké Shield",
        "Nemotron cites. Diké proves. A Chilean labor draft that can leave the chat window.",
        "01.png",
    )
    frame_light(
        "Question",
        "What is the deadline to challenge a dismissal for business needs?",
        "A Santiago lawyer asks in Spanish. FAST Lightning 30B drafts. Every article must survive Diké.",
        "02.png",
    )
    frame_light(
        "Invented cite, caught",
        "artículo 14 at position 391",
        "Live Nightshift, 27 Oct 2026: nvidia/nemotron-3.5-lightning-30b-a3b, 26.9 s. Diké: AMBIGUOUS. The article is in the draft. It is not in the final.",
        "03.png",
        "Token hidden. Model id and latency from CURSOR_LOG Fase 2.",
    )
    frame_light(
        "Audit",
        "artículo 9999 of the Labour Code",
        "The pasted brief cites a number that does not exist. Diké: FALLO UNRESOLVABLE. The shield will not publish it.",
        "04.png",
    )
    frame_light(
        "Verified repair",
        "DEEP rewrites on verified articles only",
        "nvidia/nemotron-3-ultra-550b-a55b keeps artículo 161 and artículo 168. 9999 is gone. Diké runs again. Decision: publicar.",
        "05.png",
    )
    frame_light(
        "Offline commitment",
        "A ZIP anyone can check without Nightshift",
        "Ed25519 over the citations that survived. A third party verifies on a machine that never saw the Runtime token.",
        "06.png",
    )
    frame_light(
        "Memory across sessions",
        "recordado de la sesión <id>",
        "H-MEM stores the refuted cite. The next session recalls artículo 9999 before FAST drafts again. Meterless engine, conformance 13/13.",
        "07.png",
    )
    im, draw = card(PAPER)
    draw.rectangle((0, 0, 18, H), fill=BURGUNDY)
    kicker(draw, "Adversarial bank", 100, color=BURGUNDY)
    title(draw, "Unproven cites per lane", 170, color=INK, size=56)
    # two columns
    draw.rounded_rectangle((120, 420, 900, 900), radius=18, fill=CARD)
    draw.rounded_rectangle((1020, 420, 1800, 900), radius=18, fill=INK)
    draw.text((160, 470), "Without shield", font=font(28, True), fill=BURGUNDY)
    draw.text((160, 540), "50%", font=font(96, True), fill=INK)
    draw.text((160, 680), "FAST and DEEP, scripted n=2", font=font(26), fill=MUTED)
    draw.text((1060, 470), "With shield", font=font(28, True), fill=BRASS)
    draw.text((1060, 540), "0%", font=font(96, True), fill=PAPER)
    draw.text((1060, 680), "Same items, Diké on the path", font=font(26), fill=BRASS)
    draw.text((120, 980), "Measured on synthetic questions. Not a production rate. Live 30-q bank still pending a healthy NVIDIA upstream.", font=font(22), fill=MUTED)
    save(im, "08.png")

    im, draw = card(INK)
    draw.rectangle((0, 0, 18, H), fill=BURGUNDY)
    kicker(draw, "Runtime receipt  ·  27 Oct 2026  17:26 CL", 48)
    title(draw, "Nightshift Console  ·  live", 110, size=52)
    shot = Path(__file__).resolve().parent / "console-live.png"
    console = Image.open(shot).convert("RGB")
    max_w, max_h = 1100, 780
    scale = min(max_w / console.size[0], max_h / console.size[1])
    nw, nh = int(console.size[0] * scale), int(console.size[1] * scale)
    console = console.resize((nw, nh), Image.Resampling.LANCZOS)
    im.paste(console, (120, 250))
    save(im, "09.png")

    frame_light(
        "Same evening",
        "GET /models 200  ·  86 ids",
        "Hotspot on 192.168.122.50:8088. Catalog includes nvidia/nemotron-3.5-lightning-30b-a3b and nvidia/nemotron-3-ultra-550b-a55b. New chat/completions returned 502 from NVIDIA at 17:27 CL; the live FAST/DEEP receipt is the morning run (26.9 s Lightning). Token hidden.",
        "10.png",
        "Console screenshot is the VM framebuffer. API key cropped. Do not ship a fake Console.",
    )
    frame_dark(
        "The Agent That Can Explain Why",
        "Nemotron cites. Diké proves.",
        "The lawyer still decides whether the article supports the claim. We only refuse to invent the article.",
        "11.png",
    )


if __name__ == "__main__":
    main()
    print("frames", OUT)
