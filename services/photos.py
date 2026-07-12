import logging
from datetime import datetime
from sqlalchemy.orm import Session

import requests

from config import settings
from models import ClientPhoto

logger = logging.getLogger(__name__)

# Service menu map used for display and storage
SERVICES = {
    "1": "Starter Locs",
    "2": "Loc Maintenance",
    "3": "Loc Retwist",
    "4": "Natural Hair Styling",
    "5": "Color Services",
    "6": "General Consultation",
}


def _upload_to_twicpics(image_bytes: bytes, client_id: str, filename: str) -> dict:
    """
    Upload image bytes to TwicPics.
    API docs: https://www.twicpics.com/docs/api/upload
    """
    response = requests.post(
        "https://api.twicpics.com/v1/upload",
        headers={"Authorization": f"Bearer {settings.TWICPICS_API_KEY}"},
        files={"file": (filename, image_bytes, "image/jpeg")},
        data={"path": f"clients/{client_id}/"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    path = data.get("path", "")
    url = f"{settings.TWICPICS_DOMAIN.rstrip('/')}/{path.lstrip('/')}" if path else ""
    return {"url": url, "path": path, "storage_type": "twicpics"}


def save_photo(
    db: Session,
    client_id: str,
    twilio_media_url: str,
    context_message: str = "",
) -> ClientPhoto:
    """
    Download photo from Twilio, attempt TwicPics upload, fall back to
    storing the raw Twilio URL if TwicPics is not configured or upload fails.
    """
    url = twilio_media_url
    twicpics_path = None
    storage_type = "twilio"

    if settings.TWICPICS_API_KEY and settings.TWICPICS_DOMAIN:
        try:
            resp = requests.get(
                twilio_media_url,
                auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                timeout=30,
            )
            resp.raise_for_status()
            filename = f"{client_id}_{int(datetime.utcnow().timestamp())}.jpg"
            result = _upload_to_twicpics(resp.content, client_id, filename)
            if result["url"]:
                url = result["url"]
                twicpics_path = result["path"]
                storage_type = "twicpics"
        except Exception as exc:
            logger.warning("TwicPics upload failed, storing Twilio URL: %s", exc)

    photo = ClientPhoto(
        client_id=client_id,
        url=url,
        twicpics_path=twicpics_path,
        storage_type=storage_type,
        conversation_context=context_message[:500] if context_message else None,
        sent_at=datetime.utcnow(),
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


def get_client_photo_count(db: Session, client_id: str) -> int:
    return db.query(ClientPhoto).filter_by(client_id=client_id).count()


def get_client_photo_urls(db: Session, client_id: str) -> list[str]:
    photos = db.query(ClientPhoto).filter_by(client_id=client_id).all()
    return [p.url for p in photos]
