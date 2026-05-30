import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User, PasswordReset
from ..auth import hash_password, verify_password, create_token, get_current_user
from ..resend_email import send_password_reset

RESET_TTL_HOURS = 1

router = APIRouter(prefix="/api/users", tags=["users"])


class RegisterBody(BaseModel):
    username: str
    name: str = ""
    email: EmailStr
    password: str


class LoginBody(BaseModel):
    username: str
    password: str


def user_dict(user: User) -> dict:
    return {"id": user.id, "username": user.username, "name": user.name or user.username, "email": user.email, "is_admin": user.is_admin, "is_approved": user.is_approved, "notify_email": user.notify_email or 0}


@router.post("/register")
def register(body: RegisterBody, db: Session = Depends(get_db)):
    existing = db.query(User).filter(
        (User.username == body.username) | (User.email == body.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already taken")

    is_first = db.query(User).count() == 0
    user = User(
        username=body.username,
        name=body.name.strip() or None,
        email=body.email,
        password_hash=hash_password(body.password),
        is_admin=1 if is_first else 0,
        is_approved=1 if is_first else 0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    if is_first:
        return {"token": create_token(user.id), "username": user.username, "name": user.name or user.username, "is_admin": user.is_admin, "notify_email": user.notify_email or 0}
    return {"pending": True, "message": "Konto skapat — väntar på administratörens godkännande."}


@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.is_approved:
        raise HTTPException(status_code=403, detail="Your account is awaiting admin approval.")
    return {"token": create_token(user.id), "username": user.username, "name": user.name or user.username, "is_admin": user.is_admin, "notify_email": user.notify_email or 0}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_dict(user)


@router.get("/approved")
def approved_users(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    return [user_dict(u) for u in db.query(User).filter(User.is_approved == 1).order_by(User.created_at).all()]


class UpdateProfileBody(BaseModel):
    name: Optional[str] = None
    notify_email: Optional[int] = None
    old_password: Optional[str] = None
    new_password: Optional[str] = None

@router.patch("/me")
def update_me(body: UpdateProfileBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.name is not None:
        user.name = body.name.strip() or None
    if body.notify_email is not None:
        user.notify_email = body.notify_email
    if body.new_password:
        if not body.old_password:
            raise HTTPException(status_code=400, detail="Ange nuvarande lösenord")
        if not verify_password(body.old_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Felaktigt nuvarande lösenord")
        user.password_hash = hash_password(body.new_password)
    db.commit()
    db.refresh(user)
    return {"username": user.username, "name": user.name or user.username, "is_admin": user.is_admin, "notify_email": user.notify_email or 0}


class UpdateUserBody(BaseModel):
    name: str


@router.patch("/{user_id}")
def update_user(user_id: int, body: UpdateUserBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Användaren hittades inte")
    target.name = body.name.strip() or None
    db.commit()
    return user_dict(target)


@router.get("/pending")
def pending_users(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    return [user_dict(u) for u in db.query(User).filter(User.is_approved == 0).all()]


@router.post("/{user_id}/approve")
def approve_user(user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_approved = 1
    db.commit()
    return user_dict(target)


@router.delete("/{user_id}")
def delete_user(user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(target)
    db.commit()
    return {"ok": True}


# ── Password reset ────────────────────────────────────────────────────────

class ForgotBody(BaseModel):
    email: EmailStr


class ResetBody(BaseModel):
    token: str
    password: str


@router.post("/forgot-password")
def forgot_password(body: ForgotBody, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # Always return success — don't reveal whether the email exists.
    target = db.query(User).filter(User.email == body.email).first()
    if target and target.is_approved:
        token = secrets.token_urlsafe(32)
        pr = PasswordReset(
            user_id=target.id,
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=RESET_TTL_HOURS),
        )
        db.add(pr)
        db.commit()
        background_tasks.add_task(send_password_reset, target.email, target.name or target.username, token)
    return {"ok": True}


@router.post("/reset-password")
def reset_password(body: ResetBody, db: Session = Depends(get_db)):
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Lösenordet måste vara minst 6 tecken")
    pr = db.query(PasswordReset).filter(PasswordReset.token == body.token).first()
    now = datetime.now(timezone.utc)
    if not pr or pr.used_at is not None:
        raise HTTPException(status_code=400, detail="Ogiltig eller använd länk")
    # expires_at may be naive (SQLite stores without tz); treat as UTC
    expires = pr.expires_at if pr.expires_at.tzinfo else pr.expires_at.replace(tzinfo=timezone.utc)
    if expires < now:
        raise HTTPException(status_code=400, detail="Länken har gått ut")
    user = db.get(User, pr.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Användaren hittades inte")
    user.password_hash = hash_password(body.password)
    pr.used_at = now
    db.commit()
    return {"ok": True}
