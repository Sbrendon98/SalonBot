# SalonBot

A WhatsApp customer-service bot for a hair stylist (Stephanie), with Claude as
the conversational brain. Built to consolidate client messages, onboard new
clients through an intake flow, answer questions in her voice, route bookings
to GlossGenius, and run post-visit retention sequences — while always knowing
when to hand a human back to the human.

**Status: pre-pivot.** v1 (below) is a working Twilio-based design. The plan
now is a near-complete overhaul onto **ManyChat** as the channel and flow
layer, keeping Claude as the brain. See *The ManyChat pivot*.

---

## What v1 is (the working system)

### Stack
FastAPI + SQLAlchemy (Postgres) + Anthropic Claude (`claude-sonnet-4-6`).
WhatsApp via **Twilio**; intake via **Tally** webhooks; photos via TwicPics
(config) — note `.env.example` still mentions Cloudinary, one of several
small inconsistencies to clean up. ngrok for local webhook dev.

### Components
| Piece | File | Job |
|---|---|---|
| App + lifecycle | `main.py` | FastAPI app, `/health`, mounts both webhook routers, runs the retention worker (checks due follow-ups every 5 min) |
| Webhooks | `routers/twilio_webhook.py`, `routers/tally_webhook.py` | Inbound WhatsApp messages; Tally intake-form submissions |
| Conversation engine | `services/conversation.py` | The state machine + all routing logic |
| Claude client | `services/claude_ai.py` | 20-message history window, system prompt, `[HANDOFF]` / `[BOOKING_READY]` control tokens, graceful fallback message on API error |
| Identity | `services/identity.py` | Phone normalization, client resolution for owner commands |
| Notifications | `services/notifications.py` | Alerts the owner (handoffs, new intakes) |
| Photos | `services/photos.py` | Client photo records (inspiration pics etc.) |
| Prompts | `prompts/system_prompt.py` | The persona/voice, parameterized by owner name |
| Data | `models.py`, `database.py` | Postgres schema below |

### Data model
- **Client** — WhatsApp number, email, intake state, `client_type`
  (`loyalist | seasonal | one_and_done | forgotten`), opt-out tracking, notes,
  appointment counters. This is the CRM heart and survives any channel pivot.
- **Conversation** — per-client state machine: `NEW → INTAKE_PENDING →
  ACTIVE → STYLE_MENU → BOOKING_SENT`.
- **Message** — full inbound/outbound history (feeds Claude's context window).
- **RetentionEvent** — scheduled post-visit follow-ups.
- **Appointment**, **ClientPhoto**.

### Behavior worth keeping (the real product logic)
- **Opt-out compliance**: STOP/unsubscribe keywords cancel everything, immediately.
- **Human handoff**: complaint/refund/"speak to Stephanie" keywords (or Claude's
  `[HANDOFF]` token) notify the owner and pause the bot for that client.
- **Owner commands** over WhatsApp: `!pause`, `!resume`, `!status`, `!appt done`
  (logs a visit → schedules the retention sequence), `!optout`, `!optin`,
  `!note <name> | <text>`, `!who`, `!help`.
- **Intake flow**: new client → Tally form → webhook marks intake complete →
  conversation unlocks.
- **Booking intent**: keywords or Claude's `[BOOKING_READY]` → GlossGenius link.
- **Retention**: post-visit sequences fire from the background worker.

### Known gaps / rough edges in v1
- Twilio WhatsApp: per-message costs, business approval, template-message
  friction, and Stephanie can't touch anything without a deploy.
- TwicPics vs Cloudinary inconsistency (config vs `.env.example`).
- No tests; state machine covered by manual testing only.
- Retention templates live in code — the owner should own that copy.

---

## The ManyChat pivot (the overhaul)

**Why:** ManyChat now has a native WhatsApp channel (no Twilio costs or
approval dance), visual flows Stephanie can edit herself, and — the key
enabler — an **External Request** block that calls our backend mid-flow, plus
a dev API (custom fields, tags, send-message) for the backend to drive back.

**What stays (the assets):**
- Claude brain (`services/claude_ai.py`) + the system prompt/persona.
- The Client/Conversation/Message model — ManyChat custom fields are flat and
  per-channel; real client history stays in our Postgres.
- The behavior rules above (opt-out, handoff, owner commands, retention
  templates) — re-homed, not deleted.

**What gets replaced:**
- `routers/twilio_webhook.py` → ManyChat External Request endpoints
  (`POST /manychat/reply` — receives contact id + message text + flow
  context, returns JSON `{messages, actions, field_updates}`).
- Twilio config/signature validation, ngrok dev loop → ManyChat sandbox.
- Keyword state machine → ManyChat flows for the structural paths
  (intake, booking menu, opt-out), with Claude handling open conversation.

**What's new:**
- A small ManyChat API client (field sync, tags, send).
- Flow map: which states live in ManyChat vs which delegate to the brain.
- Owner commands: either stay via a lightweight webhook channel or move into
  a ManyChat admin flow.

**Target shape:** ManyChat owns channel + compliance + scaffolding; our
FastAPI shrinks to a focused "brain + memory" service: Claude, client
history, retention scheduler (or ManyChat sequences — decide on the Mac),
and the owner-command surface.

### Open decisions for the Mac session
1. Retention sequences: keep our 5-min worker + ManyChat send API, or rebuild
   as native ManyChat sequences?
2. How much of the state machine becomes flows vs stays in code?
3. Tally intake: keep the Tally webhook, or rebuild intake as a ManyChat flow?
4. Photo handling: does it survive the pivot at all in v2.0?
5. Secrets/env naming for the new stack (`.env.example` rewrite).

---

## Dev setup

```bash
python -m venv venv && source venv/bin/activate
pip install fastapi uvicorn sqlalchemy psycopg2-binary pydantic-settings anthropic
cp .env.example .env   # fill in; .env is gitignored, never commit it
uvicorn main:app --reload
```

`.gitignore` already covers `.env`, venvs, `__pycache__`, ngrok artifacts.
Current tree runs as-is on v1 once Twilio + Postgres creds exist.

*Recap written 2026-08-02 ahead of the ManyChat overhaul on the Mac.*
