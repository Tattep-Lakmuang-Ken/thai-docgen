#!/usr/bin/env python3
"""Generate reproducible, fictional Thai profile data for handwriting samples."""

from __future__ import annotations

import argparse
import json
import random
import secrets
from pathlib import Path
from typing import Any


FEMALE_NAMES = (
    "กานดา", "ณิชา", "พิมพ์ชนก", "นภัสสร", "เมธาวี", "อรอุมา",
    "ธัญญา", "สิริน", "วรัญญา", "พรทิพย์", "ลลิตา", "ชลธิชา",
)
MALE_NAMES = (
    "ธนกร", "ภูวดล", "ศุภชัย", "กิตติพงษ์", "ปกรณ์", "วรเมธ",
    "ชนาธิป", "ปริญญา", "ภาคิน", "ณัฐพงศ์", "ธีรภัทร", "รณกร",
)
SURNAMES = (
    "แสงทอง", "พูนสุข", "รุ่งเรือง", "มีศรี", "ชื่นจิต", "เกษมสุข",
    "มั่นคง", "ใจงาม", "วัฒนชัย", "สายชล", "พิพัฒน์", "ประเสริฐ",
    "มณีรัตน์", "ธนากุล", "นวลจันทร์", "มงคลชัย", "ศรีสวัสดิ์", "ทองดี",
)

# Each entry is a plausible administrative area. House numbers, village
# numbers, and street combinations are generated, so the complete address is
# synthetic and should only be used as sample data.
AREAS = (
    {"subdistrict": "แขวงจตุจักร", "district": "เขตจตุจักร", "province": "กรุงเทพมหานคร", "urban": True},
    {"subdistrict": "ตำบลสุเทพ", "district": "อำเภอเมืองเชียงใหม่", "province": "เชียงใหม่"},
    {"subdistrict": "ตำบลเวียง", "district": "อำเภอเมืองเชียงราย", "province": "เชียงราย"},
    {"subdistrict": "ตำบลในเมือง", "district": "อำเภอเมืองขอนแก่น", "province": "ขอนแก่น"},
    {"subdistrict": "ตำบลในเมือง", "district": "อำเภอเมืองนครราชสีมา", "province": "นครราชสีมา"},
    {"subdistrict": "ตำบลบางปลาสร้อย", "district": "อำเภอเมืองชลบุรี", "province": "ชลบุรี"},
    {"subdistrict": "ตำบลตลาดใหญ่", "district": "อำเภอเมืองภูเก็ต", "province": "ภูเก็ต"},
    {"subdistrict": "ตำบลบ่อยาง", "district": "อำเภอเมืองสงขลา", "province": "สงขลา"},
    {"subdistrict": "ตำบลบางตลาด", "district": "อำเภอปากเกร็ด", "province": "นนทบุรี"},
    {"subdistrict": "ตำบลคลองหนึ่ง", "district": "อำเภอคลองหลวง", "province": "ปทุมธานี"},
    {"subdistrict": "ตำบลปากน้ำ", "district": "อำเภอเมืองสมุทรปราการ", "province": "สมุทรปราการ"},
    {"subdistrict": "ตำบลในเมือง", "district": "อำเภอเมืองพิษณุโลก", "province": "พิษณุโลก"},
)
SOI_NAMES = ("สายลม", "ดอกแก้ว", "ร่มเย็น", "สวนสุข", "แสงทอง", "พูนทรัพย์", "ใจดี", "ดาวเรือง")
ROAD_NAMES = ("สุขใจ", "ประชาร่วม", "ร่มโพธิ์", "พัฒนาสุข", "สายชล", "รุ่งเรือง", "ดอกไม้", "คลองสวย")
VILLAGE_NAMES = ("บ้านร่มเย็น", "บ้านสายลม", "บ้านดอกแก้ว", "บ้านสวนสุข", "บ้านแสงทอง", "บ้านพูนทรัพย์")
OCCUPATIONS = (
    ("ครู", 18_000, 50_000),
    ("พนักงานบัญชี", 15_000, 42_000),
    ("ช่างไฟฟ้า", 16_000, 48_000),
    ("พนักงานขาย", 12_000, 48_000),
    ("นักออกแบบกราฟิก", 18_000, 65_000),
    ("เกษตรกร", 10_000, 60_000),
    ("เจ้าหน้าที่ธุรการ", 14_000, 36_000),
    ("ช่างยนต์", 15_000, 48_000),
    ("พนักงานร้านอาหาร", 10_000, 32_000),
    ("โปรแกรมเมอร์", 25_000, 100_000),
    ("ผู้ช่วยพยาบาล", 16_000, 45_000),
    ("คนขับรถ", 13_000, 45_000),
    ("ผู้จัดการร้าน", 20_000, 65_000),
    ("ช่างภาพ", 16_000, 72_000),
    ("พนักงานธนาคาร", 18_000, 62_000),
    ("ผู้ประกอบการ", 20_000, 100_000),
    ("พนักงานคลังสินค้า", 13_000, 38_000),
)
THAI_DIGITS = str.maketrans("0123456789", "๐๑๒๓๔๕๖๗๘๙")


