#!/usr/bin/env python3
"""Generate brand assets for codebase-index (social preview + README demo still).

Pure-Pillow, no external binaries. Renders at 3x and downsamples with LANCZOS for
crisp typography. Re-run after changing copy:

    python scripts/gen_assets.py

Outputs:
    assets/social-preview.png   1280x640  -> upload in Settings -> Social preview
    assets/demo.png             1200x760  -> embed near the top of README.md
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SS = 3  # supersample factor

# GitHub dark palette
BG_TOP = (13, 17, 23)        # #0d1117
BG_BOT = (1, 4, 9)           # #010409
PANEL = (22, 27, 34)         # #161b22
PANEL_BAR = (26, 32, 40)
BORDER = (48, 54, 61)        # #30363d
FG = (230, 237, 243)         # #e6edf3
FG2 = (173, 186, 199)        # #adbac7
MUTED = (110, 118, 129)      # #6e7681
DIM = (118, 131, 144)        # #768390
BLUE = (88, 166, 255)        # #58a6ff
CYAN = (121, 192, 255)       # #79c0ff
GREEN = (63, 185, 80)        # #3fb950
PURPLE = (188, 140, 255)     # #bc8cff
YELLOW = (210, 153, 34)      # #d29922
RED = (248, 81, 73)          # #f85149

FONTDIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for candidate in (FONTDIR / name, Path(name)):
        try:
            return ImageFont.truetype(str(candidate), size * SS)
        except OSError:
            continue
    return ImageFont.load_default()


# Font roles
def f_ui(size: int) -> ImageFont.FreeTypeFont:        # Segoe UI regular
    return font("segoeui.ttf", size)


def f_ui_b(size: int) -> ImageFont.FreeTypeFont:      # Segoe UI bold
    return font("segoeuib.ttf", size)


def f_mono(size: int) -> ImageFont.FreeTypeFont:      # Consolas regular
    return font("consola.ttf", size)


def f_mono_b(size: int) -> ImageFont.FreeTypeFont:    # Consolas bold
    return font("consolab.ttf", size)


def gradient_bg(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), BG_TOP)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        r = round(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
        g = round(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
        b = round(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def add_glow(img: Image.Image, cx: int, cy: int, radius: int, color, alpha: int) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(radius // 2))
    img.paste(Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB"), (0, 0))


def spaced_text(d, xy, text, fnt, fill, tracking):
    """Draw text with extra letter-spacing (tracking in unscaled px)."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=fnt, fill=fill)
        x += d.textlength(ch, font=fnt) + tracking * SS


