"""Exact row duplicates and image duplicates (SHA-256 plus a perceptual hash)."""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from datacardforge.stats import NEAR_COLOR_MAE_MAX, NEAR_HAMMING_MAX

HASH_SIZE = 8


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dhash(image: Image.Image, hash_size: int = HASH_SIZE) -> tuple[int, ...]:
    """Difference hash: 64 bits of horizontal grayscale gradients."""
    gray = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.BOX)
    pixels = list(gray.tobytes())
    bits: list[int] = []
    width = hash_size + 1
    for y in range(hash_size):
        row = pixels[y * width : (y + 1) * width]
        for x in range(hash_size):
            bits.append(1 if row[x] > row[x + 1] else 0)
    return tuple(bits)


def bits_to_hex(bits: tuple[int, ...]) -> str:
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    width = max(1, len(bits) // 4)
    return f"{value:0{width}x}"


def color_signature(image: Image.Image) -> tuple[tuple[int, int, int], ...]:
    small = image.convert("RGB").resize((HASH_SIZE, HASH_SIZE), Image.Resampling.BOX)
    raw = small.tobytes()
    return tuple((raw[index], raw[index + 1], raw[index + 2]) for index in range(0, len(raw), 3))


def hamming(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    return sum(a != b for a, b in zip(left, right))


def color_mae(
    left: tuple[tuple[int, int, int], ...],
    right: tuple[tuple[int, int, int], ...],
) -> float:
    if not left or len(left) != len(right):
        return 255.0
    total = 0
    for (r1, g1, b1), (r2, g2, b2) in zip(left, right):
        total += abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)
    return total / (len(left) * 3)


def row_duplicates(records: list[dict], columns: list[str]) -> dict:
    keys = [tuple(_norm(record.get(column)) for column in columns) for record in records]
    counts = Counter(keys)
    groups = sum(1 for count in counts.values() if count > 1)
    extra = sum(count - 1 for count in counts.values() if count > 1)
    in_groups = sum(count for count in counts.values() if count > 1)
    return {
        "extra_duplicate_rows": extra,
        "rows_in_duplicate_groups": in_groups,
        "duplicate_groups": groups,
    }


def cluster_images(items: list[dict]) -> dict:
    """Group exact SHA-256 copies and perceptually near copies.

    A near-duplicate joins a group only when it is close to every member
    (complete linkage), so a chain of mildly similar pictures does not
    collapse into one group. `near_extra_files` counts extra distinct
    file hashes, so an exact copy is not also counted as a near copy.
    """
    by_sha: dict[str, list[str]] = defaultdict(list)
    for item in items:
        by_sha[item["sha256"]].append(item["path"])

    exact_groups = []
    for sha, paths in by_sha.items():
        if len(paths) < 2:
            continue
        exact_groups.append(
            {
                "sha256": sha,
                "paths": sorted(paths),
                "count": len(paths),
                "extra": len(paths) - 1,
            }
        )
    exact_groups.sort(key=lambda group: group["paths"])

    order = sorted(range(len(items)), key=lambda index: items[index]["path"])
    unused = set(order)
    clusters: list[list[dict]] = []
    for index in order:
        if index not in unused:
            continue
        group = [items[index]]
        unused.remove(index)
        grew = True
        while grew:
            grew = False
            for other in list(unused):
                candidate = items[other]
                if all(_near(candidate, member) for member in group):
                    group.append(candidate)
                    unused.remove(other)
                    grew = True
        clusters.append(group)

    near_groups = []
    for members in clusters:
        distinct = {member["sha256"] for member in members}
        if len(distinct) < 2:
            continue
        max_hamming = 0
        max_mae = 0.0
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                max_hamming = max(max_hamming, hamming(left["bits"], right["bits"]))
                max_mae = max(max_mae, color_mae(left["color"], right["color"]))
        near_groups.append(
            {
                "paths": sorted(member["path"] for member in members),
                "distinct_files": len(distinct),
                "extra": len(distinct) - 1,
                "max_hamming": max_hamming,
                "max_color_mae": round(max_mae, 2),
            }
        )
    near_groups.sort(key=lambda group: group["paths"])

    return {
        "compared": len(items),
        "exact_extra_files": sum(group["extra"] for group in exact_groups),
        "exact_groups": exact_groups,
        "near_extra_files": sum(group["extra"] for group in near_groups),
        "near_groups": near_groups,
        "method": (
            "SHA-256 for exact copies; dHash (64-bit) Hamming distance "
            f"<= {NEAR_HAMMING_MAX} and 8x8 color MAE <= {NEAR_COLOR_MAE_MAX:g} "
            "for near-duplicates"
        ),
    }


def empty_image_duplicates() -> dict:
    report = cluster_images([])
    report["unreadable"] = 0
    return report


def _near(left: dict, right: dict) -> bool:
    return (
        hamming(left["bits"], right["bits"]) <= NEAR_HAMMING_MAX
        and color_mae(left["color"], right["color"]) <= NEAR_COLOR_MAE_MAX
    )


def _norm(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (str, int, float, bool, bytes)):
        return value
    return str(value)
