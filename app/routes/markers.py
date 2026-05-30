import csv
import io
import os
import uuid
import aiofiles
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models import Marker, Photo, Comment, User, Category, Confirmation, MarkerEvent
from ..auth import get_current_user
from ..email import send_new_marker_email
from ..geo import geocode_marker

router = APIRouter(prefix="/api/markers", tags=["markers"])

UPLOAD_DIR = "/data/uploads"
VALID_SEVERITIES = {"low", "medium", "high"}
VALID_STATUSES = {"unfilled", "filled"}
SEVERITY_LABEL = {"high": "Hög", "medium": "Medel", "low": "Låg"}
STATUS_LABEL = {"unfilled": "Inte igenfylld", "filled": "Igenfylld"}
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def confirmation_count(db: Session, marker_id: int) -> int:
    return db.query(func.count(Confirmation.id)).filter(Confirmation.marker_id == marker_id).scalar() or 0


def user_has_confirmed(db: Session, marker_id: int, user_id: int) -> bool:
    return db.query(Confirmation.id).filter(Confirmation.marker_id == marker_id, Confirmation.user_id == user_id).first() is not None


def marker_dict(m: Marker, db: Optional[Session] = None, user: Optional[User] = None, include_user_names: bool = True) -> dict:
    created_by = (m.creator.name or m.creator.username) if include_user_names else None
    filled_by = ((m.filler.name or m.filler.username) if m.filler else None) if include_user_names else None
    return {
        "id": m.id,
        "lat": m.lat,
        "lng": m.lng,
        "title": m.title,
        "description": m.description,
        "severity": m.severity,
        "status": m.status,
        "reported_at": m.reported_at.isoformat(),
        "created_by": created_by,
        "created_by_id": m.created_by if include_user_names else None,
        "address": m.address,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        "photos": [{"id": p.id, "url": f"/uploads/{p.filename}", "tag": p.tag} for p in m.photos],
        "filled_at": m.filled_at.isoformat() if m.filled_at else None,
        "filled_by": filled_by,
        "category": (
            {"id": m.category.id, "name": m.category.name, "icon": m.category.icon, "color": m.category.color}
            if m.category else None
        ),
        "confirmation_count": confirmation_count(db, m.id) if db is not None else 0,
        "has_confirmed": user_has_confirmed(db, m.id, user.id) if (db is not None and user is not None) else False,
    }


def log_event(db: Session, marker_id: int, user_id: int, field: str, old_value, new_value):
    db.add(MarkerEvent(
        marker_id=marker_id,
        user_id=user_id,
        field=field,
        old_value=str(old_value) if old_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
    ))


class MarkerCreate(BaseModel):
    lat: float
    lng: float
    title: str
    description: str = ""
    severity: str = "medium"
    address: str = ""
    category_id: Optional[int] = None


class MarkerUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    address: Optional[str] = None
    category_id: Optional[int] = None


class CommentCreate(BaseModel):
    text: str


