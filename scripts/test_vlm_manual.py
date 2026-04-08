from __future__ import annotations

from pathlib import Path

from backend.vlm_ingestion import describe_images


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    visual_input_dir = repo_root / "shard_workspace" / "visual_input"

    if not visual_input_dir.exists():
        print(f"[VLM TEST] Directory not found: {visual_input_dir}")
        return 1

    image_paths = sorted(
        str(path)
        for path in visual_input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    )

    if not image_paths:
        print(f"[VLM TEST] No images found in: {visual_input_dir}")
        return 0

    print(f"[VLM TEST] Found {len(image_paths)} image(s)")
    print(f"[VLM TEST] Topic: attention mechanism")
    print()

    output = describe_images(image_paths, topic="attention mechanism")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
