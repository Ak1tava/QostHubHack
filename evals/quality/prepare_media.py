"""Fetch evaluation-only source photographs; never redistribute media in Git.

Run with bundled Python (Pillow/pypdf/certifi), or uv run --with pypdf.
"""

import hashlib
import json
import ssl
import urllib.request
from pathlib import Path

import certifi
from PIL import Image, ImageFilter
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / ".tooling" / "t07-quality" / "media"


def prepare():
    sources = json.loads((ROOT / "evals/quality/sources.json").read_text())
    MEDIA.mkdir(parents=True, exist_ok=True)
    for source in sources.values():
        for name, url in source["files"].items():
            target = MEDIA / name
            if not target.exists():
                request = urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(
                    request,
                    context=ssl.create_default_context(cafile=certifi.where()),
                    timeout=30,
                ) as response:
                    data = response.read(12 * 1024 * 1024 + 1)
                if len(data) > 12 * 1024 * 1024:
                    raise ValueError("Source media too large")
                target.write_bytes(data)
            if (
                hashlib.sha256(target.read_bytes()).hexdigest()
                != source["raw_sha256"][name]
            ):
                raise ValueError(
                    "Source file changed; review provenance before updating frozen corpus"
                )
    pdf = PdfReader(MEDIA / "corrocoat.pdf")
    # Embedded photograph objects contain no PDF captions or result annotations.
    for number in (0, 1):
        (MEDIA / f"corrocoat-{number}.jpg").write_bytes(
            pdf.pages[0].images[number].data
        )
    inputs = {
        "rezitech-before": ("rezitech-before.jpg", None),
        "rezitech-after": ("rezitech-after.jpg", None),
        "acca-before": ("acca-before.avif", None),
        "acca-after": ("acca-after.avif", None),
        "corrocoat-before": ("corrocoat-1.jpg", None),
        "corrocoat-after": ("corrocoat-0.jpg", None),
        "westin-before": ("westin.jpg", (0, 0, 950, 475)),
        "westin-after": ("westin.jpg", (0, 475, 950, 950)),
    }
    for stem, (name, crop) in inputs.items():
        with Image.open(MEDIA / name) as raw:
            pixels = raw.convert("RGB")
            if crop:
                pixels = pixels.crop(crop)
            pixels.thumbnail((1024, 1024))
            # Re-encoding drops EXIF, URLs, result labels and other metadata.
            pixels.save(MEDIA / f"{stem}.normalized.jpg", format="JPEG", quality=90)
            if stem in {"rezitech-after", "corrocoat-after", "westin-after"}:
                degraded = (
                    pixels.resize((24, 24))
                    .resize(pixels.size)
                    .filter(ImageFilter.GaussianBlur(20))
                )
                degraded.save(MEDIA / f"{stem}.blurred.jpg", format="JPEG", quality=80)
    print(
        "Prepared 8 evaluation photographs and 3 deliberately degraded derivatives; all media ignored by Git."
    )


if __name__ == "__main__":
    prepare()
