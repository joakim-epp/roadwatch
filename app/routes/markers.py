import os
import uuid
import aiofiles
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Marker, Photo, User
from ..auth import get_current_user

router = APIRouter(prefix="/api/markers", tags=["markers"])

UPLOAD_DIR = "/data/uploads"
VALID_SEVERITIES = {"low", "medium", "high"}
VALID_STATUSES = {"unfilled", "filled"}


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


@router.get("")
def list_markers(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [marker_dict(m) for m in db.query(Marker).order_by(Marker.reported_at.desc()).all()]


@router.post("")
def create_marker(body: MarkerCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.severity not in VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail="severity must be low, medium, or high")
    m = Marker(**body.model_dump(), created_by=user.id)
    db.add(m)
    db.commit()
    db.refresh(m)
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
        raise HTTPException(status_code=404, detail="Not found")
    if m.created_by != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    updates = body.model_dump(exclude_none=True)
    if "severity" in updates and updates["severity"] not in VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail="Invalid severity")
    if "status" in updates and updates["status"] not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    for field, value in updates.items():
        setattr(m, field, value)
    db.commit()
    db.refresh(m)
    return marker_dict(m)


@router.delete("/{marker_id}")
def delete_marker(marker_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.get(Marker, marker_id)
    if not m:
        raise HTTPException(status_code=404, detail="Not found")
    if m.created_by != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
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
        raise HTTPException(status_code=404, detail="Not found")
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
        raise HTTPException(status_code=404, detail="Not found")
    marker = db.get(Marker, marker_id)
    if photo.uploaded_by != user.id and marker.created_by != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        os.remove(os.path.join(UPLOAD_DIR, photo.filename))
    except FileNotFoundError:
        pass
    db.delete(photo)
    db.commit()
    return {"ok": True}
