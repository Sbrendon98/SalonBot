import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from config import settings
from models import Appointment, Client, Conversation, Message, RetentionEvent
from services import claude_ai, notifications, photos as photo_service
from services.identity import (
    extract_email,
    extract_name,
    get_or_create_client,
    get_or_create_conversation,
    is_valid_email,
    normalize_phone,
    resolve_command_target,
    set_state,
)

logger = logging.getLogger(__name__)

OWNER_NUMBER = normalize_phone(settings.OWNER_WHATSAPP_NUMBER)

OPT_OUT_KEYWORDS = {"stop", "unsubscribe", "remove me", "stop messaging", "don't message", "dont message"}
HANDOFF_KEYWORDS = {"real person", "speak to someone", "talk to someone", "talk to stephanie",
                    "speak to stephanie", "complaint", "refund", "not happy", "disappointed",
                    "terrible", "awful", "lawsuit", "report this"}
BOOKING_KEYWORDS = {"book", "booking", "appointment", "schedule", "come in",
                    "ready to", "how do i", "consultation", "sign up"}

STYLE_MENU = (
    "What service are you looking for? Reply with the number:\n\n"
    "1 - Starter Locs\n"
    "2 - Loc Maintenance\n"
    "3 - Loc Retwist\n"
    "4 - Natural Hair Styling\n"
    "5 - Color Services\n"
    "6 - General Consultation"
)

