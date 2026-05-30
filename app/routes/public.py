from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Marker, Setting, Category

router = APIRouter(prefix="/api/public", tags=["public"])


def public_marker_dict(m: Marker) -> dict:
    return {
        "id": m.id,
        "lat": m.lat,
        "lng": m.lng,
        "title": m.title,
        "description": m.description,
        "severity": m.severity,
        "status": m.status,
        "reported_at": m.reported_at.isoformat(),
        "address": m.address,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        "photos": [{"id": p.id, "url": f"/uploads/{p.filename}", "tag": p.tag} for p in m.photos],
        "filled_at": m.filled_at.isoformat() if m.filled_at else None,
        "category": (
            {"id": m.category.id, "name": m.category.name, "icon": m.category.icon, "color": m.category.color}
            if m.category else None
        ),
        "confirmation_count": len(m.confirmations),
    }


@router.get("/markers")
def public_markers(db: Session = Depends(get_db)):
    markers = db.query(Marker).order_by(Marker.reported_at.desc()).all()
    return [public_marker_dict(m) for m in markers]


@router.get("/settings")
def public_settings(db: Session = Depends(get_db)):
    rows = db.query(Setting).all()
    return {r.key: r.value for r in rows}


@router.get("/categories")
def public_categories(db: Session = Depends(get_db)):
    return [
        {"id": c.id, "name": c.name, "icon": c.icon, "color": c.color}
        for c in db.query(Category).order_by(Category.sort_order, Category.name).all()
    ]
