import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey,
    Integer, String, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship
from database import Base


def _uuid():
    return str(uuid.uuid4())


class Client(Base):
    __tablename__ = "clients"

    id                         = Column(String, primary_key=True, default=_uuid)
    whatsapp_number            = Column(String(20), unique=True, index=True)
    full_name                  = Column(String(255))
    email                      = Column(String(255), unique=True, index=True)
    intake_completed           = Column(Boolean, default=False)
    intake_submitted_at        = Column(DateTime)
    intake_tally_submission_id = Column(String(255))
    total_appointments         = Column(Integer, default=0)
    last_appointment_at        = Column(DateTime)
    service_interest           = Column(String(100))
    # loyalist | seasonal | one_and_done | forgotten
    client_type                = Column(String(50))
    opted_out                  = Column(Boolean, default=False)
    opted_out_at               = Column(DateTime)
    notes                      = Column(Text)
    first_seen_at              = Column(DateTime, default=datetime.utcnow)
    last_seen_at               = Column(DateTime, default=datetime.utcnow)
    created_at                 = Column(DateTime, default=datetime.utcnow)
    updated_at                 = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversations    = relationship("Conversation", back_populates="client")
    messages         = relationship("Message", back_populates="client")
    photos           = relationship("ClientPhoto", back_populates="client")
    retention_events = relationship("RetentionEvent", back_populates="client")
    appointments     = relationship("Appointment", back_populates="client")


class Conversation(Base):
    __tablename__ = "conversations"

    id                      = Column(String, primary_key=True, default=_uuid)
    client_id               = Column(String, ForeignKey("clients.id"), index=True)
    channel                 = Column(String(50), default="whatsapp")
    # NEW | INTAKE_PENDING | ACTIVE | STYLE_MENU | BOOKING_SENT | HANDOFF | SILENT | RESUMED
    state                   = Column(String(50), default="NEW")
    handoff_trigger_message = Column(Text)
    started_at              = Column(DateTime, default=datetime.utcnow)
    last_message_at         = Column(DateTime, default=datetime.utcnow)
    updated_at              = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client   = relationship("Client", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", order_by="Message.sent_at")


class Message(Base):
    __tablename__ = "messages"

    id                 = Column(String, primary_key=True, default=_uuid)
    conversation_id    = Column(String, ForeignKey("conversations.id"), index=True)
    client_id          = Column(String, ForeignKey("clients.id"), index=True)
    # inbound | outbound
    direction          = Column(String(10))
    # client | bot | owner
    sender             = Column(String(50))
    body               = Column(Text)
    media_url          = Column(Text)
    twilio_message_sid = Column(String(100))
    sent_at            = Column(DateTime, default=datetime.utcnow)
    created_at         = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")
    client       = relationship("Client", back_populates="messages")


class ClientPhoto(Base):
    __tablename__ = "client_photos"

    id                   = Column(String, primary_key=True, default=_uuid)
    client_id            = Column(String, ForeignKey("clients.id"), index=True)
    url                  = Column(Text, nullable=False)
    twicpics_path        = Column(String(255))
    # twilio | twicpics
    storage_type         = Column(String(50), default="twilio")
    # before | after | inspiration | reference | unknown
    photo_type           = Column(String(50), default="unknown")
    conversation_context = Column(Text)
    sent_at              = Column(DateTime)
    created_at           = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="photos")


class RetentionEvent(Base):
    __tablename__ = "retention_events"

    id            = Column(String, primary_key=True, default=_uuid)
    client_id     = Column(String, ForeignKey("clients.id"), index=True)
    sequence_name = Column(String(100), nullable=False)
    step_number   = Column(Integer, nullable=False)
    # pending | sent | skipped | cancelled | responded
    status        = Column(String(50), default="pending")
    scheduled_for = Column(DateTime)
    sent_at       = Column(DateTime)
    created_at    = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("client_id", "sequence_name", "step_number", name="uq_retention"),
    )

    client = relationship("Client", back_populates="retention_events")


class Appointment(Base):
    __tablename__ = "appointments"

    id                     = Column(String, primary_key=True, default=_uuid)
    client_id              = Column(String, ForeignKey("clients.id"), index=True)
    glossgenius_booking_id = Column(String(255))
    service_type           = Column(String(255))
    appointment_at         = Column(DateTime)
    # scheduled | completed | cancelled | rescheduled
    status                 = Column(String(50), default="completed")
    notes                  = Column(Text)
    created_at             = Column(DateTime, default=datetime.utcnow)
    updated_at             = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client", back_populates="appointments")
