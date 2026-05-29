import csv
import io
import os
import uuid
import aiofiles
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Marker, Photo, Comment, User
from ..auth import get_current_user
from ..email import send_new_marker_email

router = APIRouter(prefix="/api/markers", tags=["markers"])

UPLOAD_DIR = "/data/uploads"
VALID_SEVERITIES = {"low", "medium", "high"}
VALID_STATUSES = {"unfilled", "filled"}
SEVERITY_LABEL = {"high": "Hög", "medium": "Medel", "low": "Låg"}
STATUS_LABEL = {"unfilled": "Inte igenfylld", "filled": "Igenfylld"}


def marker_dict(m: Marker) -> dict:
    return {
        "id": m.id,
        "lat": m.lat,
        "lng": m.lng,
        "title": m.title,
        "description": m.description,
        "severity": m.severity,
        "status": m.status,
        "reported_at": m.reported_at.isoformat(),
        "created_by": m.creator.username,
        "created_by_id": m.created_by,
        "photos": [{"id": p.id, "url": f"/uploads/{p.filename}"} for p in m.photos],
        "filled_at": m.filled_at.isoformat() if m.filled_at else None,
    }


class MarkerCreate(BaseModel):
    lat: float
    lng: float
    title: str
    description: str = ""
    severity: str = "medium"


class MarkerUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None


class CommentCreate(BaseModel):
    text: str


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    markers = db.query(Marker).order_by(Marker.severity, Marker.reported_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Titel", "Beskrivning", "Allvarlighet", "Status", "Rapporterad", "Av", "Lat", "Lng"])
    for m in markers:
        writer.writerow([
            m.id, m.title, m.description,
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
def list_markers(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [marker_dict(m) for m in db.query(Marker).order_by(Marker.reported_at.desc()).all()]


@router.post("")
def create_marker(
    body: MarkerCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.severity not in VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail="Ogiltig allvarlighetsgrad")
    m = Marker(**body.model_dump(), created_by=user.id)
    db.add(m)
    db.commit()
    db.refresh(m)
    background_tasks.add_task(send_new_marker_email, m.title, user.username)
    return marker_dict(m)


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
    updates = body.model_dump(exclude_none=True)
    if "severity" in updates and updates["severity"] not in VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail="Ogiltig allvarlighetsgrad")
    if "status" in updates and updates["status"] not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Ogiltig status")
    if "status" in updates:
        if updates["status"] == "filled" and m.status == "unfilled":
            m.filled_at = datetime.now(timezone.utc)
        elif updates["status"] == "unfilled":
            m.filled_at = None
    for field, value in updates.items():
        setattr(m, field, value)
    db.commit()
    db.refresh(m)
    return marker_dict(m)


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


@router.post("/{marker_id}/photos")
async def upload_photo(
    marker_id: int,
    file: UploadFile = File(...),
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
    photo = Photo(marker_id=marker_id, filename=filename, uploaded_by=user.id)
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


@router.get("/{marker_id}/comments")
def get_comments(marker_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.get(Marker, marker_id)
    if not m:
        raise HTTPException(status_code=404, detail="Hittades inte")
    return [
        {
            "id": c.id,
            "text": c.text,
            "author": c.author.username,
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
    return {"id": c.id, "text": c.text, "author": c.author.username, "user_id": c.user_id, "created_at": c.created_at.isoformat()}


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
