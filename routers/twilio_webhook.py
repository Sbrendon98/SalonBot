import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from twilio.request_validator import RequestValidator

from config import settings
from database import get_db
from services.conversation import handle_message

logger = logging.getLogger(__name__)
router = APIRouter()

_validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)


def _validate_twilio(request: Request, form: dict) -> None:
    if not settings.TWILIO_VALIDATE_SIGNATURE:
        return
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    if not _validator.validate(url, form, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


@router.post("/webhooks/twilio/whatsapp")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    form = dict(await request.form())
    _validate_twilio(request, form)

    from_number = form.get("From", "")
    body = form.get("Body", "").strip()
    num_media = int(form.get("NumMedia", "0"))
    media_urls = [form.get(f"MediaUrl{i}") for i in range(num_media)]

    logger.info("Inbound from %s | media: %d | body: %.80s", from_number, num_media, body)

    try:
        response_text = handle_message(
            db=db,
            from_number=from_number,
            body=body,
            media_urls=media_urls,
        )
    except Exception as exc:
        logger.exception("Error handling message from %s: %s", from_number, exc)
        return {"status": "error"}

    if response_text:
        from twilio.rest import Client as TwilioClient
        twilio = TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        try:
            twilio.messages.create(
                from_=settings.TWILIO_WHATSAPP_NUMBER,
                to=from_number,
                body=response_text,
            )
        except Exception as exc:
            logger.error("Failed to send reply to %s: %s", from_number, exc)

    return {"status": "ok"}
