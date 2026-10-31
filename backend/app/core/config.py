from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    GEMINI_API_KEY: str
    GROQ_API_KEY: str
    SMTP_HOST: str
    SMTP_PORT: int = 587
    SMTP_USER: str
    SMTP_PASSWORD: str
    EMAIL_FROM: str

    ENVIRONMENT: str = "development"
    FRONTEND_BASE_URL: str = "http://localhost:5173"
    MAX_CONCURRENT_OCR_WORKERS: int = 2
    RATE_LIMIT_PASSWORD_RESET: int = 5
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    TRUSTED_PROXIES: list[str] = ["127.0.0.1", "::1"]

    # Multi-Tenancy & Vector Isolation
    DEFAULT_INSTITUTION_ID: str = "eduintel-pilot"
    ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE: bool = False

    # Authentication & Cookie Security (SEC-10)
    AUTH_COOKIE_NAME: str = "access_token"
    AUTH_COOKIE_SAMESITE: str = "strict"
    AUTH_COOKIE_SECURE: bool | None = None
    AUTH_COOKIE_PATH: str = "/"

    @field_validator("TRUSTED_PROXIES", mode="before")
    @classmethod
    def parse_trusted_proxies(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [ip.strip() for ip in v.split(",") if ip.strip()]
        if isinstance(v, list):
            return [str(ip).strip() for ip in v if str(ip).strip()]
        return ["127.0.0.1", "::1"]

    @field_validator("FRONTEND_BASE_URL")
    @classmethod
    def validate_frontend_url(cls, v: str, info) -> str:
        env = info.data.get("ENVIRONMENT", "development")
        if env == "production" and not v.startswith("https://"):
            raise ValueError(f"In production, FRONTEND_BASE_URL must use HTTPS: {v}")
        return v.rstrip("/")

    class Config:
        env_file = ".env"


settings = Settings()