"""The assistant in English.

The check that matters most here is not that English comes out. It is that
"bang na" never again resolves to จังหวัดพังงา — which it did, scoring 0.7 on
letter similarity against a province 700 km away, and then answering with
complete confidence that there was no flooding there. On a map whose purpose
is telling people whether to drive into water, a confident answer about the
wrong province is the worst failure this code can produce, worse than no
answer and worse than an answer in the wrong language.

The rest: English questions reach the four translated intents, Thai is
untouched, and an intent with no English wording says so instead of silently
replying in Thai.
"""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/chat.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"  # no network in tests

from fastapi.testclient import TestClient

from app import chatbot, chatbot_en
from app.main import app

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


def thai(text):
    return any("฀" <= ch <= "๿" for ch in text or "")


BKK = {"lat": 13.68, "lng": 100.61}

with TestClient(app) as c:
    def ask(message, lang="en", **kw):
        return c.post("/api/chat", json={"message": message, "lang": lang, **kw}).json()

    # ------------------------------------------------------- the dangerous one
    place = chatbot_en.to_thai_place("is bang na flooded")
    check("\"bang na\" -> บางนา ไม่ใช่พังงา", place == "บางนา", place)

    answer = ask("is bang na flooded")
    check("ถามชื่อโรมัน -> จับพื้นที่ถูก",
          answer.get("matched_place") == "บางนา", answer.get("matched_place"))
    check("และไม่ไปโผล่จังหวัดอื่น",
          "พังงา" not in (answer.get("answer") or ""), answer.get("answer", "")[:120])

    # A name in neither the gazetteer nor the alias list must come back as
    # "I do not know where you mean", never as the nearest-sounding province.
    stray = ask("is zzzqqq flooded")
    check("ชื่อที่ไม่มีจริง -> ไม่เดาเป็นจังหวัดใกล้เคียง",
          stray.get("intent") in ("fallback", "worst_areas"), stray.get("intent"))

    # ------------------------------------------------------- English answers
    for question, intent in [
        ("is it flooded near me", "flood_near_me"),
        ("where is it worst right now", "worst_areas"),
        ("cameras near me", "cameras"),
        ("is sukhumvit flooded", "flood_at_place"),
    ]:
        got = ask(question, **BKK)
        check(f"ถาม \"{question[:26]}\" -> {intent}", got.get("intent") == intent, got.get("intent"))
        body = got.get("answer") or ""
        # Report text and place names stay Thai on purpose, so the test looks
        # for English sentence structure rather than the absence of Thai.
        check(f"  และตอบเป็นอังกฤษ",
              any(w in body for w in ("flood", "camera", "confirmed", "no ", "Within", "Tap")),
              body[:150])

    # ------------------------------------------------------- Thai unchanged
    th = c.post("/api/chat", json={"message": "น้ำท่วมบางนาไหม", **BKK}).json()
    check("ถามไทย -> ยังตอบไทยเหมือนเดิม", thai(th.get("answer")), (th.get("answer") or "")[:90])
    check("และไม่มีหมายเหตุภาษาอังกฤษปนมา",
          "only answered in Thai" not in (th.get("answer") or ""), th.get("answer", "")[:120])

    # ------------------------------------------------------- honest about gaps
    gap = ask("how do I report flooding")
    check("คำถามที่ยังไม่ได้แปล -> ตอบไทย",
          thai(gap.get("answer")), (gap.get("answer") or "")[:80])
    check("แต่บอกตรง ๆ ว่ายังไม่รองรับภาษาอังกฤษ",
          "only answered in Thai" in (gap.get("answer") or ""),
          (gap.get("answer") or "")[-120:])

    # ------------------------------------------------------- inches
    near = ask("is it flooded near me", **BKK)
    body = near.get("answer") or ""
    if "Measured" in body:
        check("ความลึกมีหน่วยนิ้วกำกับให้คนอ่านอังกฤษ", "in)" in body,
              body[body.index("Measured"):][:60])

    # ------------------------------------------------------- the switch
    check("ไม่ส่ง lang มา -> ถือว่าเป็นไทย",
          thai(c.post("/api/chat", json={"message": "ท่วมที่ไหนบ้าง"}).json().get("answer")))

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL ENGLISH ASSISTANT CHECKS PASSED")
sys.exit(1 if fails else 0)
