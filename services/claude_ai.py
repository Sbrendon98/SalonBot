import logging
from anthropic import Anthropic
from config import settings
from prompts.system_prompt import get_system_prompt

logger = logging.getLogger(__name__)

_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

HISTORY_LIMIT = 20


def get_response(owner_name: str, conversation_history: list[dict]) -> str:
    """
    Send conversation history to Claude and return its response text.

    conversation_history: list of {"role": "user"|"assistant", "content": str}
    Returns the response text, which may start with [HANDOFF] or [BOOKING_READY].
    """
    try:
        response = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=get_system_prompt(owner_name),
            messages=conversation_history[-HISTORY_LIMIT:],
        )
        return response.content[0].text.strip()
    except Exception as exc:
        logger.error("Claude API error: %s", exc)
        return (
            f"I'm having a little trouble right now. "
            f"Please message {owner_name} directly and she'll be right with you."
        )


def build_history(messages) -> list[dict]:
    """Convert Message ORM objects to the format Claude expects."""
    history = []
    for msg in messages:
        if msg.direction == "inbound":
            history.append({"role": "user", "content": msg.body or ""})
        elif msg.direction == "outbound" and msg.sender == "bot":
            history.append({"role": "assistant", "content": msg.body or ""})
    return history
