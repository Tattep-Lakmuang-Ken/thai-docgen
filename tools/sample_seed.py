#!/usr/bin/env python3
"""Deterministically sample one Thai glyph skeleton using a seed.

The sampled JSON retains the source schema and adds a ``sampling`` record.
It can be passed to a renderer that reads the ``strokes`` / ``segments`` data.
Only Python's standard library is required.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SKELETON_ROOT = PACKAGE_ROOT / "skeletons"
PERSON_HEAD_MODE_WEIGHTS = (("looped", 0.65), ("headless", 0.35))


def _rng(seed: str | int, codepoint: str, occurrence: int) -> random.Random:
    material = f"{seed}\0{codepoint}\0{occurrence}".encode("utf-8")
    value = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
    return random.Random(value)


def choose_person_head_mode(seed: str | int) -> str:
    """Choose one repeatable head habit for the writer represented by a seed."""
    material = f"{seed}\0person-head-mode".encode("utf-8")
    value = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
    rng = random.Random(value)
    pick = rng.random() * sum(weight for _, weight in PERSON_HEAD_MODE_WEIGHTS)
    for mode, weight in PERSON_HEAD_MODE_WEIGHTS:
        pick -= weight
        if pick < 0:
            return mode
    return PERSON_HEAD_MODE_WEIGHTS[-1][0]


def _weighted_choice(rng: random.Random, choices: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(float(choice["weight"]) for choice in choices)
    pick = rng.random() * total
    for choice in choices:
        pick -= float(choice["weight"])
        if pick < 0:
            return choice
    return choices[-1]


def _uniform(rng: random.Random, bounds: list[float]) -> float:
    return rng.uniform(float(bounds[0]), float(bounds[1]))


def _transform(glyph: dict[str, Any], rng: random.Random, profile: dict[str, Any]) -> None:
    points = [point for stroke in glyph["strokes"] for point in stroke["points"]]
    if not points:
        return

    min_x = min(float(point["x"]) for point in points)
    max_x = max(float(point["x"]) for point in points)
    min_y = min(float(point["y"]) for point in points)
    max_y = max(float(point["y"]) for point in points)
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    width_scale = _uniform(rng, profile["width_scale"])
    height_scale = _uniform(rng, profile["height_scale"])
    slant = _uniform(rng, profile["slant"])
    translate_x = rng.uniform(-0.5, 0.5)
    translate_y = rng.uniform(-0.5, 0.5)
    jitter_scale = float(profile["point_jitter_scale"])
    simplify = _uniform(rng, profile["curve_simplify"])

    for point in points:
        x = float(point["x"])
        y = float(point["y"])
        sx = center_x + (x - center_x) * width_scale
        sy = center_y + (y - center_y) * height_scale
        sx += slant * (sy - center_y) + translate_x
        sy += translate_y

        if not point.get("locked", False):
            sx += rng.uniform(-float(point.get("max_shift_x", 0)), float(point.get("max_shift_x", 0))) * jitter_scale
            sy += rng.uniform(-float(point.get("max_shift_y", 0)), float(point.get("max_shift_y", 0))) * jitter_scale

        point["x"] = round(sx, 3)
        point["y"] = round(sy, 3)

    # Gently pull cubic handles toward their chord. This gives a less ornate,
    # more quickly written look without deleting a character's defining path.
    by_id = {point["id"]: point for point in points}
    for stroke in glyph["strokes"]:
        for segment in stroke.get("segments", []):
            if segment.get("type") != "cubic_bezier":
                continue
            start = by_id[segment["from"]]
            c1 = by_id[segment["control_1"]]
            c2 = by_id[segment["control_2"]]
            end = by_id[segment["to"]]
            x0, y0 = float(start["x"]), float(start["y"])
            x3, y3 = float(end["x"]), float(end["y"])
            for control, fraction in ((c1, 1 / 3), (c2, 2 / 3)):
                control["x"] = round(float(control["x"]) * (1 - simplify) + (x0 + (x3 - x0) * fraction) * simplify, 3)
                control["y"] = round(float(control["y"]) * (1 - simplify) + (y0 + (y3 - y0) * fraction) * simplify, 3)


def _apply_head_mode(
    glyph: dict[str, Any], rng: random.Random, metadata: dict[str, Any], requested_mode: str | None = None
) -> str:
    options = metadata.get("head_options", [])
    if not options:
        head = glyph.get("letter_features", {}).get("head", {})
        if head.get("presence") == "absent":
            return "none"
        if head.get("reference_form") == "open_terminal":
            return "unlooped"
        return "not_applicable"
    if requested_mode is None:
        selected_mode = _weighted_choice(rng, metadata["head_modes"])["id"]
    else:
        valid_modes = {mode["id"] for mode in metadata["head_modes"]}
        if requested_mode not in valid_modes:
            raise ValueError(f"Unsupported head mode {requested_mode!r} for {glyph['codepoint']}")
        selected_mode = requested_mode
    if selected_mode == "looped":
        return "looped"

    # A headless form omits the entire closed head component. Leaving a gap in
    # the loop would still draw a head, which is a different handwriting form.
    removed_stroke_ids = {option["stroke_id"] for option in options}
    removed_strokes = [
        stroke for stroke in glyph["strokes"] if stroke["stroke_id"] in removed_stroke_ids
    ]
    if len(removed_strokes) != len(removed_stroke_ids) or any(
        not stroke.get("closed") for stroke in removed_strokes
    ):
        raise ValueError(f"Invalid head component metadata for {glyph['codepoint']}")
    removed_point_ids = {
        point["id"] for stroke in removed_strokes for point in stroke["points"]
    }
    glyph["strokes"] = [
        stroke for stroke in glyph["strokes"] if stroke["stroke_id"] not in removed_stroke_ids
    ]
    for point_ids in glyph.get("point_groups", {}).values():
        point_ids[:] = [point_id for point_id in point_ids if point_id not in removed_point_ids]
    critical = glyph.get("distinguishing_features", {}).get("critical_points")
    if critical is not None:
        critical[:] = [point_id for point_id in critical if point_id not in removed_point_ids]
    return "headless"


def _apply_optional_components(
    glyph: dict[str, Any],
    rng: random.Random,
    requested: dict[str, str] | None = None,
) -> dict[str, str]:
    """Select optional letter features and apply their declared geometry edits."""
    components = glyph.get("optional_components", [])
    by_id = {component["id"]: component for component in components}
    requested = requested or {}
    unknown = sorted(set(requested) - set(by_id))
    if unknown:
        raise ValueError(f"Unsupported optional feature(s) for {glyph['codepoint']}: {', '.join(unknown)}")

    selected: dict[str, str] = {}
    for component in components:
        feature_id = component["id"]
        choices = component["choices"]
        state = requested.get(feature_id)
        valid_states = {choice["id"] for choice in choices}
        if state is None:
            state = _weighted_choice(rng, choices)["id"]
        elif state not in valid_states:
            raise ValueError(
                f"Unsupported state {state!r} for feature {feature_id!r} on {glyph['codepoint']}"
            )

        geometry = component["geometry"]
        stroke_id = geometry["stroke_id"]
        if state == "absent":
            prepend = geometry.get("prepend_segment_by_state", {}).get(state)
            if prepend:
                point_map = {
                    point["id"]: point
                    for stroke in glyph["strokes"]
                    for point in stroke["points"]
                }
                start = point_map.get(prepend["from_point_id"])
                end = point_map.get(prepend["to_point_id"])
                target = next(
                    (stroke for stroke in glyph["strokes"] if stroke["stroke_id"] == prepend["target_stroke_id"]),
                    None,
                )
                if start is None or end is None or target is None:
                    raise ValueError(f"Feature {feature_id!r} refers to missing segment anchors")
                x0, y0 = float(start["x"]), float(start["y"])
                x1, y1 = float(end["x"]), float(end["y"])
                fractions = prepend["control_fractions"]
                start_id, control1_id, control2_id = prepend["point_ids"]
                new_points = [
                    {"id": start_id, "x": round(x0, 3), "y": round(y0, 3), "role": "shape_critical", "locked": True, "max_shift_x": 0.0, "max_shift_y": 0.0},
                    {"id": control1_id, "x": round(x0 + (x1 - x0) * float(fractions[0]), 3), "y": round(y0 + (y1 - y0) * float(fractions[0]), 3), "role": "curve", "locked": True, "max_shift_x": 0.0, "max_shift_y": 0.0},
                    {"id": control2_id, "x": round(x0 + (x1 - x0) * float(fractions[1]), 3), "y": round(y0 + (y1 - y0) * float(fractions[1]), 3), "role": "curve", "locked": True, "max_shift_x": 0.0, "max_shift_y": 0.0},
                ]
                target["points"][0:0] = new_points
                target.setdefault("segments", []).insert(0, {
                    "type": "cubic_bezier",
                    "from": start_id,
                    "control_1": control1_id,
                    "control_2": control2_id,
                    "to": prepend["to_point_id"],
                })
                for group_id in prepend.get("point_groups", []):
                    group = glyph.get("point_groups", {}).get(group_id)
                    if group is not None:
                        group[0:0] = [point["id"] for point in new_points]
                critical = glyph.get("distinguishing_features", {}).get("critical_points")
                if critical is not None:
                    critical[0:0] = prepend.get("critical_point_ids", [])

            state_strokes = geometry.get("remove_stroke_ids_by_state", {}).get(state, [stroke_id])
            removed_ids = {
                point["id"]
                for stroke in glyph["strokes"]
                if stroke["stroke_id"] in state_strokes
                for point in stroke["points"]
            }
            glyph["strokes"] = [
                stroke for stroke in glyph["strokes"] if stroke["stroke_id"] not in state_strokes
            ]
            for point_ids in glyph.get("point_groups", {}).values():
                point_ids[:] = [point_id for point_id in point_ids if point_id not in removed_ids]
            critical = glyph.get("distinguishing_features", {}).get("critical_points")
            if critical is not None:
                critical[:] = [point_id for point_id in critical if point_id not in removed_ids]
        elif geometry["type"] == "extend_terminal":
            stroke = next((s for s in glyph["strokes"] if s["stroke_id"] == stroke_id), None)
            if stroke is None:
                raise ValueError(f"Feature {feature_id!r} refers to missing stroke {stroke_id!r}")
            points = {point["id"]: point for point in stroke["points"]}
            anchor = points.get(geometry["anchor_point_id"])
            endpoint = points.get(geometry["endpoint_point_id"])
            if anchor is None or endpoint is None:
                raise ValueError(f"Feature {feature_id!r} refers to missing terminal points")
            delta = geometry["present_endpoint_delta"]
            endpoint["x"] = round(float(anchor["x"]) + _uniform(rng, delta["x"]), 3)
            endpoint["y"] = round(float(anchor["y"]) + _uniform(rng, delta["y"]), 3)
        else:
            raise ValueError(f"Unsupported geometry type {geometry['type']!r} for feature {feature_id!r}")
        selected[feature_id] = state
    return selected


def sample_glyph(
    glyph: dict[str, Any],
    seed: str | int,
    occurrence: int = 0,
    style_id: str | None = None,
    head_mode: str | None = None,
    features: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return a deterministic variation of a parsed glyph JSON object."""
    sampled = copy.deepcopy(glyph)
    metadata = sampled.get("seed_variants")
    if not metadata or metadata.get("schema_version") != 1:
        raise ValueError(f"{sampled.get('codepoint', 'glyph')} has no seed_variants schema v1")

    rng = _rng(seed, sampled["codepoint"], occurrence)
    if style_id is None:
        profile = _weighted_choice(rng, metadata["styles"])
    else:
        profiles = [item for item in metadata["styles"] if item["id"] == style_id]
        if not profiles:
            raise ValueError(f"Unsupported style {style_id!r} for {sampled['codepoint']}")
        profile = profiles[0]
    _transform(sampled, rng, profile)
    # Head habit belongs to the writer/seed, rather than each individual glyph.
    # This keeps a person's use of looped vs. headless forms consistent across text.
    person_head_mode = head_mode if head_mode is not None else choose_person_head_mode(seed)
    chosen_head_mode = _apply_head_mode(sampled, rng, metadata, person_head_mode)
    chosen_features = _apply_optional_components(sampled, rng, features)

    sampled["metrics"]["sampled_stroke_width"] = round(rng.uniform(3.0, 5.0), 2)
    sampled["sampling"] = {
        "algorithm": "thai-handwriting-seed-v2",
        "seed": str(seed),
        "occurrence": occurrence,
        "style": profile["id"],
        "head_mode": chosen_head_mode,
        "features": chosen_features,
        "reproducible": True,
    }
    return sampled


