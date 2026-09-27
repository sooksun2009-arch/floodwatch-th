#!/usr/bin/env bash
# One-shot Railway deploy for FloodWatch TH.
#
# Prerequisites:
#   1. railway login              (already done for sooksun2009@gmail.com)
#   2. an active Railway plan     (the trial does not allow new projects)
#
# Safe to re-run: it reuses the project if it already exists and only sets
# variables that are missing, so it never overwrites a secret you changed by
# hand in the dashboard.
set -euo pipefail

PROJECT_NAME="${PROJECT_NAME:-floodwatch-th}"
SECRETS_FILE="${SECRETS_FILE:-.deploy-secrets.txt}"

cd "$(dirname "$0")"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }

# ---------------------------------------------------------------- secrets
if [[ ! -f "$SECRETS_FILE" ]]; then
  say "สร้างคีย์ลับใหม่ ($SECRETS_FILE)"
  python - <<'PY' > "$SECRETS_FILE"
import secrets, string
print("JWT_SECRET=" + secrets.token_hex(32))
alphabet = string.ascii_letters + string.digits
print("ADMIN_PASSWORD=" + "".join(secrets.choice(alphabet) for _ in range(20)))
PY
fi
# shellcheck disable=SC1090
source "$SECRETS_FILE"

# ---------------------------------------------------------------- project
if railway status >/dev/null 2>&1; then
  say "ใช้โปรเจกต์ที่ link ไว้แล้ว"
else
  say "สร้างโปรเจกต์ $PROJECT_NAME"
  railway init --name "$PROJECT_NAME"
fi

# ---------------------------------------------------------------- database
say "เพิ่ม PostgreSQL (ข้ามถ้ามีอยู่แล้ว)"
railway add --database postgres || echo "  (มี Postgres อยู่แล้ว หรือเพิ่มไม่สำเร็จ — ตรวจใน dashboard)"

# ---------------------------------------------------------------- variables
# DATABASE_URL and PORT are injected by Railway; everything else is ours.
say "ตั้งค่า environment variables"
railway variables \
  --set "JWT_SECRET=$JWT_SECRET" \
  --set "SEED_ADMIN_USERNAME=admin" \
  --set "SEED_ADMIN_PASSWORD=$ADMIN_PASSWORD" \
  --set "SEED_DEMO_DATA=false" \
  --set "REQUIRE_MODERATION=true" \
  --set "ALLOW_ANONYMOUS_REPORTS=true" \
  --set "UPLOAD_DIR=/data/uploads" \
  --set "SYNC_STATIONS_ON_START=true" \
  --set "SYNC_BMA_ON_START=true" \
  --set "GEOCODE_ENABLED=true" \
  --set "HTTP_USER_AGENT=FloodWatchTH/1.0 (flood alert app; https://$PROJECT_NAME.up.railway.app)" \
  --skip-deploys

say "deploy"
railway up --detach

cat <<EOF

--------------------------------------------------------------------
เสร็จแล้ว ขั้นตอนที่เหลือต้องทำในหน้า Railway:

 1. ผูก Volume ที่ path /data ให้ service  (เก็บรูปที่ผู้ใช้อัปโหลด
    ถ้าไม่ผูก รูปจะหายทุกครั้งที่ deploy ใหม่)

 2. Generate Domain เพื่อให้ได้ URL สาธารณะ

 3. ตั้ง cron ยิง POST /api/stations/sync ทุก ~15 นาที
    เพื่อให้ระดับน้ำสดตลอด (ตอนบูตซิงก์ให้รอบเดียว)

 4. ถ้า domain ไม่ตรงกับ $PROJECT_NAME.up.railway.app
    ให้แก้ HTTP_USER_AGENT ให้ชี้ URL จริง — Nominatim ปฏิเสธคำขอ
    ที่ไม่ระบุผู้ดูแลที่ติดต่อได้

บัญชีผู้ดูแล: admin / $ADMIN_PASSWORD
(เก็บไว้ให้ดี ไฟล์ $SECRETS_FILE อยู่ใน .gitignore แล้ว)
--------------------------------------------------------------------
EOF
