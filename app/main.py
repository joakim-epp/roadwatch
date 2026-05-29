import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from .database import Base, engine, get_db
from .models import Setting
from .auth import get_current_user
from .models import User
from .routes import users, markers

os.makedirs("/data/uploads", exist_ok=True)
Base.metadata.create_all(bind=engine)

# Add columns that create_all won't add to existing tables
with engine.connect() as _conn:
    for _stmt in [
        "ALTER TABLE markers ADD COLUMN filled_at DATETIME",
        "ALTER TABLE markers ADD COLUMN filled_by_id INTEGER",
        "ALTER TABLE users ADD COLUMN name VARCHAR",
    ]:
        try:
            _conn.execute(text(_stmt))
            _conn.commit()
        except Exception:
            pass  # column already exists

# Seed default settings
def seed_settings():
    from .database import SessionLocal
    db = SessionLocal()
    try:
        if not db.get(Setting, "road_name"):
            db.add(Setting(key="road_name", value="er väg"))
            db.commit()
    finally:
        db.close()

seed_settings()

app = FastAPI(title="Grop")

app.include_router(users.router)
app.include_router(markers.router)


@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    rows = db.query(Setting).all()
    return {r.key: r.value for r in rows}


class SettingsUpdate(BaseModel):
    road_name: str


@app.patch("/api/settings")
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    setting = db.get(Setting, "road_name")
    setting.value = body.road_name
    db.commit()
    return {"road_name": setting.value}

app.mount("/uploads", StaticFiles(directory="/data/uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="/app/static"), name="static")


@app.get("/")
def root():
    return FileResponse("/app/static/index.html")
