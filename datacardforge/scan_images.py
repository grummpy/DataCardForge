"""Read class-folder images: root/<class>/*.(jpg|png|...)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError

from datacardforge.dupes import bits_to_hex, cluster_images, color_signature, dhash, empty_image_duplicates, sha256_file
from datacardforge.stats import SMALL_IMAGE_MIN_SIDE, balance_from_counts, empty_balance

Image.MAX_IMAGE_PIXELS = 80_000_000

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_SKIP_DIRS = {"__pycache__", "node_modules"}


def has_class_folders(root: Path) -> bool:
    return any(_class_images(path) for path in _class_dirs(root))


def scan(root: Path) -> dict:
    items = []
    errors: list[str] = []
    class_counts: dict[str, int] = {}
    widths: list[int] = []
    heights: list[int] = []
    small = 0
    unreadable = 0

    for folder in _class_dirs(root):
        readable_here = 0
        for path in _class_images(folder):
            relative = path.relative_to(root).as_posix()
            try:
                descriptor = _describe(path, relative)
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                unreadable += 1
                errors.append(f"{relative}: {exc}")
                continue
            items.append(descriptor)
            readable_here += 1
            widths.append(descriptor["width"])
            heights.append(descriptor["height"])
            if min(descriptor["width"], descriptor["height"]) < SMALL_IMAGE_MIN_SIDE:
                small += 1
        if readable_here:
            class_counts[folder.name] = class_counts.get(folder.name, 0) + readable_here

    if widths:
        resolution = {
            "count": len(widths),
            "min_width": min(widths),
            "max_width": max(widths),
            "min_height": min(heights),
            "max_height": max(heights),
            "mean_width": round(sum(widths) / len(widths), 1),
            "mean_height": round(sum(heights) / len(heights), 1),
            "min_side": min(min(w, h) for w, h in zip(widths, heights)),
            "small_image_count": small,
            "small_image_threshold": SMALL_IMAGE_MIN_SIDE,
        }
    else:
        resolution = {
            "count": 0,
            "min_width": None,
            "max_width": None,
            "min_height": None,
            "max_height": None,
            "mean_width": None,
            "mean_height": None,
            "min_side": None,
            "small_image_count": 0,
            "small_image_threshold": SMALL_IMAGE_MIN_SIDE,
        }

    duplicates = cluster_images(items) if items else empty_image_duplicates()
    duplicates["unreadable"] = unreadable
    balance = (
        balance_from_counts(class_counts, source="folders")
        if class_counts
        else empty_balance()
    )
    return {
        "classes": [
            {"label": label, "count": count}
            for label, count in sorted(class_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "readable": len(items),
        "unreadable": unreadable,
        "resolution": resolution,
        "duplicates": duplicates,
        "balance": balance,
        "errors": errors,
    }


def _describe(path: Path, relative: str) -> dict:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        rgb.load()
        width, height = rgb.size
        bits = dhash(rgb)
        color = color_signature(rgb)
    return {
        "path": relative,
        "width": width,
        "height": height,
        "sha256": sha256_file(path),
        "dhash": bits_to_hex(bits),
        "bits": bits,
        "color": color,
    }


def _class_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    folders = []
    for path in root.iterdir():
        if not path.is_dir() or path.name.startswith(".") or path.name in _SKIP_DIRS:
            continue
        folders.append(path)
    return sorted(folders, key=lambda path: path.name.lower())


def _class_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    images = [
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and not path.name.startswith(".")
    ]
    return sorted(images, key=lambda path: path.name.lower())
