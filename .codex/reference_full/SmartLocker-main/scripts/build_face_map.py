from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.modules.biometrics.face_map import FaceMapError, build_face_map_from_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a face map (embedding) from a single photo.",
    )
    parser.add_argument("image_path", help="Path to the input photo.")
    parser.add_argument(
        "-o",
        "--output",
        help="Optional path to save the resulting JSON. Prints to stdout if omitted.",
    )
    parser.add_argument(
        "--min-quality",
        type=float,
        default=0.35,
        help="Minimum acceptable quality score, default: 0.35",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image_path = Path(args.image_path)

    try:
        result = build_face_map_from_path(image_path, min_quality=args.min_quality)
    except FaceMapError as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(payload, encoding="utf-8")
        print(f"Saved face map to {output_path.resolve()}")
        return 0

    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
