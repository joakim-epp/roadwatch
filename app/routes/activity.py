from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Marker, Comment, MarkerEvent, User
from ..auth import get_current_user

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("")
def list_activity(
    limit: int = Query(50, ge=1, le=200),
    before: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Pull recent markers, comments, events; union; sort; paginate.
    # Small dataset (community road tracker) — Python merge is fine.
    items = []
    for m in db.query(Marker).order_by(Marker.reported_at.desc()).limit(200).all():
        items.append({
            "kind": "marker_created",
            "at": m.reported_at,
            "marker_id": m.id,
            "marker_title": m.title,
            "user": m.creator.name or m.creator.username,
        })
    for c in db.query(Comment).order_by(Comment.created_at.desc()).limit(200).all():
        if not c.marker:
            continue
        items.append({
            "kind": "comment",
            "at": c.created_at,
            "marker_id": c.marker_id,
            "marker_title": c.marker.title,
            "user": c.author.name or c.author.username,
            "text": c.text,
        })
    for e in db.query(MarkerEvent).order_by(MarkerEvent.created_at.desc()).limit(200).all():
        if not e.marker:
            continue
        items.append({
            "kind": f"marker_{e.field}_changed",
            "at": e.created_at,
            "marker_id": e.marker_id,
            "marker_title": e.marker.title,
            "user": e.user.name or e.user.username,
            "field": e.field,
            "old_value": e.old_value,
            "new_value": e.new_value,
        })

    items.sort(key=lambda x: x["at"], reverse=True)

    if before:
        try:
            from datetime import datetime
            cutoff = datetime.fromisoformat(before.replace("Z", "+00:00"))
            items = [x for x in items if x["at"] < cutoff]
        except ValueError:
            pass

    items = items[:limit]
    return [{**x, "at": x["at"].isoformat()} for x in items]
