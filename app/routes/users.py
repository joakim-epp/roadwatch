from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..auth import hash_password, verify_password, create_token, get_current_user

router = APIRouter(prefix="/api/users", tags=["users"])


class RegisterBody(BaseModel):
    username: str
    email: EmailStr
    password: str


class LoginBody(BaseModel):
    username: str
    password: str


def user_dict(user: User) -> dict:
    return {"id": user.id, "username": user.username, "email": user.email, "is_admin": user.is_admin, "is_approved": user.is_approved}


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
        email=body.email,
        password_hash=hash_password(body.password),
        is_admin=1 if is_first else 0,
        is_approved=1 if is_first else 0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    if is_first:
        return {"token": create_token(user.id), "username": user.username, "is_admin": user.is_admin}
    return {"pending": True, "message": "Account created — waiting for admin approval before you can log in."}


@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.is_approved:
        raise HTTPException(status_code=403, detail="Your account is awaiting admin approval.")
    return {"token": create_token(user.id), "username": user.username, "is_admin": user.is_admin}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_dict(user)


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