def sample_sequence(text: str, seed: str | int) -> list[dict[str, Any]]:
    """Sample every supported character; repeated characters get distinct but reproducible forms."""
    seen: dict[str, int] = {}
    result: list[dict[str, Any]] = []
    for character in text:
        if character.isspace():
            continue
        codepoint = f"U+{ord(character):04X}"
        matches = list(SKELETON_ROOT.glob(f"*/{codepoint}.json"))
        if not matches:
            continue
        occurrence = seen.get(codepoint, 0)
        seen[codepoint] = occurrence + 1
        glyph = json.loads(matches[0].read_text(encoding="utf-8"))
        result.append(sample_glyph(glyph, seed, occurrence))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Sample a Thai handwriting skeleton reproducibly from a seed.")
    parser.add_argument("--char", required=True, help="One character, for example ง")
    parser.add_argument("--seed", required=True, help="Integer or text seed; the same seed gives the same result")
    parser.add_argument("--occurrence", type=int, default=0, help="Occurrence index for repeated characters (default: 0)")
    parser.add_argument(
        "--head-mode", choices=("looped", "headless"),
        help="Force a closed-loop head or a form with the complete head removed",
    )
    parser.add_argument("--output", type=Path, help="Write JSON to this file instead of stdout")
    parser.add_argument(
        "--feature", action="append", default=[], metavar="ID=STATE",
        help="Force an optional feature state, for example beak=present or beak=absent; may be repeated",
    )
    args = parser.parse_args()
    if len(args.char) != 1:
        parser.error("--char must contain exactly one Unicode codepoint")
    codepoint = f"U+{ord(args.char):04X}"
    matches = list(SKELETON_ROOT.glob(f"*/{codepoint}.json"))
    if not matches:
        parser.error(f"No skeleton found for {args.char!r} ({codepoint})")
    glyph = json.loads(matches[0].read_text(encoding="utf-8"))
    features: dict[str, str] = {}
    for assignment in args.feature:
        if "=" not in assignment:
            parser.error("--feature must use ID=STATE syntax")
        feature_id, state = assignment.split("=", 1)
        if not feature_id or feature_id in features:
            parser.error(f"Invalid or repeated feature assignment: {assignment!r}")
        features[feature_id] = state
    try:
        result = sample_glyph(
            glyph, args.seed, args.occurrence, head_mode=args.head_mode, features=features
        )
    except ValueError as exc:
        parser.error(str(exc))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
