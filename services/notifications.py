import logging
from twilio.rest import Client as TwilioClient
from config import settings
from models import Client

logger = logging.getLogger(__name__)

_twilio = TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


def _send(body: str) -> None:
    try:
        _twilio.messages.create(
            from_=settings.TWILIO_WHATSAPP_NUMBER,
            to=settings.OWNER_WHATSAPP_NUMBER,
            body=body,
        )
    except Exception as exc:
        logger.error("Failed to notify owner: %s", exc)


def _fmt_phone(number: str) -> str:
    digits = number.replace("+", "").replace(" ", "")
    if len(digits) == 11 and digits.startswith("1"):
        return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    return f"+{digits}"


def notify_new_client(client: Client) -> None:
    _send(
        f"👤 New client\n"
        f"Name: {client.full_name or 'Not collected yet'}\n"
        f"Number: {_fmt_phone(client.whatsapp_number)}"
    )


def notify_intake_complete(client: Client, photo_count: int = 0) -> None:
    photos_line = f"📸 Photos: {photo_count} saved\n" if photo_count else ""
    _send(
        f"✅ Intake complete\n"
        f"──────────────────\n"
        f"👤 {client.full_name}\n"
        f"📱 {_fmt_phone(client.whatsapp_number)}\n"
        f"💇 Service interest: {client.service_interest or 'Not selected yet'}\n"
        f"{photos_line}"
        f"Message: wa.me/{client.whatsapp_number.lstrip('+')}"
    )


def notify_consultation_request(client: Client, photo_count: int = 0) -> None:
    photos_line = f"📸 {photo_count} photo(s) saved\n" if photo_count else ""
    _send(
        f"📋 New consultation request\n"
        f"──────────────────────────\n"
        f"👤 {client.full_name}\n"
        f"📱 {_fmt_phone(client.whatsapp_number)}\n"
        f"💇 Service: {client.service_interest or 'Not selected'}\n"
        f"✅ Intake: Complete\n"
        f"{photos_line}"
        f"Message: wa.me/{client.whatsapp_number.lstrip('+')}"
    )


def notify_handoff(client: Client, trigger_message: str) -> None:
    _send(
        f"🚨 Handoff needed\n"
        f"──────────────────\n"
        f"👤 {client.full_name or 'Unknown'}\n"
        f"📱 {_fmt_phone(client.whatsapp_number)}\n"
        f"Trigger: \"{trigger_message[:200]}\"\n\n"
        f"Reply through this number. Send !resume {client.full_name or client.whatsapp_number} "
        f"when done."
    )


def notify_photo_received(client: Client, photo_url: str) -> None:
    _send(
        f"📸 Photo from {client.full_name or client.whatsapp_number}\n"
        f"{photo_url}"
    )
