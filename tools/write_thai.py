#!/usr/bin/env python3
"""Turn typed Thai text into a deterministic, seed-varied SVG handwriting file."""

from __future__ import annotations

import argparse
import hashlib
import html
import math
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from sample_seed import sample_glyph


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SKELETON_ROOT = PACKAGE_ROOT / "skeletons"
LINE_ADVANCE = 58.0
BASE_GAP = 5.0
UPPER_GAP = 1.5
LOWER_GAP = 1.5
OUTPUT_SCALE = 2.0

PERSONAS: dict[str, dict[str, Any]] = {
    "careful": {
        "label": "เป็นระเบียบ ตัวตั้ง",
        "profile": "natural", "head": "looped",
        "width": 0.94, "height": 1.04, "slant": -0.01,
        "stroke": 3.4, "hand_noise": 0.12,
    },
    "rounded": {
        "label": "กลมและเส้นหนัก",
        "profile": "natural", "head": "looped",
        "width": 1.06, "height": 1.00, "slant": 0.00,
        "stroke": 4.6, "hand_noise": 0.28,
    },
    "flat": {
        "label": "ตัวแบน ไม่มีหัว",
        "profile": "flat", "head": "headless",
        "width": 1.03, "height": 0.86, "slant": 0.015,
        "stroke": 4.0, "hand_noise": 0.35,
    },
    "slanted": {
        "label": "เอียงขวา",
        "profile": "natural", "head": "headless",
        "width": 0.97, "height": 1.01, "slant": 0.14,
        "stroke": 3.7, "hand_noise": 0.42,
    },
    "quick": {
        "label": "เขียนเร็ว ลดรูป",
        "profile": "reduced", "head": "headless",
        "width": 0.94, "height": 0.94, "slant": 0.18,
        "stroke": 3.3, "hand_noise": 0.58,
    },
    "messy": {
        "label": "ชุ่ย แกว่งสูงต่ำและเอียงไม่เท่ากัน",
        "profile": "reduced", "head": "headless",
        "width": 0.98, "height": 0.96, "slant": 0.13,
        "stroke": 4.0, "hand_noise": 1.6,
        "cluster_scale_x": 0.12, "cluster_scale_y": 0.25,
        "cluster_rotation": 0.12, "cluster_shift_x": 3.5,
        "cluster_shift_y": 9.0, "stroke_jitter": 1.1,
    },
}


def load_glyphs() -> dict[str, dict[str, Any]]:
    glyphs: dict[str, dict[str, Any]] = {}
    for path in SKELETON_ROOT.glob("*/*.json"):
        glyph = json.loads(path.read_text(encoding="utf-8"))
        glyphs[glyph["character"]] = glyph
    return glyphs


def bounds(glyph: dict[str, Any]) -> tuple[float, float, float, float]:
    points = [point for stroke in glyph["strokes"] for point in stroke["points"]]
    if not points:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(float(point["x"]) for point in points),
        min(float(point["y"]) for point in points),
        max(float(point["x"]) for point in points),
        max(float(point["y"]) for point in points),
    )


def translate(glyph: dict[str, Any], dx: float, dy: float) -> None:
    for stroke in glyph["strokes"]:
        for point in stroke["points"]:
            point["x"] = round(float(point["x"]) + dx, 3)
            point["y"] = round(float(point["y"]) + dy, 3)


