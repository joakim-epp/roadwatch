import json
import urllib.request
from .database import SessionLocal
from .models import Marker


def geocode_marker(marker_id: int, lat: float, lng: float):
    url = (
        f"https://nominatim.openstreetmap.org/reverse"
        f"?format=json&lat={lat}&lon={lng}&accept-language=sv"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Grop/1.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read())
        addr = data.get("address", {})
        parts = [
            addr.get("road") or addr.get("hamlet") or addr.get("locality"),
            addr.get("village") or addr.get("town") or addr.get("city") or addr.get("municipality"),
        ]
        address = ", ".join(p for p in parts if p) or data.get("display_name", "").split(", ")[0]
    except Exception:
        return
    db = SessionLocal()
    try:
        m = db.get(Marker, marker_id)
        if m:
            m.address = address or None
            db.commit()
    finally:
        db.close()
