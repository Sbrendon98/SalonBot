import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from twilio.rest import Client as TwilioClient

from config import settings
from database import get_db
from models import Client, Conversation
from services.identity import get_or_create_conversation, set_state
from services import notifications

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhooks/tally/intake")
async def tally_intake_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Tally.so fires this when a client submits the intake form.
    Tally sends JSON — configure the webhook URL in Tally's form settings.
    """
    payload = await request.json()
    logger.info("Tally submission received")

    email = _extract_email_from_tally(payload)
    submission_id = payload.get("eventId") or payload.get("id", "")

    if not email:
        logger.warning("Tally submission missing email: %s", payload)
        return {"status": "ignored", "reason": "no email found"}

    client = db.query(Client).filter(Client.email == email.lower()).first()
    if not client:
        logger.info("Tally submission for unknown email: %s", email)
        return {"status": "ignored", "reason": "client not found"}

    client.intake_completed = True
    client.intake_tally_submission_id = str(submission_id)

    from datetime import datetime
    client.intake_submitted_at = datetime.utcnow()
    db.commit()

    # Transition conversation if it's waiting on intake
    conv = (
        db.query(Conversation)
        .filter_by(client_id=client.id, state="INTAKE_PENDING")
        .first()
    )
    if conv:
        set_state(db, conv, "ACTIVE")
        _send_whatsapp(
            client.whatsapp_number,
            f"Your intake form is complete — thanks, "
            f"{(client.full_name or '').split()[0] or 'there'}! "
            f"How can I help you today?"
        )

    from services.photos import get_client_photo_count
    notifications.notify_intake_complete(client, get_client_photo_count(db, client.id))

    return {"status": "ok"}


def _extract_email_from_tally(payload: dict) -> str | None:
    """
    Tally wraps answers in payload['data']['fields'].
    Find the field whose label contains 'email' (case-insensitive).
    """
    try:
        fields = payload.get("data", {}).get("fields", [])
        for field in fields:
            label = (field.get("label") or "").lower()
            if "email" in label:
                val = field.get("value")
                if isinstance(val, str):
                    return val.strip().lower()
    except Exception:
        pass

    # Fallback: check top-level keys
    return payload.get("email") or payload.get("respondentEmail")


def _send_whatsapp(to_number: str, body: str) -> None:
    if not to_number:
        return
    twilio = TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    try:
        twilio.messages.create(
            from_=settings.TWILIO_WHATSAPP_NUMBER,
            to=f"whatsapp:{to_number}",
            body=body,
        )
    except Exception as exc:
        logger.error("Failed to notify client after Tally intake: %s", exc)
