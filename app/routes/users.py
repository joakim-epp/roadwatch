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


@router.post("/register")
def register(body: RegisterBody, db: Session = Depends(get_db)):
    existing = db.query(User).filter(
        (User.username == body.username) | (User.email == body.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already taken")
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": create_token(user.id), "username": user.username, "is_admin": user.is_admin}


@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"token": create_token(user.id), "username": user.username, "is_admin": user.is_admin}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "email": user.email, "is_admin": user.is_admin}
