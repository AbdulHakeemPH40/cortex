"""
Run this script once to generate rounded-corner icons for Cortex.
Usage: python generate_icons.py

Generates:
  src/assets/logo/taskbar_rounded.png  (256x256 with 10px radius)
  src/assets/logo/taskbar.ico          (multi-size ICO with rounded corners)
  src/assets/logo/logo.ico             (multi-size ICO with rounded corners)
"""

import os
from PIL import Image, ImageDraw

LOGO_DIR = os.path.join(os.path.dirname(__file__), "src", "assets", "logo")

# Source PNG to use as base (pick whichever looks best)
SOURCE_PNG = os.path.join(LOGO_DIR, "taskbar.png")
if not os.path.exists(SOURCE_PNG):
    SOURCE_PNG = os.path.join(LOGO_DIR, "app.png")

RADIUS_AT_256 = 40  # 40px at 256x256 → visible squircle effect (scales to ~5px at 32px)


def add_rounded_corners(img: Image.Image, radius: int) -> Image.Image:
    """Apply rounded corners mask to image."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (img.size[0] - 1, img.size[1] - 1)], radius=radius, fill=255)
    result = img.copy()
    result.putalpha(mask)
    return result


def generate(source_path: str):
    print(f"Loading source: {source_path}")
    base = Image.open(source_path).convert("RGBA")

    sizes = [16, 32, 48, 64, 128, 256]
    frames = []

    for size in sizes:
        # Scale radius proportionally, minimum 4px so it's always visible
        radius = max(4, round(RADIUS_AT_256 * size / 256))
        resized = base.resize((size, size), Image.LANCZOS)
        rounded = add_rounded_corners(resized, radius)
        frames.append(rounded)
        print(f"  Generated {size}x{size} with radius={radius}px")

    # Save 256x256 rounded PNG (used by main.py at runtime)
    out_png = os.path.join(LOGO_DIR, "taskbar_rounded.png")
    frames[-1].save(out_png, "PNG")
    print(f"Saved: {out_png}")

    # Save taskbar.ico (multi-size) — pass the 256px image, PIL resizes down for each size
    out_ico = os.path.join(LOGO_DIR, "taskbar.ico")
    frames[-1].save(
        out_ico,
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )
    print(f"Saved: {out_ico}")

    # Save logo.ico (same — used by PyInstaller to embed into Cortex.exe)
    out_logo_ico = os.path.join(LOGO_DIR, "logo.ico")
    frames[-1].save(
        out_logo_ico,
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )
    print(f"Saved: {out_logo_ico}")

    print("\nDone! All icons generated with rounded corners.")
    print("Now rebuild the .exe with: python -m PyInstaller cortex.spec --noconfirm")


if __name__ == "__main__":
    generate(SOURCE_PNG)
