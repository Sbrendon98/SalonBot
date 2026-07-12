import re
from datetime import datetime
from sqlalchemy.orm import Session
from models import Client, Conversation


def normalize_phone(number: str) -> str:
    """Strip whatsapp: prefix and whitespace."""
    return number.replace("whatsapp:", "").strip()


def is_valid_email(text: str) -> bool:
    return bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text))


def extract_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    return match.group(0).lower() if match else text.strip().lower()


def extract_name(text: str) -> str:
    """Strip common conversational prefixes before a name."""
    text = text.strip()
    lower = text.lower()
    for prefix in ["my name is ", "i'm ", "im ", "it's ", "its ", "call me ", "this is "]:
        if lower.startswith(prefix):
            return text[len(prefix):].strip().title()
    return text.title()


def get_or_create_client(db: Session, whatsapp_number: str) -> Client:
    phone = normalize_phone(whatsapp_number)
    client = db.query(Client).filter_by(whatsapp_number=phone).first()
    if not client:
        client = Client(whatsapp_number=phone)
        db.add(client)
        db.commit()
        db.refresh(client)
    return client


def find_client_by_name(db: Session, name_query: str) -> Client | None:
    """Case-insensitive partial match. Returns first result."""
    pattern = f"%{name_query.strip()}%"
    return (
        db.query(Client)
        .filter(Client.full_name.ilike(pattern))
        .first()
    )


def find_client_by_phone(db: Session, phone: str) -> Client | None:
    return db.query(Client).filter_by(whatsapp_number=normalize_phone(phone)).first()


def resolve_command_target(db: Session, arg: str) -> Client | None:
    """Find a client from a command argument (name or +number)."""
    arg = arg.strip()
    if arg.startswith("+"):
        return find_client_by_phone(db, arg)
    return find_client_by_name(db, arg)


def get_or_create_conversation(db: Session, client_id: str) -> Conversation:
    conv = (
        db.query(Conversation)
        .filter_by(client_id=client_id)
        .order_by(Conversation.started_at.desc())
        .first()
    )
    if not conv:
        conv = Conversation(client_id=client_id, state="NEW")
        db.add(conv)
        db.commit()
        db.refresh(conv)
    return conv


def set_state(db: Session, conversation: Conversation, state: str) -> None:
    conversation.state = state
    conversation.updated_at = datetime.utcnow()
    db.commit()
