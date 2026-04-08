from __future__ import annotations

from pathlib import Path

from PIL import Image


def compress_image(path: Path, max_side: int = 512, quality: int = 85) -> None:
    img = Image.open(path)
    img = img.convert("RGB")
    width, height = img.size
    scale = min(1.0, max_side / max(width, height))

    if scale < 1.0:
        new_size = (int(width * scale), int(height * scale))
        img = img.resize(new_size, Image.LANCZOS)

    target_path = path.with_stem(f"{path.stem}-compressed")
    img.save(target_path, "JPEG", quality=quality, optimize=True)
    print(f"compressed {path.name} -> {target_path.name} ({new_size if scale < 1 else img.size})")


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    visual_dir = repo_root / "shard_workspace" / "visual_input"

    if not visual_dir.exists():
        print(f"No visual_input folder at {visual_dir}")
        return 1

    files = sorted(
        f for f in visual_dir.iterdir() if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    if not files:
        print("No visual files to compress.")
        return 0

    for path in files:
        compress_image(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