def layout_text(
    text: str,
    seed: str | int,
    catalog: dict[str, dict[str, Any]],
    persona: dict[str, Any] | None = None,
    features: dict[str, str] | None = None,
    head_mode: str | None = None,
) -> list[dict[str, Any]]:
    missing = sorted({char for char in text if not char.isspace() and char not in catalog})
    if missing:
        details = ", ".join(f"{char} (U+{ord(char):04X})" for char in missing)
        raise ValueError(f"ไม่มี skeleton สำหรับ: {details}")

    placed: list[dict[str, Any]] = []
    counts: defaultdict[str, int] = defaultdict(int)
    cursor_x = 0.0
    last_base: dict[str, Any] | None = None
    pending_preposed: list[dict[str, Any]] = []
    next_cluster_id = 0

    for char in text:
        if char.isspace():
            for preposed in pending_preposed:
                preposed["_cluster_id"] = next_cluster_id
                next_cluster_id += 1
                translate(preposed, cursor_x, 0)
                placed.append(preposed)
                cursor_x += LINE_ADVANCE
            pending_preposed.clear()
            last_base = None
            cursor_x += LINE_ADVANCE * (0.45 if char == " " else 1.0)
            continue

        occurrence = counts[char]
        counts[char] += 1
        supported_features = {
            component["id"] for component in catalog[char].get("optional_components", [])
        }
        glyph = sample_glyph(
            catalog[char], seed, occurrence,
            style_id=persona["profile"] if persona else None,
            head_mode=head_mode if head_mode is not None else (persona["head"] if persona else None),
            features={key: state for key, state in (features or {}).items() if key in supported_features},
        )
        glyph["_cluster_id"] = None
        kind = glyph["placement"]["kind"]
        if kind == "spacing_preposed":
            pending_preposed.append(glyph)
            continue

        if kind == "combining_above":
            if last_base is None:
                glyph["_cluster_id"] = next_cluster_id
                next_cluster_id += 1
                translate(glyph, cursor_x, 0)
                placed.append(glyph)
                continue
            glyph["_cluster_id"] = last_base["cluster_id"]
            mx0, my0, mx1, my1 = bounds(glyph)
            bx0, _, bx1, _ = last_base["bounds"]
            center_dx = (bx0 + bx1) / 2 - (mx0 + mx1) / 2
            target_bottom = last_base["top_y"] - UPPER_GAP
            dy = target_bottom - my1
            translate(glyph, center_dx, dy)
            placed.append(glyph)
            _, top, _, _ = bounds(glyph)
            last_base["top_y"] = top
            continue

        if kind == "combining_below":
            if last_base is None:
                glyph["_cluster_id"] = next_cluster_id
                next_cluster_id += 1
                translate(glyph, cursor_x, 0)
                placed.append(glyph)
                continue
            glyph["_cluster_id"] = last_base["cluster_id"]
            mx0, my0, mx1, _ = bounds(glyph)
            bx0, _, bx1, _ = last_base["bounds"]
            center_dx = (bx0 + bx1) / 2 - (mx0 + mx1) / 2
            target_top = last_base["bottom_y"] + LOWER_GAP
            dy = target_top - my0
            translate(glyph, center_dx, dy)
            placed.append(glyph)
            _, _, _, bottom = bounds(glyph)
            last_base["bottom_y"] = bottom
            cursor_x = max(cursor_x, bounds(glyph)[2] + BASE_GAP)
            continue

        if kind == "spacing_vowel" and last_base is not None:
            # Right-side Thai vowels join the previous base; align their left
            # edge just inside the base's right edge, then grow the next slot.
            mx0, _, _, _ = bounds(glyph)
            glyph["_cluster_id"] = last_base["cluster_id"]
            _, _, base_right, _ = last_base["bounds"]
            dx = base_right - mx0 - 4.0
            translate(glyph, dx, 0)
            placed.append(glyph)
            _, _, vowel_right, _ = bounds(glyph)
            last_base["right_x"] = max(last_base["right_x"], vowel_right)
            cursor_x = max(cursor_x, last_base["right_x"] + BASE_GAP)
            continue

        # A consonant, independent vowel, digit, or symbol starts a new base.
        x = cursor_x
        cluster_id = next_cluster_id
        next_cluster_id += 1
        glyph["_cluster_id"] = cluster_id
        translate(glyph, x, 0)
        base_bounds = bounds(glyph)
        placed.append(glyph)
        last_base = {
            "x": x,
            "bounds": base_bounds,
            "top_y": base_bounds[1],
            "bottom_y": base_bounds[3],
            "right_x": base_bounds[2],
            "cluster_id": cluster_id,
        }

        if pending_preposed:
            # Place one or more preposed vowels immediately to the left of the
            # base, using their actual sampled bounds to avoid a fixed-font fit.
            edge = base_bounds[0] - BASE_GAP
            for preposed in reversed(pending_preposed):
                px0, _, px1, _ = bounds(preposed)
                dx = edge - px1
                preposed["_cluster_id"] = cluster_id
                translate(preposed, dx, 0)
                placed.append(preposed)
                edge = bounds(preposed)[0] - BASE_GAP
            pending_preposed.clear()

        cursor_x = max(x + LINE_ADVANCE, base_bounds[2] + BASE_GAP)

    # A dangling preposed vowel still becomes visible at the end of the line.
    for glyph in pending_preposed:
        glyph["_cluster_id"] = next_cluster_id
        next_cluster_id += 1
        translate(glyph, cursor_x, 0)
        placed.append(glyph)
        cursor_x += LINE_ADVANCE
    return placed


