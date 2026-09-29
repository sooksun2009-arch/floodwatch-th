"""Turning what someone typed into a point on the map.

Written after a user reported that "Central Rayong" took them somewhere else.
It did not send them to another province — it matched the word "Rayong",
returned the middle of Rayong province, and threw away the word that said
which building. From the far end those are the same thing: you asked for a
shopping centre and the map moved to a field.

So the rule these tests hold is not "find everything". It is that a partial
match is never dressed up as a whole one, and that a result nowhere near the
area someone named is thrown away rather than shown.
"""
import asyncio
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/geo.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"  # no network in tests

from fastapi.testclient import TestClient

from app import geocode
from app.database import SessionLocal
from app.geocode import _covers, _split_variants, resolve_place
from app.main import app

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


with TestClient(app):
    db = SessionLocal()

    def ask(q):
        return asyncio.run(resolve_place(db, q))

    # ------------------------------------------------- the reported bug
    whole = ask("ระยอง")
    part = ask("Central Rayong")
    check("ชื่อจังหวัดล้วน -> ได้จังหวัด ไม่มีป้ายกำกับ",
          whole and whole[3] == "local" and "จังหวัด)" not in whole[2], whole)
    check("พิมพ์มากกว่าชื่อจังหวัด -> ไม่ตอบเป็นจุดกึ่งกลางเฉย ๆ",
          part is None or part[3] != "local", part)
    check("ถ้าหาที่เจาะจงไม่ได้ -> บอกตรง ๆ ว่าได้ทั้งจังหวัด",
          part is None or "ทั้งจังหวัด" in part[2], part)

    # The two must not be presented as the same answer, which is what the user
    # actually hit: identical coordinates, identical label, no hint of it.
    if whole and part:
        check("คำถามสองแบบ -> คำตอบต้องไม่หน้าตาเหมือนกันทั้งที่คนละเรื่อง",
              whole[2] != part[2], (whole[2], part[2]))

    # ------------------------------------------------- how much was matched
    check("จับได้ทั้งคำถาม -> ถือว่าครบ", _covers("ระยอง", "ระยอง") >= 0.75)
    check("จับได้แค่ครึ่งเดียว -> ถือว่าไม่ครบ",
          _covers("rayong", "Central Rayong") < 0.75,
          _covers("rayong", "Central Rayong"))

    # ------------------------------------------------- Thai written unspaced
    # Thai has no spaces between words, so this is how people type it and how
    # every geocoder fails to find it.
    variants = _split_variants(db, "เซ็นทรัลระยอง")
    check("ชื่อไทยติดกัน -> แตกคำให้ก่อนไปถาม", "เซ็นทรัล ระยอง" in variants, variants)
    check("ชื่อที่มีเว้นวรรคอยู่แล้ว -> ไม่แตกซ้ำ",
          not _split_variants(db, "เซ็นทรัล ระยอง"), _split_variants(db, "เซ็นทรัล ระยอง"))

    # ------------------------------------------------- the far-away guard
    # A geocoder that answers a Rayong question with a Bangkok result is not
    # answering the question. Worse than no answer: it looks like one.
    rayong = ask("ระยอง")
    bangkok = (13.7563, 100.5018)
    check("ผลลัพธ์คนละภาค -> ถือว่าไม่ใช่สิ่งที่ถาม",
          not geocode._near(bangkok[0], bangkok[1], rayong[0], rayong[1]),
          geocode.AREA_RADIUS_KM)
    check("ผลลัพธ์ในจังหวัดเดียวกัน -> รับได้",
          geocode._near(rayong[0] + 0.2, rayong[1] + 0.2, rayong[0], rayong[1]))

    # ------------------------------------------------- unchanged behaviour
    check("ชื่อที่ไม่มีจริง -> ไม่เดา", ask("zzzz ไม่มีที่นี่ zzzz") is None)
    check("ช่องว่างล้วน -> ไม่พัง", ask("   ") is None)

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL GEOCODE CHECKS PASSED")
sys.exit(1 if fails else 0)
