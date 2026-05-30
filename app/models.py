from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    is_admin = Column(Integer, default=0)
    is_approved = Column(Integer, default=0)
    notify_email = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    markers = relationship("Marker", foreign_keys="Marker.created_by", back_populates="creator")


class Marker(Base):
    __tablename__ = "markers"

    id = Column(Integer, primary_key=True)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    title = Column(String, nullable=False)
    description = Column(String, default="")
    severity = Column(String, default="medium")  # low | medium | high
    status = Column(String, default="unfilled")   # unfilled | filled
    reported_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    address = Column(String, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    filled_at = Column(DateTime, nullable=True)
    filled_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)

    creator = relationship("User", foreign_keys=[created_by], back_populates="markers")
    filler = relationship("User", foreign_keys=[filled_by_id])
    category = relationship("Category")
    photos = relationship("Photo", back_populates="marker", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="marker", cascade="all, delete-orphan", order_by="Comment.created_at")
    confirmations = relationship("Confirmation", back_populates="marker", cascade="all, delete-orphan")
    events = relationship("MarkerEvent", back_populates="marker", cascade="all, delete-orphan", order_by="MarkerEvent.created_at.desc()")


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)


class Photo(Base):
    __tablename__ = "photos"

    id = Column(Integer, primary_key=True)
    marker_id = Column(Integer, ForeignKey("markers.id"), nullable=False)
    filename = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    tag = Column(String, nullable=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    marker = relationship("Marker", back_populates="photos")


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    marker_id = Column(Integer, ForeignKey("markers.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    text = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    marker = relationship("Marker", back_populates="comments")
    author = relationship("User")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    icon = Column(String, nullable=False, default="📍")
    color = Column(String, nullable=False, default="#3b82f6")
    sort_order = Column(Integer, default=0)


class Confirmation(Base):
    __tablename__ = "confirmations"

    id = Column(Integer, primary_key=True)
    marker_id = Column(Integer, ForeignKey("markers.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    marker = relationship("Marker", back_populates="confirmations")
    user = relationship("User")

    __table_args__ = (UniqueConstraint("marker_id", "user_id", name="uq_confirmation_marker_user"),)


class MarkerEvent(Base):
    __tablename__ = "marker_events"

    id = Column(Integer, primary_key=True)
    marker_id = Column(Integer, ForeignKey("markers.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    field = Column(String, nullable=False)        # status | severity | category
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    marker = relationship("Marker", back_populates="events")
    user = relationship("User")