def thai_digits(value: int) -> str:
    """Format an integer without separators using Thai numerals."""
    return str(value).translate(THAI_DIGITS)


def make_address(rng: random.Random) -> str:
    area = rng.choice(AREAS)
    house_number = thai_digits(rng.randint(1, 299))
    soi = rng.choice(SOI_NAMES)
    road = rng.choice(ROAD_NAMES)
    if area.get("urban"):
        return f"เลขที่ {house_number} ซอย{soi} ถนน{road} {area['subdistrict']} {area['district']} {area['province']}"

    village_number = thai_digits(rng.randint(1, 12))
    village = rng.choice(VILLAGE_NAMES)
    return (
        f"เลขที่ {house_number} หมู่ {village_number} {village} ซอย{soi} ถนน{road} "
        f"{area['subdistrict']} {area['district']} จังหวัด{area['province']}"
    )


def generate_profile(rng: random.Random, index: int) -> dict[str, Any]:
    is_female = bool(rng.getrandbits(1))
    title = "นางสาว" if is_female else "นาย"
    first_name = rng.choice(FEMALE_NAMES if is_female else MALE_NAMES)
    last_name = rng.choice(SURNAMES)
    occupation, min_income, max_income = rng.choice(OCCUPATIONS)
    income = rng.randrange(min_income, max_income + 1, 1_000)

    return {
        "profile_id": f"synthetic-{index:03d}",
        "synthetic": True,
        "title": title,
        "first_name": first_name,
        "last_name": last_name,
        "full_name": f"{title} {first_name} {last_name}",
        "address": make_address(rng),
        "occupation": occupation,
        "monthly_income": f"{thai_digits(income)} บาทต่อเดือน",
        "monthly_income_thb": income,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="สร้างข้อมูลบุคคลสมมติภาษาไทยสำหรับตัวอย่างลายมือ",
    )
    parser.add_argument("--count", type=int, default=1, help="จำนวนชุดข้อมูล (ค่าเริ่มต้น: 1)")
    parser.add_argument("--seed", help="seed สำหรับสร้างชุดเดิมซ้ำ; ถ้าไม่ระบุจะสุ่ม seed ใหม่")
    parser.add_argument("--output", type=Path, help="ไฟล์ JSON ปลายทาง; ถ้าไม่ระบุจะแสดง JSON ที่ terminal")
    parser.add_argument(
        "--field",
        choices=("full_name", "address", "occupation", "monthly_income"),
        help="แสดงค่าฟิลด์เดียวเพื่อส่งต่อให้ write_thai.py (ใช้ได้เมื่อ --count 1)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count ต้องมีค่าอย่างน้อย 1")
    if args.field and args.count != 1:
        parser.error("เมื่อใช้ --field ให้กำหนด --count 1")
    if args.field and args.output:
        parser.error("--field แสดงข้อความทาง terminal; ไม่ใช้ร่วมกับ --output")

    seed = args.seed if args.seed is not None else secrets.token_hex(8)
    rng = random.Random(seed)
    profiles = [generate_profile(rng, index + 1) for index in range(args.count)]

    if args.field:
        print(profiles[0][args.field])
        return 0

    payload = {
        "schema_version": 1,
        "synthetic": True,
        "synthetic_notice_th": "ข้อมูลสมมติสำหรับทดสอบ ไม่ใช่ข้อมูลบุคคลจริง",
        "seed": str(seed),
        "profiles": profiles,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"บันทึกข้อมูลสมมติแล้ว: {args.output.resolve()}")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
