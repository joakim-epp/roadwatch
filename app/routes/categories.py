from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import update
from ..database import get_db
from ..models import Category, Marker, User
from ..auth import get_current_user

router = APIRouter(prefix="/api/categories", tags=["categories"])


def category_dict(c: Category) -> dict:
    return {"id": c.id, "name": c.name, "icon": c.icon, "color": c.color, "sort_order": c.sort_order}


class CategoryCreate(BaseModel):
    name: str
    icon: str = "📍"
    color: str = "#3b82f6"
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


@router.get("")
def list_categories(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [category_dict(c) for c in db.query(Category).order_by(Category.sort_order, Category.name).all()]


@router.post("")
def create_category(body: CategoryCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Åtkomst nekad")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Namn krävs")
    if db.query(Category).filter(Category.name == name).first():
        raise HTTPException(status_code=400, detail="Kategori finns redan")
    c = Category(name=name, icon=body.icon.strip() or "📍", color=body.color.strip() or "#3b82f6", sort_order=body.sort_order)
    db.add(c)
    db.commit()
    db.refresh(c)
    return category_dict(c)


@router.patch("/{category_id}")
def update_category(category_id: int, body: CategoryUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Åtkomst nekad")
    c = db.get(Category, category_id)
    if not c:
        raise HTTPException(status_code=404, detail="Hittades inte")
    for field, value in body.model_dump(exclude_none=True).items():
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        setattr(c, field, value)
    db.commit()
    db.refresh(c)
    return category_dict(c)


@router.delete("/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Åtkomst nekad")
    c = db.get(Category, category_id)
    if not c:
        raise HTTPException(status_code=404, detail="Hittades inte")
    db.execute(update(Marker).where(Marker.category_id == category_id).values(category_id=None))
    db.delete(c)
    db.commit()
    return {"ok": True}
