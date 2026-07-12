from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Twilio
    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_WHATSAPP_NUMBER: str

    # Owner
    OWNER_WHATSAPP_NUMBER: str
    OWNER_NAME: str = "Stephanie"

    # Claude
    ANTHROPIC_API_KEY: str

    # Database
    DATABASE_URL: str

    # TwicPics
    TWICPICS_API_KEY: str = ""
    TWICPICS_DOMAIN: str = ""

    # External links (empty until ready)
    TALLY_FORM_URL: str = ""
    GLOSSGENIUS_BOOKING_URL: str = ""

    # Dev
    TWILIO_VALIDATE_SIGNATURE: bool = False

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
