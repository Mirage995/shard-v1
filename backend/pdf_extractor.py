"""pdf_extractor.py -- Extract images from PDF for SHARD VLM ingestion.

Converts each PDF page to a PNG image, optionally filtering pages that
contain figures/diagrams (non-blank pages with significant visual content).

Usage:
    from pdf_extractor import extract_pdf_images
    image_paths = extract_pdf_images("paper.pdf", output_dir="shard_workspace/visual_input")
"""

from __future__ import annotations

import os
from pathlib import Path

import fitz  # pymupdf
from PIL import Image


DPI = int(os.getenv("PDF_EXTRACT_DPI", "120"))          # 120dpi = buon compromesso qualità/peso
MAX_PAGES = int(os.getenv("PDF_EXTRACT_MAX_PAGES", "20"))  # cap per paper lunghi
MIN_IMAGE_BYTES = int(os.getenv("PDF_MIN_IMAGE_BYTES", "10000"))  # scarta pagine quasi vuote
VLM_MAX_PX = int(os.getenv("VLM_MAX_PX", "1024"))       # max dimensione lato lungo per VLM
VLM_JPEG_QUALITY = int(os.getenv("VLM_JPEG_QUALITY", "80"))  # qualità JPEG output


def _page_has_figures(page: fitz.Page) -> bool:
    """True if page has embedded images or drawings (non-text-only)."""
    # Check immagini embedded
    if page.get_images():
        return True
    # Check drawings/paths (grafici, diagrammi)
    drawings = page.get_drawings()
    if len(drawings) > 5:
        return True
    return False


def extract_pdf_images(
    pdf_path: str,
    output_dir: str,
    figures_only: bool = True,
    prefix: str | None = None,
) -> list[str]:
    """Extract pages from PDF as PNG images.

    Args:
        pdf_path: Path to PDF file.
        output_dir: Directory where PNG files will be saved.
        figures_only: If True, only extract pages with figures/diagrams.
                      If False, extract all pages.
        prefix: Filename prefix (default: PDF basename without extension).

    Returns:
        List of absolute paths to extracted PNG files.
    """
    pdf_path = Path(pdf_path).resolve()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if prefix is None:
        prefix = pdf_path.stem[:40]  # max 40 chars

    doc = fitz.open(str(pdf_path))
    total = min(len(doc), MAX_PAGES)

    extracted: list[str] = []
    mat = fitz.Matrix(DPI / 72, DPI / 72)  # 72dpi base → scale to DPI

    for page_num in range(total):
        page = doc[page_num]

        if figures_only and not _page_has_figures(page):
            continue

        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        out_path = output_dir / f"{prefix}_page{page_num + 1:03d}.jpg"

        # Converti in PIL, ridimensiona se necessario, salva JPEG compresso
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        if max(img.width, img.height) > VLM_MAX_PX:
            ratio = VLM_MAX_PX / max(img.width, img.height)
            img = img.resize(
                (int(img.width * ratio), int(img.height * ratio)),
                Image.LANCZOS,
            )
        img.save(str(out_path), "JPEG", quality=VLM_JPEG_QUALITY, optimize=True)

        # Scarta file troppo piccoli (pagine bianche o quasi vuote)
        if out_path.stat().st_size < MIN_IMAGE_BYTES:
            out_path.unlink()
            continue

        extracted.append(str(out_path))

    doc.close()
    return extracted


def extract_pdf_text(pdf_path: str, max_pages: int = 20) -> str:
    """Extract raw text from PDF (complementary to image extraction)."""
    pdf_path = Path(pdf_path).resolve()
    doc = fitz.open(str(pdf_path))
    pages = min(len(doc), max_pages)
    texts = []
    for i in range(pages):
        text = doc[i].get_text("text").strip()
        if text:
            texts.append(f"[Page {i+1}]\n{text}")
    doc.close()
    return "\n\n".join(texts)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python pdf_extractor.py <pdf_path> [output_dir] [--all-pages]")
        sys.exit(1)

    pdf = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "../shard_workspace/visual_input"
    figures_only = "--all-pages" not in sys.argv

    paths = extract_pdf_images(pdf, out, figures_only=figures_only)
    print(f"Estratte {len(paths)} immagini da {pdf}:")
    for p in paths:
        size = Path(p).stat().st_size // 1024
        print(f"  {p} ({size}KB)")
