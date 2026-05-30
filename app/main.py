import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from .database import Base, engine, get_db
from .models import Setting, Category
from .auth import get_current_user
from .models import User
from .routes import users, markers, categories, activity, public

os.makedirs("/data/uploads", exist_ok=True)
Base.metadata.create_all(bind=engine)

# Add columns that create_all won't add to existing tables
with engine.connect() as _conn:
    for _stmt in [
        "ALTER TABLE markers ADD COLUMN filled_at DATETIME",
        "ALTER TABLE markers ADD COLUMN filled_by_id INTEGER",
        "ALTER TABLE users ADD COLUMN name VARCHAR",
        "ALTER TABLE users ADD COLUMN notify_email INTEGER DEFAULT 0",
        "ALTER TABLE markers ADD COLUMN address VARCHAR",
        "ALTER TABLE markers ADD COLUMN updated_at DATETIME",
        "ALTER TABLE photos ADD COLUMN tag VARCHAR",
        "ALTER TABLE markers ADD COLUMN category_id INTEGER",
    ]:
        try:
            _conn.execute(text(_stmt))
            _conn.commit()
        except Exception:
            pass  # column already exists

# Seed default settings + categories
def seed():
    from .database import SessionLocal
    db = SessionLocal()
    try:
        if not db.get(Setting, "road_name"):
            db.add(Setting(key="road_name", value="er väg"))
        if db.query(Category).count() == 0:
            defaults = [
                ("Grop", "🕳️", "#ef4444", 0),
                ("Fallet träd", "🌳", "#16a34a", 1),
                ("Översvämning", "💧", "#3b82f6", 2),
                ("Skadat skylt", "🪧", "#f59e0b", 3),
                ("Annat", "❓", "#94a3b8", 4),
            ]
            for name, icon, color, order in defaults:
                db.add(Category(name=name, icon=icon, color=color, sort_order=order))
        db.commit()
    finally:
        db.close()

seed()

app = FastAPI(title="Grop")

app.include_router(users.router)
app.include_router(markers.router)
app.include_router(categories.router)
app.include_router(activity.router)
app.include_router(public.router)


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


@app.get("/public")
def public_root():
    return FileResponse("/app/static/index.html")


@app.get("/reset")
def reset_root():
    return FileResponse("/app/static/index.html")


@app.get("/sw.js")
def service_worker():
    return FileResponse("/app/static/sw.js", media_type="application/javascript")
