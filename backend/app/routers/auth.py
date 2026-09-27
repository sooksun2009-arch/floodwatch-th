from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, enforce_limit, get_current_user
from ..models import Role, User
from ..schemas import LoginIn, RegisterIn, TokenOut, UserOut, UserUpdateIn
from ..security import create_access_token, hash_password, verify_password
from ..services import log_action

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    enforce_limit(f"register:{client_ip(request)}", 5)

    exists = db.execute(
        select(User).where(func.lower(User.username) == payload.username.lower())
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "ชื่อผู้ใช้นี้ถูกใช้แล้ว")
    if payload.email:
        email_taken = db.execute(
            select(User).where(func.lower(User.email) == payload.email.lower())
        ).scalar_one_or_none()
        if email_taken:
            raise HTTPException(status.HTTP_409_CONFLICT, "อีเมลนี้ถูกใช้แล้ว")

    user = User(
        username=payload.username,
        email=payload.email,
        display_name=payload.display_name or payload.username,
        phone=payload.phone,
        hashed_password=hash_password(payload.password),
        role=Role.user.value,
    )
    db.add(user)
    log_action(db, user, "register", "user", user.id)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_access_token(user.id, user.role),
                    user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    # Throttle per IP and per attempted username so neither a single host nor a
    # distributed attempt on one account can brute-force freely.
    ip = client_ip(request)
    enforce_limit(f"login:ip:{ip}", 30, window_sec=900)
    enforce_limit(f"login:user:{payload.username.lower()}", 10, window_sec=900)

    user = db.execute(
        select(User).where(func.lower(User.username) == payload.username.lower())
    ).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "บัญชีนี้ถูกระงับการใช้งาน")

    return TokenOut(access_token=create_access_token(user.id, user.role),
                    user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
def update_me(payload: UserUpdateIn, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)

    if "email" in data and data["email"]:
        taken = db.execute(
            select(User).where(func.lower(User.email) == data["email"].lower(), User.id != user.id)
        ).scalar_one_or_none()
        if taken:
            raise HTTPException(status.HTTP_409_CONFLICT, "อีเมลนี้ถูกใช้แล้ว")

    for key, value in data.items():
        setattr(user, key, value)
    if password:
        user.hashed_password = hash_password(password)

    log_action(db, user, "update_profile", "user", user.id)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)
