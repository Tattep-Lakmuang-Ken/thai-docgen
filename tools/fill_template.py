#!/usr/bin/env python3
"""Fill a UTF-8 text template with fields from generated profile JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}")


def load_profile(path: Path, index: int) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "profiles" in data:
        profiles = data["profiles"]
        if not isinstance(profiles, list):
            raise ValueError("ฟิลด์ profiles ใน JSON ต้องเป็นรายการ")
        if index < 0 or index >= len(profiles):
            raise ValueError(f"ไม่มี profile ลำดับ {index}; มีทั้งหมด {len(profiles)} ชุด")
        profile = profiles[index]
    elif isinstance(data, list):
        if index < 0 or index >= len(data):
            raise ValueError(f"ไม่มี profile ลำดับ {index}; มีทั้งหมด {len(data)} ชุด")
        profile = data[index]
    else:
        if index != 0:
            raise ValueError("ไฟล์ JSON มี profile เดียว จึงใช้ได้เฉพาะ --index 0")
        profile = data
    if not isinstance(profile, dict):
        raise ValueError("ข้อมูล profile ต้องเป็น JSON object")
    return profile


def render_template(template: str, profile: dict[str, Any]) -> str:
    """Replace {{field_name}} markers; raise a clear error for unknown fields."""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in profile:
            available = ", ".join(sorted(profile))
            raise ValueError(f"ไม่พบฟิลด์ {key!r} ในข้อมูล; ฟิลด์ที่มี: {available}")
        value = profile[key]
        if isinstance(value, (dict, list)):
            raise ValueError(f"ฟิลด์ {key!r} ต้องเป็นข้อความหรือตัวเลข ไม่ใช่ object/list")
        return "" if value is None else str(value)

    return PLACEHOLDER.sub(replace, template)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="เติม placeholder ใน template ข้อความด้วยข้อมูลจาก generate_profiles.py",
    )
    parser.add_argument("--template", required=True, type=Path, help="ไฟล์ template UTF-8 ที่มี {{field_name}}")
    parser.add_argument("--data", required=True, type=Path, help="ไฟล์ JSON ที่สร้างจาก generate_profiles.py")
    parser.add_argument("--index", type=int, default=0, help="ลำดับ profile เริ่มจาก 0 (ค่าเริ่มต้น: 0)")
    parser.add_argument("--output", type=Path, help="ไฟล์ข้อความปลายทาง; ถ้าไม่ระบุจะแสดงผลที่ terminal")
    args = parser.parse_args()

    try:
        profile = load_profile(args.data, args.index)
        template = args.template.read_text(encoding="utf-8")
        result = render_template(template, profile)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ผิดพลาด: {exc}", file=sys.stderr)
        return 2

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding="utf-8")
        print(f"เติมข้อมูลลง template แล้ว: {args.output.resolve()}")
    else:
        print(result, end="" if result.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
