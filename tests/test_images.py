import importlib.util
import shutil
from pathlib import Path

from PIL import Image

from datacardforge.dupes import color_mae, color_signature, dhash, hamming
from datacardforge.stats import NEAR_COLOR_MAE_MAX, NEAR_HAMMING_MAX
from datacardforge.store import save_edits, scan_and_merge

ROOT = Path(__file__).resolve().parents[1]


def load_generate():
    spec = importlib.util.spec_from_file_location("generate_samples", ROOT / "samples" / "generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_brightness_shift_is_near_and_a_different_shape_is_not():
    generate = load_generate()
    base = generate.draw_circle((180, 48, 42))
    near = base.copy()
    pixels = near.load()
    for y in range(near.size[1]):
        for x in range(near.size[0]):
            red, green, blue = pixels[x, y]
            pixels[x, y] = (min(255, red + 12), min(255, green + 12), min(255, blue + 12))
    other = generate.draw_square((46, 92, 210))
    assert hamming(dhash(base), dhash(near)) <= NEAR_HAMMING_MAX
    assert color_mae(color_signature(base), color_signature(near)) <= NEAR_COLOR_MAE_MAX
    same_shape = hamming(dhash(base), dhash(other)) <= NEAR_HAMMING_MAX
    same_color = color_mae(color_signature(base), color_signature(other)) <= NEAR_COLOR_MAE_MAX
    assert not (same_shape and same_color)


def build_image_dataset(folder: Path):
    generate = load_generate()
    red = folder / "circle" / "red.jpg"
    generate.save_jpeg(generate.draw_circle((180, 48, 42), generate.CIRCLE_SIZE), red)
    shutil.copyfile(red, folder / "circle" / "red_copy.jpg")
    generate.brighten_file(red, folder / "circle" / "red_near.jpg", 12)
    generate.save_jpeg(generate.draw_square((46, 92, 210), generate.SQUARE_SIZE), folder / "square" / "blue.jpg")
    generate.save_jpeg(generate.draw_tiny(), folder / "square" / "tiny.jpg")
    return folder


def test_image_resolution_exact_and_near_duplicates(tmp_path):
    folder = build_image_dataset(tmp_path / "images")
    card = scan_and_merge(folder)
    assert card["kind"] == "images"
    assert card["size"]["rows"] == 0
    assert card["size"]["columns"] == 0
    assert card["size"]["images"] == 5
    assert card["size"]["files"] == 5
    resolution = card["size"]["resolution"]
    assert resolution["min_side"] == 16
    assert resolution["min_width"] == 16
    assert resolution["max_width"] == 128
    assert resolution["mean_width"] == 99.2
    assert resolution["mean_height"] == 99.2
    assert resolution["small_image_count"] == 1

    counts = {row["label"]: row["count"] for row in card["class_balance"]["counts"]}
    assert counts == {"circle": 3, "square": 2}
    assert card["class_balance"]["source"] == "folders"

    images = card["duplicates"]["images"]
    assert images["exact_extra_files"] == 1
    assert len(images["exact_groups"]) == 1
    assert images["near_extra_files"] == 1
    assert len(images["near_groups"]) == 1
    assert "sha256" in images["method"].lower() or "SHA-256" in images["method"]
    assert any("smaller than 32px" in gap for gap in card["known_gaps"]["auto"])
    assert card["schema"] == []
    assert card["pii_hints"] == []


def test_unreadable_image_does_not_abort_the_scan(tmp_path):
    folder = tmp_path / "mixed"
    generate = load_generate()
    generate.save_jpeg(generate.draw_circle((180, 48, 42)), folder / "circle" / "ok.jpg")
    (folder / "circle" / "bad.jpg").write_bytes(b"this is not a jpeg")
    card = scan_and_merge(folder)
    assert card["size"]["images"] == 1
    assert card["size"]["unreadable_images"] == 1
    assert card["duplicates"]["images"]["unreadable"] == 1
    assert card["errors"]


def test_image_description_survives_rescan(tmp_path):
    folder = build_image_dataset(tmp_path / "kept")
    card = scan_and_merge(folder)
    save_edits(folder, {"description": "Shapes drawn for a local demo."})
    generate = load_generate()
    generate.save_jpeg(generate.draw_triangle((20, 160, 90)), folder / "triangle" / "one.jpg")
    again = scan_and_merge(folder)
    assert again["overview"]["description"]["value"] == "Shapes drawn for a local demo."
    assert again["overview"]["description"]["source"] == "user"
    assert again["size"]["images"] == 6
    with Image.open(folder / "triangle" / "one.jpg") as image:
        assert image.size[0] > 0