def pill(d, x, y, label, fnt, fg, bg, pad_x=16, pad_y=9):
    w = d.textlength(label, font=fnt)
    h = (fnt.getbbox("Hg")[3] - fnt.getbbox("Hg")[1])
    x1 = x + w + pad_x * 2 * SS
    y1 = y + h + pad_y * 2 * SS
    d.rounded_rectangle([x, y, x1, y1], radius=(h // 2 + pad_y * SS), fill=bg, outline=BORDER, width=SS)
    d.text((x + pad_x * SS, y + pad_y * SS - fnt.getbbox("Hg")[1]), label, font=fnt, fill=fg)
    return x1


def window_chrome(d, x0, y0, x1, y1, title, bar_h=44):
    d.rounded_rectangle([x0, y0, x1, y1], radius=16 * SS, fill=PANEL, outline=BORDER, width=SS + SS // 2)
    # title bar separator
    d.line([x0 + SS, y0 + bar_h * SS, x1 - SS, y0 + bar_h * SS], fill=BORDER, width=SS)
    cy = y0 + (bar_h // 2) * SS
    for i, col in enumerate((RED, YELLOW, GREEN)):
        cx = x0 + (24 + i * 26) * SS
        r = 7 * SS
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    tf = f_mono(16)
    tw = d.textlength(title, font=tf)
    d.text(((x0 + x1) / 2 - tw / 2, cy - (tf.getbbox("Hg")[3] - tf.getbbox("Hg")[1]) / 2 - tf.getbbox("Hg")[1]),
           title, font=tf, fill=MUTED)


def downsave(img: Image.Image, w: int, h: int, path: Path) -> None:
    out = img.resize((w, h), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path, "PNG", optimize=True)
    kb = path.stat().st_size / 1024
    print(f"  {path}  {w}x{h}  {kb:.0f} KB")


# --------------------------------------------------------------------------- #
# Social preview: 1280 x 640
# --------------------------------------------------------------------------- #
def build_social(out: Path) -> None:
    W, H = 1280, 640
    w, h = W * SS, H * SS
    img = gradient_bg(w, h)
    add_glow(img, int(w * 0.92), int(h * 0.08), 360 * SS, BLUE, 46)
    add_glow(img, int(w * 0.04), int(h * 0.98), 320 * SS, PURPLE, 34)
    d = ImageDraw.Draw(img)

    LM = 72 * SS

    # eyebrow
    dot_r = 6 * SS
    ey = 82 * SS
    d.ellipse([LM, ey - dot_r, LM + 2 * dot_r, ey + dot_r], fill=GREEN)
    spaced_text(d, (LM + 22 * SS, 74 * SS),
                "LOCAL-FIRST  ·  NO NETWORK BY DEFAULT  ·  MCP-READY",
                f_ui_b(15), DIM, 2)

    # wordmark (split color)
    wm = f_mono_b(80)
    wy = 104 * SS
    d.text((LM, wy), "codebase", font=wm, fill=FG)
    seg = d.textlength("codebase", font=wm)
    d.text((LM + seg, wy), "-index", font=wm, fill=BLUE)

    # tagline
    d.text((LM, 214 * SS), "Local codebase indexing for AI coding agents",
           font=f_ui(36), fill=FG2)

    # terminal
    x0, y0, x1, y1 = LM, 290 * SS, (W - 72) * SS, 540 * SS
    window_chrome(d, x0, y0, x1, y1, "codebase-index — search")
    bx = x0 + 30 * SS
    mono = f_mono(21)
    cw = d.textlength("0", font=mono)
    by = y0 + 64 * SS

    # command line
    d.text((bx, by), "$", font=f_mono_b(21), fill=GREEN)
    d.text((bx + cw * 2, by), "codebase-index search ", font=mono, fill=FG)
    cmd_w = d.textlength("codebase-index search ", font=mono)
    d.text((bx + cw * 2 + cmd_w, by), '"where is auth implemented?"', font=mono, fill=CYAN)

    # results header
    hy = by + 46 * SS
    d.text((bx, hy), "Top matches", font=f_mono(18), fill=MUTED)

    rows = [
        ("1", "src/auth/AuthService.ts", "0.92", "exact symbol match", GREEN),
        ("2", "src/routes/auth.ts", "0.78", "FTS · 4 callers", BLUE),
        ("3", "src/middleware/auth.ts", "0.65", "path · FTS match", MUTED),
    ]
    col_rank = bx
    col_path = bx + cw * 3
    col_score = bx + cw * 31
    col_reason = bx + cw * 38
    ry = hy + 36 * SS
    for rank, path, score, reason, scol in rows:
        d.text((col_rank, ry), rank, font=f_mono_b(20), fill=BLUE)
        d.text((col_path, ry), path, font=mono, fill=CYAN)
        d.text((col_score, ry), score, font=f_mono_b(20), fill=scol)
        d.text((col_reason, ry), reason, font=mono, fill=FG2)
        ry += 33 * SS

    # chips
    chips = ["Tree-sitter", "SQLite FTS5", "Graph impact", "MCP server"]
    cf = f_ui_b(16)
    cx = LM
    cy = 574 * SS
    for c in chips:
        cx = pill(d, cx, cy, c, cf, FG2, PANEL_BAR) + 12 * SS

    downsave(img, W, H, out)


# --------------------------------------------------------------------------- #
# README demo still: 1200 x 760
# --------------------------------------------------------------------------- #
def build_demo(out: Path) -> None:
    W, H = 1200, 760
    w, h = W * SS, H * SS
    img = gradient_bg(w, h)
    add_glow(img, int(w * 0.5), int(h * -0.05), 460 * SS, BLUE, 26)
    d = ImageDraw.Draw(img)

    # terminal
    x0, y0, x1, y1 = 48 * SS, 56 * SS, (W - 48) * SS, 660 * SS
    window_chrome(d, x0, y0, x1, y1, "bash — codebase-index")

    mono = f_mono(20)
    mono_b = f_mono_b(20)
    bx = x0 + 32 * SS
    cw = d.textlength("0", font=mono)
    lh = 30 * SS
    y = y0 + 70 * SS

    def col(n):  # x position at character column n
        return bx + cw * n

    # command
    d.text((bx, y), "$", font=mono_b, fill=GREEN)
    d.text((col(2), y), "codebase-index search ", font=mono, fill=FG)
    cmdw = d.textlength("codebase-index search ", font=mono)
    d.text((col(2) + cmdw, y), '"where is user authentication implemented?"', font=mono, fill=CYAN)
    y += lh * 2

    d.text((bx, y), "Top matches:", font=mono_b, fill=FG); y += lh
    d.text((bx, y), "Rank   Path                     Symbols              Score  Reason",
           font=mono, fill=MUTED); y += lh

    table = [
        ("1", "src/auth/AuthService.ts", "AuthService, login", "0.92", "exact symbol match", GREEN),
        ("2", "src/routes/auth.ts", "loginHandler, logout", "0.78", "FTS · 4 callers", BLUE),
        ("3", "src/middleware/auth.ts", "requireAuth", "0.65", "path · FTS match", MUTED),
    ]
    for rank, path, syms, score, reason, scol in table:
        d.text((col(2), y), rank, font=mono_b, fill=BLUE)
        d.text((col(7), y), path, font=mono, fill=CYAN)
        d.text((col(32), y), syms, font=mono, fill=FG2)
        d.text((col(53), y), score, font=mono_b, fill=scol)
        d.text((col(60), y), reason, font=mono, fill=FG2)
        y += lh
    y += lh

    d.text((bx, y), "Recommended reads:", font=mono_b, fill=FG); y += lh
    reads = [
        ("1.", "src/auth/AuthService.ts:12-148", "matched AuthService, login(), validatePassword()"),
        ("2.", "src/routes/auth.ts:20-91", "/login route calls AuthService.login()"),
        ("3.", "src/middleware/auth.ts:5-42", "auth middleware validates sessions"),
    ]
    for n, loc, reason in reads:
        d.text((col(2), y), n, font=mono, fill=MUTED)
        d.text((col(5), y), loc, font=mono_b, fill=CYAN)
        y += lh
        d.text((col(5), y), "reason: " + reason, font=mono, fill=MUTED)
        y += lh + 4 * SS

    # footer wordmark + tagline
    fy = (H - 64) * SS
    wm = f_mono_b(26)
    d.text((48 * SS, fy), "codebase-index", font=wm, fill=FG)
    seg = d.textlength("codebase-index", font=wm)
    d.text((48 * SS + seg + 14 * SS, fy + 6 * SS),
           "local hybrid index · no network by default", font=f_ui(17), fill=MUTED)

    downsave(img, W, H, out)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    assets = root / "assets"
    print("Generating assets:")
    build_social(assets / "social-preview.png")
    build_demo(assets / "demo.png")
    print("Done.")


if __name__ == "__main__":
    main()