def apply_persona(placed: list[dict[str, Any]], persona_id: str, seed: str | int) -> None:
    persona = PERSONAS[persona_id]
    points = [point for glyph in placed for stroke in glyph["strokes"] for point in stroke["points"]]
    if not points:
        return
    min_x = min(float(point["x"]) for point in points)
    max_x = max(float(point["x"]) for point in points)
    min_y = min(float(point["y"]) for point in points)
    max_y = max(float(point["y"]) for point in points)
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    material = f"persona\0{persona_id}\0{seed}".encode("utf-8")
    rng = random.Random(int.from_bytes(hashlib.sha256(material).digest()[:8], "big"))

    for point in points:
        x = float(point["x"])
        y = float(point["y"])
        x = center_x + (x - center_x) * float(persona["width"]) + float(persona["slant"]) * (y - center_y)
        y = center_y + (y - center_y) * float(persona["height"])
        if not point.get("locked", False):
            noise = float(persona["hand_noise"])
            x += rng.uniform(-noise, noise)
            y += rng.uniform(-noise, noise)
        point["x"] = round(x, 3)
        point["y"] = round(y, 3)

    # Apply one shared transform to each Thai grapheme cluster so tone marks,
    # vowels and the base character wobble together instead of coming apart.
    if persona_id == "messy":
        clusters: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
        for glyph in placed:
            cluster_id = glyph.get("_cluster_id")
            if cluster_id is not None:
                clusters[int(cluster_id)].append(glyph)
        for cluster_id, glyphs in sorted(clusters.items()):
            cluster_points = [
                point for glyph in glyphs for stroke in glyph["strokes"] for point in stroke["points"]
            ]
            if not cluster_points:
                continue
            x0 = min(float(point["x"]) for point in cluster_points)
            x1 = max(float(point["x"]) for point in cluster_points)
            y0 = min(float(point["y"]) for point in cluster_points)
            y1 = max(float(point["y"]) for point in cluster_points)
            pivot_x = (x0 + x1) / 2
            pivot_y = (y0 + y1) / 2
            local_rng = random.Random(rng.getrandbits(64) ^ cluster_id)
            scale_x = 1 + local_rng.uniform(-persona["cluster_scale_x"], persona["cluster_scale_x"])
            scale_y = 1 + local_rng.uniform(-persona["cluster_scale_y"], persona["cluster_scale_y"])
            angle = local_rng.uniform(-persona["cluster_rotation"], persona["cluster_rotation"])
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            shift_x = local_rng.uniform(-persona["cluster_shift_x"], persona["cluster_shift_x"])
            shift_y = local_rng.uniform(-persona["cluster_shift_y"], persona["cluster_shift_y"])
            for point in cluster_points:
                dx = (float(point["x"]) - pivot_x) * scale_x
                dy = (float(point["y"]) - pivot_y) * scale_y
                point["x"] = round(pivot_x + dx * cos_a - dy * sin_a + shift_x, 3)
                point["y"] = round(pivot_y + dx * sin_a + dy * cos_a + shift_y, 3)

    for glyph in placed:
        stroke_jitter = float(persona.get("stroke_jitter", 0.22))
        width = float(persona["stroke"]) + rng.uniform(-stroke_jitter, stroke_jitter)
        glyph["metrics"]["sampled_stroke_width"] = round(width, 2)
        glyph["sampling"]["persona"] = persona_id


def _path_data(stroke: dict[str, Any]) -> str:
    points = {point["id"]: point for point in stroke["points"]}
    chunks: list[str] = []
    for index, segment in enumerate(stroke.get("segments", [])):
        start = points[segment["from"]]
        c1 = points[segment["control_1"]]
        c2 = points[segment["control_2"]]
        end = points[segment["to"]]
        if index == 0:
            chunks.append(f"M {float(start['x']):.3f} {float(start['y']):.3f}")
        chunks.append(
            "C "
            f"{float(c1['x']):.3f} {float(c1['y']):.3f}, "
            f"{float(c2['x']):.3f} {float(c2['y']):.3f}, "
            f"{float(end['x']):.3f} {float(end['y']):.3f}"
        )
    if chunks and stroke.get("closed"):
        chunks.append("Z")
    return " ".join(chunks)


