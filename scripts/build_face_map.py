from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MIN_FACE_SIZE = 80
MIN_QUALITY_SCORE = 0.35
MODEL_VERSION = "face_recognition-1.3-128d"


class FaceMapError(Exception):
    """Raised when a face map cannot be built."""


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
        default=MIN_QUALITY_SCORE,
        help=f"Minimum acceptable quality score, default: {MIN_QUALITY_SCORE}",
    )
    return parser.parse_args()


def load_image(image_path: Path) -> np.ndarray:
    if not image_path.exists() or not image_path.is_file():
        raise FaceMapError(f"File not found: {image_path}")
    if image_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise FaceMapError(
            f"Unsupported file format: {image_path.suffix}. Use jpg, jpeg, or png."
        )

    try:
        image = Image.open(image_path)
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Exception as exc:  # pragma: no cover - depends on image codec errors
        raise FaceMapError(f"Unable to read image: {exc}") from exc

    max_side = 1600
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side))

    return np.array(image)


def compute_blur_score(image: np.ndarray) -> float:
    grayscale = image.mean(axis=2)
    grad_y = np.diff(grayscale, axis=0)
    grad_x = np.diff(grayscale, axis=1)
    variance = float(np.var(grad_x)) + float(np.var(grad_y))
    return min(1.0, variance / 1000.0)


def compute_brightness_score(image: np.ndarray) -> float:
    grayscale = image.mean(axis=2) / 255.0
    mean_brightness = float(grayscale.mean())
    return max(0.0, 1.0 - min(abs(mean_brightness - 0.55) / 0.55, 1.0))


def compute_face_size_score(bbox: tuple[int, int, int, int], image_shape: tuple[int, ...]) -> float:
    top, right, bottom, left = bbox
    face_width = right - left
    face_height = bottom - top
    short_side = min(image_shape[0], image_shape[1])
    ratio = min(face_width, face_height) / max(short_side, 1)
    return min(1.0, ratio / 0.25)


def compute_edge_margin_score(
    bbox: tuple[int, int, int, int],
    image_shape: tuple[int, ...],
) -> float:
    top, right, bottom, left = bbox
    height, width = image_shape[:2]
    margin = min(top, left, width - right, height - bottom)
    margin_ratio = margin / max(min(width, height), 1)
    return min(1.0, max(0.0, margin_ratio / 0.08))


def estimate_quality(image: np.ndarray, bbox: tuple[int, int, int, int]) -> float:
    top, right, bottom, left = bbox
    face_crop = image[top:bottom, left:right]
    if face_crop.size == 0:
        return 0.0

    face_width = right - left
    face_height = bottom - top
    if min(face_width, face_height) < MIN_FACE_SIZE:
        return 0.0

    blur_score = compute_blur_score(face_crop)
    brightness_score = compute_brightness_score(face_crop)
    face_size_score = compute_face_size_score(bbox, image.shape)
    edge_margin_score = compute_edge_margin_score(bbox, image.shape)

    quality = (
        0.35 * blur_score
        + 0.20 * brightness_score
        + 0.30 * face_size_score
        + 0.15 * edge_margin_score
    )
    return round(max(0.0, min(1.0, quality)), 4)


def select_single_face(face_locations: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    if not face_locations:
        raise FaceMapError("No face found in the image.")
    if len(face_locations) > 1:
        raise FaceMapError("Multiple faces found in the image.")
    return face_locations[0]


def normalize_landmarks(raw_landmarks: dict[str, list[tuple[int, int]]]) -> dict[str, Any]:
    def average(points: list[tuple[int, int]]) -> list[float]:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return [round(float(sum(xs) / len(xs)), 2), round(float(sum(ys) / len(ys)), 2)]

    return {
        "chin": [[int(x), int(y)] for x, y in raw_landmarks.get("chin", [])],
        "left_eyebrow": [[int(x), int(y)] for x, y in raw_landmarks.get("left_eyebrow", [])],
        "right_eyebrow": [[int(x), int(y)] for x, y in raw_landmarks.get("right_eyebrow", [])],
        "nose_bridge": [[int(x), int(y)] for x, y in raw_landmarks.get("nose_bridge", [])],
        "nose_tip": [[int(x), int(y)] for x, y in raw_landmarks.get("nose_tip", [])],
        "left_eye": [[int(x), int(y)] for x, y in raw_landmarks.get("left_eye", [])],
        "right_eye": [[int(x), int(y)] for x, y in raw_landmarks.get("right_eye", [])],
        "top_lip": [[int(x), int(y)] for x, y in raw_landmarks.get("top_lip", [])],
        "bottom_lip": [[int(x), int(y)] for x, y in raw_landmarks.get("bottom_lip", [])],
        "keypoints": {
            "left_eye_center": average(raw_landmarks["left_eye"]),
            "right_eye_center": average(raw_landmarks["right_eye"]),
            "nose_tip_center": average(raw_landmarks["nose_tip"]),
            "mouth_left": [int(raw_landmarks["top_lip"][0][0]), int(raw_landmarks["top_lip"][0][1])],
            "mouth_right": [int(raw_landmarks["top_lip"][6][0]), int(raw_landmarks["top_lip"][6][1])],
        },
    }


def build_face_map(image_path: Path, min_quality: float) -> dict[str, Any]:
    try:
        import face_recognition
    except ModuleNotFoundError as exc:
        raise FaceMapError(
            "Dependency 'face_recognition' is not installed. Run: pip install -r requirements.txt"
        ) from exc

    image = load_image(image_path)

    face_locations = face_recognition.face_locations(image, model="hog")
    bbox = select_single_face(face_locations)
    quality_score = estimate_quality(image, bbox)
    if quality_score < min_quality:
        raise FaceMapError(
            f"Low quality image. quality_score={quality_score}, required>={min_quality}"
        )

    encodings = face_recognition.face_encodings(image, known_face_locations=[bbox], num_jitters=1)
    if not encodings:
        raise FaceMapError("Unable to extract face embedding.")

    landmarks_list = face_recognition.face_landmarks(image, [bbox])
    if not landmarks_list:
        raise FaceMapError("Unable to extract facial landmarks.")

    embedding = encodings[0]
    embedding = embedding / np.linalg.norm(embedding)

    top, right, bottom, left = bbox
    return {
        "embedding": [round(float(value), 8) for value in embedding.tolist()],
        "embedding_size": int(len(embedding)),
        "bbox": {
            "top": int(top),
            "right": int(right),
            "bottom": int(bottom),
            "left": int(left),
            "width": int(right - left),
            "height": int(bottom - top),
        },
        "landmarks": normalize_landmarks(landmarks_list[0]),
        "quality_score": quality_score,
        "model_version": MODEL_VERSION,
        "source_image": str(image_path.resolve()),
    }


def main() -> int:
    args = parse_args()
    image_path = Path(args.image_path)

    try:
        result = build_face_map(image_path, min_quality=args.min_quality)
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