def _apply_filters(query, status: Optional[str], severity: Optional[str], category_id: Optional[int]):
    if status:
        query = query.filter(Marker.status == status)
    if severity:
        query = query.filter(Marker.severity == severity)
    if category_id is not None:
        if category_id == 0:
            query = query.filter(Marker.category_id.is_(None))
        else:
            query = query.filter(Marker.category_id == category_id)
    return query


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    markers = db.query(Marker).order_by(Marker.severity, Marker.reported_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Titel", "Beskrivning", "Kategori", "Allvarlighet", "Status", "Rapporterad", "Av", "Lat", "Lng"])
    for m in markers:
        writer.writerow([
            m.id, m.title, m.description,
            m.category.name if m.category else "",
            SEVERITY_LABEL.get(m.severity, m.severity),
            STATUS_LABEL.get(m.status, m.status),
            m.reported_at.strftime("%Y-%m-%d"),
            m.creator.username, m.lat, m.lng,
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=vagskador.csv"},
    )


@router.get("")
def list_markers(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
    sort: str = Query("reported_desc"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = _apply_filters(db.query(Marker), status, severity, category_id)
    if sort == "reported_asc":
        results = query.order_by(Marker.reported_at.asc()).all()
    elif sort == "severity":
        results = query.all()
        results.sort(key=lambda m: (SEVERITY_RANK.get(m.severity, 99), -m.reported_at.timestamp()))
    else:
        results = query.order_by(Marker.reported_at.desc()).all()
    return [marker_dict(m, db, user) for m in results]


@router.post("")
def create_marker(
    body: MarkerCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.severity not in VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail="Ogiltig allvarlighetsgrad")
    if body.category_id is not None and not db.get(Category, body.category_id):
        raise HTTPException(status_code=400, detail="Ogiltig kategori")
    payload = body.model_dump()
    payload["address"] = payload.pop("address").strip() or None
    m = Marker(**payload, created_by=user.id)
    db.add(m)
    db.commit()
    db.refresh(m)
    background_tasks.add_task(send_new_marker_email, m.title, user.username)
    if not m.address:
        background_tasks.add_task(geocode_marker, m.id, m.lat, m.lng)
    return marker_dict(m, db, user)


@router.patch("/{marker_id}")
def update_marker(
    marker_id: int,
    body: MarkerUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    m = db.get(Marker, marker_id)
    if not m:
        raise HTTPException(status_code=404, detail="Hittades inte")
    if m.created_by != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Åtkomst nekad")
    updates = body.model_dump(exclude_unset=True)
    if "severity" in updates and updates["severity"] not in VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail="Ogiltig allvarlighetsgrad")
    if "status" in updates and updates["status"] not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Ogiltig status")
    if "category_id" in updates and updates["category_id"] is not None and not db.get(Category, updates["category_id"]):
        raise HTTPException(status_code=400, detail="Ogiltig kategori")

    if "status" in updates and updates["status"] != m.status:
        log_event(db, m.id, user.id, "status", m.status, updates["status"])
        if updates["status"] == "filled" and m.status == "unfilled":
            m.filled_at = datetime.now(timezone.utc)
            m.filled_by_id = user.id
        elif updates["status"] == "unfilled":
            m.filled_at = None
            m.filled_by_id = None
    if "severity" in updates and updates["severity"] != m.severity:
        log_event(db, m.id, user.id, "severity", m.severity, updates["severity"])
    if "category_id" in updates and updates["category_id"] != m.category_id:
        old_name = m.category.name if m.category else None
        new_name = None
        if updates["category_id"] is not None:
            cat = db.get(Category, updates["category_id"])
            new_name = cat.name if cat else None
        log_event(db, m.id, user.id, "category", old_name, new_name)

    for field, value in updates.items():
        setattr(m, field, value)
    m.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(m)
    return marker_dict(m, db, user)


@router.delete("/{marker_id}")
def delete_marker(marker_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.get(Marker, marker_id)
    if not m:
        raise HTTPException(status_code=404, detail="Hittades inte")
    if m.created_by != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Åtkomst nekad")
    db.delete(m)
    db.commit()
    return {"ok": True}


# ── Confirmations ──────────────────────────────────────────────────────────

@router.post("/{marker_id}/confirm")
def confirm_marker(marker_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.get(Marker, marker_id)
    if not m:
        raise HTTPException(status_code=404, detail="Hittades inte")
    existing = db.query(Confirmation).filter(Confirmation.marker_id == marker_id, Confirmation.user_id == user.id).first()
    if not existing:
        db.add(Confirmation(marker_id=marker_id, user_id=user.id))
        db.commit()
    return {"confirmation_count": confirmation_count(db, marker_id), "has_confirmed": True}


@router.delete("/{marker_id}/confirm")
def unconfirm_marker(marker_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    existing = db.query(Confirmation).filter(Confirmation.marker_id == marker_id, Confirmation.user_id == user.id).first()
    if existing:
        db.delete(existing)
        db.commit()
    return {"confirmation_count": confirmation_count(db, marker_id), "has_confirmed": False}


# ── Events (audit log) ─────────────────────────────────────────────────────

@router.get("/{marker_id}/events")
def get_events(marker_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.get(Marker, marker_id)
    if not m:
        raise HTTPException(status_code=404, detail="Hittades inte")
    return [
        {
            "id": e.id,
            "field": e.field,
            "old_value": e.old_value,
            "new_value": e.new_value,
            "user": e.user.name or e.user.username,
            "created_at": e.created_at.isoformat(),
        }
        for e in sorted(m.events, key=lambda x: x.created_at, reverse=True)
    ]


# ── Photos ─────────────────────────────────────────────────────────────────

@router.post("/{marker_id}/photos")
async def upload_photo(
    marker_id: int,
    file: UploadFile = File(...),
    tag: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    m = db.get(Marker, marker_id)
    if not m:
        raise HTTPException(status_code=404, detail="Hittades inte")
    ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
    filename = f"{uuid.uuid4()}{ext}"
    async with aiofiles.open(os.path.join(UPLOAD_DIR, filename), "wb") as f:
        await f.write(await file.read())
    photo = Photo(marker_id=marker_id, filename=filename, uploaded_by=user.id, tag=tag or None)
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return {"id": photo.id, "url": f"/uploads/{filename}"}


@router.delete("/{marker_id}/photos/{photo_id}")
def delete_photo(
    marker_id: int,
    photo_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    photo = db.get(Photo, photo_id)
    if not photo or photo.marker_id != marker_id:
        raise HTTPException(status_code=404, detail="Hittades inte")
    marker = db.get(Marker, marker_id)
    if photo.uploaded_by != user.id and marker.created_by != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Åtkomst nekad")
    try:
        os.remove(os.path.join(UPLOAD_DIR, photo.filename))
    except FileNotFoundError:
        pass
    db.delete(photo)
    db.commit()
    return {"ok": True}


# ── Comments ───────────────────────────────────────────────────────────────

@router.get("/{marker_id}/comments")
def get_comments(marker_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.get(Marker, marker_id)
    if not m:
        raise HTTPException(status_code=404, detail="Hittades inte")
    return [
        {
            "id": c.id,
            "text": c.text,
            "author": c.author.name or c.author.username,
            "user_id": c.user_id,
            "created_at": c.created_at.isoformat(),
        }
        for c in m.comments
    ]


@router.post("/{marker_id}/comments")
def add_comment(
    marker_id: int,
    body: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Kommentar får inte vara tom")
    m = db.get(Marker, marker_id)
    if not m:
        raise HTTPException(status_code=404, detail="Hittades inte")
    c = Comment(marker_id=marker_id, user_id=user.id, text=body.text.strip()[:500])
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "text": c.text, "author": c.author.name or c.author.username, "user_id": c.user_id, "created_at": c.created_at.isoformat()}


@router.delete("/{marker_id}/comments/{comment_id}")
def delete_comment(
    marker_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = db.get(Comment, comment_id)
    if not c or c.marker_id != marker_id:
        raise HTTPException(status_code=404, detail="Hittades inte")
    if c.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Åtkomst nekad")
    db.delete(c)
    db.commit()
    return {"ok": True}
