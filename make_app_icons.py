"""Generate PNG, Windows ICO, and macOS ICNS from the source SVG."""

from io import BytesIO
from pathlib import Path

import cairosvg
from PIL import Image


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"


def main():
    rendered = cairosvg.svg2png(url=str(ASSETS / "app-icon.svg"), output_width=1024,
                                output_height=1024)
    image = Image.open(BytesIO(rendered)).convert("RGBA")
    image.save(ASSETS / "app-icon.png")
    image.save(ASSETS / "app-icon.ico", format="ICO",
               sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    image.save(ASSETS / "app-icon.icns", format="ICNS")
    print("Generated desktop icons in", ASSETS)


if __name__ == "__main__":
    main()
