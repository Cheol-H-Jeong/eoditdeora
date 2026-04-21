"""Generate installers/windows/icon.ico without depending on ImageMagick.

The CI workflow used to embed the image-generation script inside a
PowerShell here-string, which made the YAML fragile. Keeping it as a
standalone script is sturdier and identical in behaviour.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    out = Path(__file__).resolve().parent / "icon.ico"
    img = Image.new("RGBA", (256, 256), (11, 13, 17, 255))
    d = ImageDraw.Draw(img)
    d.ellipse((60, 70, 180, 190), outline=(138, 180, 255, 255), width=14)
    d.line((165, 170, 220, 225), fill=(138, 180, 255, 255), width=14)
    img.save(out, sizes=[(256, 256)])
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