def render_svg(
    text: str,
    placed: list[dict[str, Any]],
    color: str = "#202020",
    seed: str | int = "0",
    persona_id: str | None = None,
) -> str:
    all_points = [
        (float(point["x"]), float(point["y"]))
        for glyph in placed
        for stroke in glyph["strokes"]
        for point in stroke["points"]
    ]
    if not all_points:
        raise ValueError("ข้อความนี้ไม่มีเส้นสำหรับวาด")
    max_stroke = max(float(glyph["metrics"].get("sampled_stroke_width", 4.0)) for glyph in placed)
    padding = max_stroke + 5
    min_x = min(x for x, _ in all_points) - max_stroke / 2
    min_y = min(y for _, y in all_points) - max_stroke / 2
    max_x = max(x for x, _ in all_points) + max_stroke / 2
    max_y = max(y for _, y in all_points) + max_stroke / 2
    width = max_x - min_x + padding * 2
    height = max_y - min_y + padding * 2
    translate_x = padding - min_x
    translate_y = padding - min_y

    escaped_text = html.escape(text)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width * OUTPUT_SCALE:.0f}px" height="{height * OUTPUT_SCALE:.0f}px" viewBox="0 0 {width:.3f} {height:.3f}" data-seed="{html.escape(str(seed), quote=True)}" data-persona="{html.escape(persona_id or "seeded", quote=True)}">',
        f"  <title>ลายมือ: {escaped_text}</title>",
        f'  <rect width="{width:.3f}" height="{height:.3f}" fill="#ffffff"/>',
    ]
    for glyph in placed:
        stroke_width = float(glyph["metrics"].get("sampled_stroke_width", 4.0))
        parts.append(
            f'  <g data-character="{html.escape(glyph["character"])}" '
            f'data-style="{html.escape(glyph.get("sampling", {}).get("style", ""), quote=True)}" '
            f'data-head-mode="{html.escape(glyph.get("sampling", {}).get("head_mode", ""), quote=True)}" '
            f'data-features="{html.escape(json.dumps(glyph.get("sampling", {}).get("features", {}), ensure_ascii=False, sort_keys=True), quote=True)}" '
            f'transform="translate({translate_x:.3f} {translate_y:.3f})" '
            f'fill="none" stroke="{html.escape(color, quote=True)}" '
            f'stroke-width="{stroke_width:.3f}" stroke-linecap="round" stroke-linejoin="round">'
        )
        for stroke in glyph["strokes"]:
            path = _path_data(stroke)
            if path:
                parts.append(f'    <path d="{path}"/>')
        parts.append("  </g>")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def default_filename(text: str) -> str:
    stem = re.sub(r"[^\w-]+", "_", text.strip(), flags=re.UNICODE).strip("_")
    return f"{stem or 'thai-handwriting'}.svg"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="พิมพ์ข้อความไทยแล้วสร้างไฟล์ลายมือ SVG จากชุด skeleton",
        epilog='ตัวอย่าง: python3 tools/write_thai.py สวัสดี --seed 42',
    )
    parser.add_argument("text", nargs="?", help="ข้อความที่จะสร้างเป็นลายมือ; ถ้าไม่ระบุจะถามใน terminal")
    parser.add_argument("--seed", default="0", help="seed สำหรับเลือกรูปแบบลายมือ (ค่าเริ่มต้น: 0)")
    parser.add_argument("-o", "--output", type=Path, help="ชื่อไฟล์ SVG ปลายทาง")
    parser.add_argument("--color", default="#202020", help="สีเส้น SVG (ค่าเริ่มต้น: #202020)")
    parser.add_argument(
        "--persona", choices=sorted(PERSONAS),
        help="เลือกแบบลายมือคงที่ เช่น careful, rounded, flat, slanted, quick, messy",
    )
    parser.add_argument(
        "--head-mode", choices=("looped", "headless"),
        help="บังคับให้มีวงหัวหรือตัดวงหัวออกทั้งส่วน สำหรับตัวที่มีตัวเลือกหัว",
    )
    parser.add_argument(
        "--feature", action="append", default=[], metavar="ID=STATE",
        help="บังคับส่วนเสริม เช่น beak=present หรือ beak=absent; ใช้ซ้ำได้",
    )
    args = parser.parse_args()

    text = args.text if args.text is not None else input("พิมพ์ข้อความที่ต้องการสร้าง: ")
    if not text:
        parser.error("กรุณาพิมพ์ข้อความอย่างน้อยหนึ่งตัวอักษร")
    try:
        features: dict[str, str] = {}
        for assignment in args.feature:
            if "=" not in assignment:
                parser.error("--feature ต้องใช้รูปแบบ ID=STATE")
            feature_id, state = assignment.split("=", 1)
            if not feature_id or feature_id in features:
                parser.error(f"ส่วนเสริมซ้ำหรือไม่ถูกต้อง: {assignment!r}")
            features[feature_id] = state
        persona = PERSONAS[args.persona] if args.persona else None
        catalog = load_glyphs()
        available_features = {
            component["id"] for glyph in catalog.values()
            for component in glyph.get("optional_components", [])
        }
        unknown_features = sorted(set(features) - available_features)
        if unknown_features:
            raise ValueError(f"ไม่มีส่วนเสริมที่รองรับ: {', '.join(unknown_features)}")
        placed = layout_text(text, args.seed, catalog, persona, features, args.head_mode)
        if args.persona:
            apply_persona(placed, args.persona, args.seed)
        svg = render_svg(text, placed, args.color, args.seed, args.persona)
    except (ValueError, KeyError) as exc:
        print(f"ผิดพลาด: {exc}", file=sys.stderr)
        return 2

    output = args.output or Path.cwd() / default_filename(text)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8")
    print(f"สร้างไฟล์แล้ว: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