SERVICES = {
    "1": "Starter Locs",
    "2": "Loc Maintenance",
    "3": "Loc Retwist",
    "4": "Natural Hair Styling",
    "5": "Color Services",
    "6": "General Consultation",
    "starter locs": "Starter Locs",
    "loc maintenance": "Loc Maintenance",
    "loc retwist": "Loc Retwist",
    "natural hair styling": "Natural Hair Styling",
    "color services": "Color Services",
    "general consultation": "General Consultation",
    "consultation": "General Consultation",
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def handle_message(
    db: Session,
    from_number: str,
    body: str,
    media_urls: list[str] | None = None,
) -> str | None:
    phone = normalize_phone(from_number)

    if phone == OWNER_NUMBER:
        return _handle_owner_command(db, body.strip())

    client = get_or_create_client(db, phone)
    client.last_seen_at = datetime.utcnow()
    db.commit()

    conversation = get_or_create_conversation(db, client.id)

    _save_message(db, conversation.id, client.id, "inbound", "client", body)

    # Handle any photos attached to this message
    for url in (media_urls or []):
        if url:
            photo = photo_service.save_photo(db, client.id, url, body)
            notifications.notify_photo_received(client, photo.url)

    if conversation.state in ("HANDOFF", "SILENT"):
        return None

    # Opt-out check (any state)
    if _is_opt_out(body):
        return _handle_opt_out(db, client, conversation)

    response = _route(db, client, conversation, body, bool(media_urls))

    if response:
        _save_message(db, conversation.id, client.id, "outbound", "bot", response)
        db.commit()

    return response


# ---------------------------------------------------------------------------
# State router
# ---------------------------------------------------------------------------

def _route(
    db: Session,
    client: Client,
    conversation: Conversation,
    body: str,
    has_photo: bool,
) -> str | None:
    state = conversation.state

    if state == "NEW":
        return _handle_new(db, client, conversation, body)
    if state == "INTAKE_PENDING":
        return _handle_intake_pending(db, client, conversation, body)
    if state == "ACTIVE":
        return _handle_active(db, client, conversation, body, has_photo)
    if state == "STYLE_MENU":
        return _handle_style_menu(db, client, conversation, body)
    if state == "BOOKING_SENT":
        return _handle_booking_sent(db, client, conversation, body)
    if state == "RESUMED":
        set_state(db, conversation, "ACTIVE")
        return _handle_active(db, client, conversation, body, has_photo)
    return None


# ---------------------------------------------------------------------------
# State handlers
# ---------------------------------------------------------------------------

def _handle_new(
    db: Session, client: Client, conversation: Conversation, body: str
) -> str:
    owner = settings.OWNER_NAME

    if not client.full_name:
        outbound_count = (
            db.query(Message)
            .filter_by(conversation_id=conversation.id, direction="outbound")
            .count()
        )
        if outbound_count == 0:
            # Very first contact — greet and ask for name
            notifications.notify_new_client(client)
            return (
                f"Hi there! 👋 Welcome to The Definition by {owner}.\n\n"
                f"I'm {owner}'s assistant. To get started, what's your full name?"
            )
        # They replied — save as name
        client.full_name = extract_name(body)
        db.commit()
        return f"Nice to meet you, {client.full_name.split()[0]}! What's your email address?"

    if not client.email:
        if not is_valid_email(body):
            return "That doesn't look like a valid email. Could you double-check it?"
        email = extract_email(body)
        # Check if another client already has this email and merge
        existing = db.query(Client).filter(
            Client.email == email, Client.id != client.id
        ).first()
        if existing:
            client = existing  # use existing record
        else:
            client.email = email
            db.commit()
        return _check_intake_and_transition(db, client, conversation)

    # Both collected — shouldn't linger in NEW
    return _check_intake_and_transition(db, client, conversation)


def _check_intake_and_transition(
    db: Session, client: Client, conversation: Conversation
) -> str:
    first_name = (client.full_name or "").split()[0]
    if client.intake_completed:
        set_state(db, conversation, "ACTIVE")
        return (
            f"You're all set, {first_name}! "
            f"How can I help you today?"
        )
    set_state(db, conversation, "INTAKE_PENDING")
    form_url = settings.TALLY_FORM_URL or "[form link coming soon]"
    return (
        f"Thanks, {first_name}! Before we go any further, {settings.OWNER_NAME} "
        f"requires all clients to complete a quick intake form — it helps her prepare "
        f"for your visit so nothing gets missed.\n\n"
        f"Complete it here: {form_url}\n\n"
        f"It takes about 5 minutes. I'll be right here when you're done. ✅"
    )


def _handle_intake_pending(
    db: Session, client: Client, conversation: Conversation, body: str
) -> str:
    db.refresh(client)
    if client.intake_completed:
        set_state(db, conversation, "ACTIVE")
        first_name = (client.full_name or "").split()[0]
        return (
            f"Your intake form is complete — thanks, {first_name}! "
            f"How can I help you today?"
        )
    form_url = settings.TALLY_FORM_URL or "[form link coming soon]"
    return (
        f"I'm still waiting on your intake form before we can continue. "
        f"It's a quick 5-minute form that helps {settings.OWNER_NAME} prepare for your visit.\n\n"
        f"{form_url}"
    )


def _handle_active(
    db: Session,
    client: Client,
    conversation: Conversation,
    body: str,
    has_photo: bool,
) -> str:
    # Handoff keyword check
    if _is_handoff(body):
        return _trigger_handoff(db, client, conversation, body)

    # Booking intent check
    if _is_booking_intent(body):
        set_state(db, conversation, "STYLE_MENU")
        return STYLE_MENU

    if has_photo and not body.strip():
        return "Photo saved to your profile — Stephanie will have it ready when you meet. 📸"

    # Pass to Claude
    messages = conversation.messages
    history = claude_ai.build_history(messages)
    history.append({"role": "user", "content": body})

    response = claude_ai.get_response(settings.OWNER_NAME, history)

    if response.startswith("[HANDOFF]"):
        client_message = response[9:].strip()
        _trigger_handoff(db, client, conversation, body)
        return client_message

    if response.startswith("[BOOKING_READY]"):
        set_state(db, conversation, "STYLE_MENU")
        return STYLE_MENU

    return response


def _handle_style_menu(
    db: Session, client: Client, conversation: Conversation, body: str
) -> str:
    selection = body.strip().lower().rstrip(".")
    service = SERVICES.get(selection) or SERVICES.get(selection.title())

    if not service:
        return (
            "Please reply with the number for your service:\n\n"
            "1 - Starter Locs\n"
            "2 - Loc Maintenance\n"
            "3 - Loc Retwist\n"
            "4 - Natural Hair Styling\n"
            "5 - Color Services\n"
            "6 - General Consultation"
        )

    client.service_interest = service
    db.commit()

    set_state(db, conversation, "BOOKING_SENT")

    photo_count = photo_service.get_client_photo_count(db, client.id)
    notifications.notify_consultation_request(client, photo_count)

    booking_url = settings.GLOSSGENIUS_BOOKING_URL or "[booking link coming soon]"
    return (
        f"Perfect — {service} it is! 💇\n\n"
        f"Here's {settings.OWNER_NAME}'s booking page. Grab a consultation slot "
        f"that works for you:\n\n"
        f"{booking_url}\n\n"
        f"{settings.OWNER_NAME} will have your full profile ready before you arrive."
    )


def _handle_booking_sent(
    db: Session, client: Client, conversation: Conversation, body: str
) -> str:
    # If they ask something new after the link was sent, drop back to ACTIVE
    set_state(db, conversation, "ACTIVE")
    return _handle_active(db, client, conversation, body, False)


# ---------------------------------------------------------------------------
# Opt-out
# ---------------------------------------------------------------------------

def _is_opt_out(body: str) -> bool:
    lower = body.lower().strip()
    if lower == "stop":
        return True
    return any(kw in lower for kw in OPT_OUT_KEYWORDS)


def _handle_opt_out(
    db: Session, client: Client, conversation: Conversation
) -> str:
    client.opted_out = True
    client.opted_out_at = datetime.utcnow()
    db.query(RetentionEvent).filter_by(
        client_id=client.id, status="pending"
    ).update({"status": "cancelled"})
    set_state(db, conversation, "SILENT")
    db.commit()
    notifications._send(
        f"⛔ {client.full_name or client.whatsapp_number} opted out of messages."
    )
    return (
        "You've been removed from all automated messages. "
        f"You can still reach out any time if you'd like to book with {settings.OWNER_NAME}."
    )


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------

def _is_handoff(body: str) -> bool:
    lower = body.lower()
    return any(kw in lower for kw in HANDOFF_KEYWORDS)


def _trigger_handoff(
    db: Session, client: Client, conversation: Conversation, trigger: str
) -> str:
    conversation.handoff_trigger_message = trigger[:500]
    set_state(db, conversation, "SILENT")
    notifications.notify_handoff(client, trigger)
    return f"Let me get {settings.OWNER_NAME} for you — she'll follow up shortly."


# ---------------------------------------------------------------------------
# Retention sequences
# ---------------------------------------------------------------------------

def schedule_post_visit_sequences(db: Session, client: Client) -> None:
    """Called when owner logs !appt done. Schedules follow-up messages."""
    now = datetime.utcnow()
    steps = [
        ("post_visit", 1, timedelta(hours=48)),
        ("post_visit", 2, timedelta(days=42)),
        ("post_visit", 3, timedelta(days=90)),
    ]
    for seq, step, delta in steps:
        exists = db.query(RetentionEvent).filter_by(
            client_id=client.id, sequence_name=seq, step_number=step
        ).first()
        if not exists:
            db.add(RetentionEvent(
                client_id=client.id,
                sequence_name=seq,
                step_number=step,
                status="pending",
                scheduled_for=now + delta,
            ))
    db.commit()


def get_retention_message(client: Client, sequence: str, step: int) -> str | None:
    name = (client.full_name or "").split()[0] or "there"
    owner = settings.OWNER_NAME
    booking = settings.GLOSSGENIUS_BOOKING_URL or "[booking link]"

    templates = {
        ("post_visit", 1): (
            f"Hey {name}! It's been a couple of days — how are you loving your hair? "
            f"💬 {owner} would love to hear from you."
        ),
        ("post_visit", 2): (
            f"Hey {name}, it's been about 6 weeks since your visit. "
            f"Ready to book your next appointment?\n\n{booking}"
        ),
        ("post_visit", 3): (
            f"{name}, {owner} has some time coming up in her calendar — "
            f"wanted to make sure you had the chance to get in before it fills.\n\n{booking}"
        ),
        ("win_back", 1): (
            f"Hey {name} — {owner} was thinking about you. "
            f"It's been a while since your last visit. How's your hair doing?\n\n{booking}"
        ),
        ("win_back", 2): (
            f"{name}, it's been about 6 months — {owner} still has your hair notes from "
            f"your last visit and would love to help with what's next.\n\n{booking}"
        ),
        ("win_back", 3): (
            f"{name}, it's been a full year. {owner} remembers your hair and would love "
            f"to give it a refresh whenever you're ready.\n\n{booking}"
        ),
    }
    return templates.get((sequence, step))


def process_due_retention_messages(db: Session) -> None:
    """Run every 5 minutes from the background worker."""
    from twilio.rest import Client as TwilioClient
    twilio = TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

    now = datetime.utcnow()
    due = (
        db.query(RetentionEvent)
        .filter(RetentionEvent.status == "pending", RetentionEvent.scheduled_for <= now)
        .all()
    )

    for event in due:
        client = db.query(Client).get(event.client_id)
        if not client or client.opted_out or not client.whatsapp_number:
            event.status = "skipped"
            db.commit()
            continue

        # Cancel if client rebooked since sequence was created
        if client.last_appointment_at and event.scheduled_for:
            if client.last_appointment_at > event.created_at:
                event.status = "cancelled"
                db.commit()
                continue

        message = get_retention_message(client, event.sequence_name, event.step_number)
        if not message:
            event.status = "skipped"
            db.commit()
            continue

        try:
            twilio.messages.create(
                from_=settings.TWILIO_WHATSAPP_NUMBER,
                to=f"whatsapp:{client.whatsapp_number}",
                body=message,
            )
            event.status = "sent"
            event.sent_at = now
        except Exception as exc:
            logger.error("Failed to send retention message %s: %s", event.id, exc)

        db.commit()


# ---------------------------------------------------------------------------
# Owner commands
# ---------------------------------------------------------------------------

HELP_TEXT = """Owner commands:
!pause [name] — silence bot, take over
!resume [name] — return to bot
!status [name] — client info
!intake done [name] — mark intake complete
!appt done [name] — log appointment + schedule follow-ups
!optout [name] — opt client out
!optin [name] — opt client back in
!optlist — list all opted-out clients
!note [name] | [text] — add a note
!who [name] — quick lookup"""


def _handle_owner_command(db: Session, body: str) -> str:
    lower = body.lower()

    if lower == "!help":
        return HELP_TEXT

    if lower == "!optlist":
        opted = db.query(Client).filter_by(opted_out=True).all()
        if not opted:
            return "No opted-out clients."
        lines = [
            f"• {c.full_name or 'Unknown'} — {c.whatsapp_number} — "
            f"opted out {c.opted_out_at.strftime('%Y-%m-%d') if c.opted_out_at else '?'}"
            for c in opted
        ]
        return "Opted-out clients:\n" + "\n".join(lines)

    # Commands with [name] argument
    for prefix, handler in [
        ("!pause ",        _cmd_pause),
        ("!resume ",       _cmd_resume),
        ("!status ",       _cmd_status),
        ("!who ",          _cmd_status),
        ("!intake done ",  _cmd_intake_done),
        ("!appt done ",    _cmd_appt_done),
        ("!optout ",       _cmd_optout),
        ("!optin ",        _cmd_optin),
        ("!note ",         _cmd_note),
    ]:
        if lower.startswith(prefix):
            arg = body[len(prefix):].strip()
            return handler(db, arg)

    return "⚠️ Unrecognized command. Send !help for the full list."


def _get_client_or_error(db: Session, arg: str):
    client = resolve_command_target(db, arg)
    if not client:
        return None, f"Client not found: \"{arg}\""
    return client, None


def _cmd_pause(db: Session, arg: str) -> str:
    client, err = _get_client_or_error(db, arg)
    if err:
        return err
    conv = get_or_create_conversation(db, client.id)
    set_state(db, conv, "SILENT")
    return f"✅ Bot paused for {client.full_name}. You're on."


def _cmd_resume(db: Session, arg: str) -> str:
    client, err = _get_client_or_error(db, arg)
    if err:
        return err
    conv = get_or_create_conversation(db, client.id)
    set_state(db, conv, "ACTIVE")
    return f"✅ Bot resumed for {client.full_name}."


def _cmd_status(db: Session, arg: str) -> str:
    client, err = _get_client_or_error(db, arg)
    if err:
        return err
    conv = get_or_create_conversation(db, client.id)
    last_appt = (
        client.last_appointment_at.strftime("%Y-%m-%d")
        if client.last_appointment_at else "None on record"
    )
    return (
        f"👤 {client.full_name}\n"
        f"📱 {client.whatsapp_number}\n"
        f"📧 {client.email or 'No email'}\n"
        f"✅ Intake: {'Complete' if client.intake_completed else 'Pending'}\n"
        f"💇 Service interest: {client.service_interest or 'Not selected'}\n"
        f"📅 Last appointment: {last_appt}\n"
        f"🔢 Total appointments: {client.total_appointments}\n"
        f"🤖 Bot state: {conv.state}\n"
        f"⛔ Opted out: {'Yes' if client.opted_out else 'No'}"
    )


def _cmd_intake_done(db: Session, arg: str) -> str:
    client, err = _get_client_or_error(db, arg)
    if err:
        return err
    client.intake_completed = True
    client.intake_submitted_at = datetime.utcnow()
    conv = get_or_create_conversation(db, client.id)
    if conv.state == "INTAKE_PENDING":
        set_state(db, conv, "ACTIVE")
    db.commit()
    return f"✅ Intake marked complete for {client.full_name}."


def _cmd_appt_done(db: Session, arg: str) -> str:
    client, err = _get_client_or_error(db, arg)
    if err:
        return err
    now = datetime.utcnow()
    client.last_appointment_at = now
    client.total_appointments = (client.total_appointments or 0) + 1
    db.add(Appointment(
        client_id=client.id,
        service_type=client.service_interest,
        appointment_at=now,
        status="completed",
    ))
    # Cancel any existing pending post_visit sequences before scheduling new ones
    db.query(RetentionEvent).filter_by(
        client_id=client.id, sequence_name="post_visit", status="pending"
    ).update({"status": "cancelled"})
    db.commit()
    schedule_post_visit_sequences(db, client)
    return (
        f"✅ Appointment logged for {client.full_name} "
        f"(total: {client.total_appointments}).\n"
        f"48hr follow-up scheduled."
    )


def _cmd_optout(db: Session, arg: str) -> str:
    client, err = _get_client_or_error(db, arg)
    if err:
        return err
    client.opted_out = True
    client.opted_out_at = datetime.utcnow()
    db.query(RetentionEvent).filter_by(
        client_id=client.id, status="pending"
    ).update({"status": "cancelled"})
    db.commit()
    return f"⛔ {client.full_name} opted out. All sequences cancelled."


def _cmd_optin(db: Session, arg: str) -> str:
    client, err = _get_client_or_error(db, arg)
    if err:
        return err
    client.opted_out = False
    client.opted_out_at = None
    db.commit()
    return f"✅ {client.full_name} opted back in."


def _cmd_note(db: Session, arg: str) -> str:
    if "|" not in arg:
        return "Format: !note [name] | [text]"
    name_part, note_text = arg.split("|", 1)
    client, err = _get_client_or_error(db, name_part.strip())
    if err:
        return err
    timestamp = datetime.utcnow().strftime("%Y-%m-%d")
    existing = client.notes or ""
    client.notes = f"{existing}\n[{timestamp}] {note_text.strip()}".strip()
    db.commit()
    return f"✅ Note added to {client.full_name}'s profile."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_booking_intent(body: str) -> bool:
    lower = body.lower()
    return any(kw in lower for kw in BOOKING_KEYWORDS)


def _save_message(
    db: Session,
    conversation_id: str,
    client_id: str,
    direction: str,
    sender: str,
    body: str,
    media_url: str | None = None,
) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        client_id=client_id,
        direction=direction,
        sender=sender,
        body=body,
        media_url=media_url,
        sent_at=datetime.utcnow(),
    )
    db.add(msg)
    db.commit()
    return msg
