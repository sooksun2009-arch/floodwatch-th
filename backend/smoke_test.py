"""End-to-end smoke test against an in-process SQLite database."""
import os, sys, tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/test.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["GEOCODE_ENABLED"] = "false"
# Off here so the end-to-end path stays exercised as it was; the gate has
# its own suite.
os.environ["REQUIRE_PHOTO"] = "false"

from fastapi.testclient import TestClient
from app.main import app

fails = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"  -> {extra}"))
    if not cond:
        fails.append(name)

with TestClient(app) as c:
    r = c.get("/api/health"); check("health", r.status_code == 200, r.text)

    r = c.get("/api/areas/provinces")
    check("77 provinces seeded", r.status_code == 200 and len(r.json()) == 77,
          f"{r.status_code} n={len(r.json()) if r.status_code==200 else '?'}")

    r = c.get("/api/areas/districts")
    check("50 Bangkok districts seeded", r.status_code == 200 and len(r.json()) == 50,
          f"n={len(r.json()) if r.status_code==200 else '?'}")

    r = c.get("/api/reports")
    check("demo reports approved", r.status_code == 200 and r.json()["total"] == 4, r.text[:200])
    first = r.json()["items"][0]
    check("report has level label", bool(first.get("level_label")), str(first)[:200])
    check("report has confidence", first.get("confidence") is not None, str(first)[:200])

    r = c.get("/api/cameras")
    check("demo cameras seeded", r.status_code == 200 and len(r.json()) == 8,
          f"n={len(r.json()) if r.status_code==200 else '?'}")

    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    check("admin login", r.status_code == 200, r.text[:200])
    token = r.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    r = c.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    check("bad password rejected", r.status_code == 401, r.text[:120])

    r = c.post("/api/auth/register", json={"username": "somchai", "password": "secret1234",
                                           "display_name": "สมชาย"})
    check("register", r.status_code == 201, r.text[:200])
    user_auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # anonymous report -> pending
    r = c.post("/api/reports", json={"lat": 13.7460, "lng": 100.5340, "level": "deep",
                                     "depth_cm": 40, "place": "ถนนเพชรบุรี ซอย 5",
                                     "reporter_name": "คนแจ้ง"})
    check("anon report created", r.status_code == 201, r.text[:250])
    rep = r.json()
    check("anon report pending", rep["status"] == "pending", rep.get("status"))
    check("province auto-resolved", rep["province_name"] == "กรุงเทพมหานคร", str(rep.get("province_name")))
    rid = rep["id"]

    r = c.get("/api/reports")
    check("pending hidden from public map", all(i["id"] != rid for i in r.json()["items"]))

    # out of country rejected
    r = c.post("/api/reports", json={"lat": 48.85, "lng": 2.35, "level": "deep"})
    check("out-of-country rejected", r.status_code == 400, r.text[:150])

    # missing level and depth rejected
    r = c.post("/api/reports", json={"lat": 13.75, "lng": 100.53})
    check("level/depth required", r.status_code == 400, r.text[:150])

    # moderation queue
    r = c.get("/api/admin/queue", headers=auth)
    check("queue shows pending", r.status_code == 200 and r.json()["total"] >= 1, r.text[:200])
    r = c.get("/api/admin/queue")
    check("queue needs auth", r.status_code == 401, r.text[:120])

    r = c.post(f"/api/admin/reports/{rid}/moderate", headers=auth,
               json={"status": "approved", "note": "ตรวจจากภาพถ่ายแล้ว"})
    check("approve report", r.status_code == 200 and r.json()["status"] == "approved", r.text[:200])

    # voting
    r = c.post(f"/api/reports/{rid}/vote", headers=user_auth, json={"vote": "confirm"})
    check("confirm vote", r.status_code == 200 and r.json()["confirm_count"] == 1, r.text[:200])
    r = c.post(f"/api/reports/{rid}/vote", headers=user_auth, json={"vote": "dispute"})
    check("vote change is idempotent per user",
          r.status_code == 200 and r.json()["confirm_count"] == 0 and r.json()["dispute_count"] == 1,
          r.text[:200])

    # official report goes live immediately
    r = c.post("/api/reports", headers=auth, json={"lat": 13.7000, "lng": 100.6000,
                                                   "depth_cm": 75, "place": "ทดสอบเจ้าหน้าที่"})
    check("official report auto-approved", r.status_code == 201
          and r.json()["status"] == "approved" and r.json()["source"] == "official", r.text[:250])
    check("depth 75cm -> severe", r.json()["level"] == "severe", r.json().get("level"))

    # stats
    r = c.get("/api/stats/summary")
    check("summary", r.status_code == 200 and r.json()["active_reports"] >= 5, r.text[:250])
    r = c.get("/api/stats/by-province")
    check("by-province", r.status_code == 200 and len(r.json()) >= 1, r.text[:200])
    r = c.get("/api/stats/timeline?hours=12")
    check("timeline buckets", r.status_code == 200 and len(r.json()) == 13, str(len(r.json())))

    # cameras admin
    r = c.post("/api/cameras", headers=auth, json={
        "name": "กล้องทดสอบ ถนนพระราม 9", "lat": 13.7580, "lng": 100.5650,
        "stream_type": "snapshot", "stream_url": "https://example.com/cam.jpg",
        "owner_org": "ทดสอบ"})
    check("create camera", r.status_code == 201, r.text[:250])
    cam_id = r.json()["id"]
    r = c.post("/api/cameras", headers=user_auth, json={
        "name": "ไม่ควรสร้างได้", "lat": 13.75, "lng": 100.5, "stream_url": "https://x.com/a.jpg"})
    check("normal user cannot add camera", r.status_code == 403, r.text[:150])
    r = c.post("/api/cameras", headers=auth, json={
        "name": "bad url", "lat": 13.75, "lng": 100.5, "stream_url": "ftp://x/a.jpg"})
    check("non-http stream url rejected", r.status_code == 422, r.text[:150])

    r = c.get("/api/cameras?near=13.7655,100.6420,5")
    body = r.json()
    check("cameras near returns distance", r.status_code == 200 and body
          and body[0]["distance_km"] is not None, str(body)[:250])
    check("cameras near sorted", r.status_code == 200
          and body == sorted(body, key=lambda x: x["distance_km"]))

    r = c.delete(f"/api/cameras/{cam_id}", headers=auth)
    check("delete camera", r.status_code == 204, r.text[:150])

print()
print("=" * 60)
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    sys.exit(1)
print("ALL CORE API CHECKS PASSED")
