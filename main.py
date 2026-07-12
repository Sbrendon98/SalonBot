import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from database import create_tables, SessionLocal
from routers import twilio_webhook, tally_webhook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def _retention_worker() -> None:
    """Check for due retention messages every 5 minutes."""
    from services.conversation import process_due_retention_messages
    while True:
        try:
            await asyncio.sleep(300)
            loop = asyncio.get_event_loop()
            db = SessionLocal()
            try:
                await loop.run_in_executor(None, process_due_retention_messages, db)
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Retention worker error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    logger.info("Database tables ready.")
    task = asyncio.create_task(_retention_worker())
    logger.info("Retention worker started.")
    yield
    task.cancel()
    logger.info("Retention worker stopped.")


app = FastAPI(title="SalonBot", lifespan=lifespan)

app.include_router(twilio_webhook.router)
app.include_router(tally_webhook.router)


@app.get("/health")
def health():
    return {"status": "ok"}
