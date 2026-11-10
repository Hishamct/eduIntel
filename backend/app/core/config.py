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
    DEFAULT_PILOT_INSTITUTION_UUID: str = "00000000-0000-0000-0000-000000000001"
    DEFAULT_PILOT_INSTITUTION_SLUG: str = "eduintel-pilot"
    DEFAULT_INSTITUTION_ID: str = "00000000-0000-0000-0000-000000000001"
    ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE: bool = False

    # Database Connection Pool Settings (ADR-0002)
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800  # 30 minutes
    DB_POOL_PRE_PING: bool = True
    DB_ECHO: bool = False

    # Disaster Recovery & Quiescence (ADR-0009)
    MAINTENANCE_FLAG_PATH: str = "/tmp/eduintel_maintenance.flag"  # nosec B108

    # Authentication & Cookie Security (SEC-10)
    AUTH_COOKIE_NAME: str = "access_token"
    AUTH_COOKIE_SAMESITE: str = "strict"
    AUTH_COOKIE_SECURE: bool | None = None
    AUTH_COOKIE_PATH: str = "/"

    # Dynamic AI Configuration Settings (Phase 5 Step 1)
    GEMINI_MODEL: str = "gemini-1.5-flash"
    GROQ_FALLBACK_MODEL: str = "openai/gpt-oss-120b"
    LLM_REQUEST_TIMEOUT_SECONDS: int = 25
    LLM_MAX_RETRIES: int = 2
    LLM_RETRY_BACKOFF_FACTOR: float = 1.5

    # Dynamic Pricing Versioning Matrix (INR per 1k tokens)
    AI_PRICING_VERSION: str = "2026-11-v1"
    GEMINI_INPUT_COST_PER_1K_INR: float = 0.0066
    GEMINI_OUTPUT_COST_PER_1K_INR: float = 0.0264
    GROQ_INPUT_COST_PER_1K_INR: float = 0.0040
    GROQ_OUTPUT_COST_PER_1K_INR: float = 0.0080

    # Stakeholder-Configurable Business Limits
    INSTITUTION_MAX_DAILY_FINANCIAL_EXPOSURE_INR: float = 500.00
    PENDING_RISK_RESERVE_CAP_PERCENT: float = 0.20

    # Stage 7.3 Tenant Quota Engine Integration Flag
    ENABLE_TENANT_AI_QUOTAS: bool = False
    # Explicit restricted dev/test bypass ONLY - strictly forbidden in production
    ALLOW_UNMETERED_AI_TEST_BYPASS: bool = False

    # Streaming Resource Limits
    MAX_STREAMING_OUTPUT_TOKENS: int = 2048
    MAX_STREAMING_STAGED_BYTES: int = 65536  # 64 KB
    MAX_CONCURRENT_STREAMS_PER_INSTITUTION: int = 10
    STREAMING_LOOKAHEAD_CHARS: int = 384
    GUARDRAIL_TIMEOUT_MS: int = 150

    # Agent Durable Session & Concurrency Limits
    AGENT_GENERATION_LEASE_SECONDS: int = 60
    USE_IN_MEMORY_SESSION_STORE: bool = False

    # ML Model Verification & Drift Monitoring (Phase 5 Step 3.6 Stage 6 & 6R)
    ML_MODEL_SIGNING_PUBLIC_KEY_PATH: str = "app/ml/models/model_signing_public_key.pem"
    ML_MODEL_SIGNING_PUBLIC_KEY: str | None = None
    ML_MODEL_SIGNING_KEY_ID: str = "eduintel-ml-signer-2026-v1"
    ML_MODEL_TRUSTED_KEY_FINGERPRINTS: list[str] = [
        "3aa4fa48c199f6c741b8f5adade778519453b6bf36acebfd7f57ba958db3e634",
    ]
    ML_MODEL_TRUST_DEV_KEYS: bool = True
    ML_FEATURE_DRIFT_MIN_SAMPLE_SIZE: int = 200
    ML_FEATURE_DRIFT_WARNING_THRESHOLD: float = 0.10
    ML_FEATURE_DRIFT_HIGH_THRESHOLD: float = 0.25

    @field_validator("ML_MODEL_TRUSTED_KEY_FINGERPRINTS", mode="before")
    @classmethod
    def parse_trusted_fingerprints(cls, v: object) -> list[str]:
        if isinstance(v, str):
            fps = [fp.strip().lower() for fp in v.split(",") if fp.strip()]
        elif isinstance(v, list):
            fps = [str(fp).strip().lower() for fp in v if str(fp).strip()]
        else:
            return []
        for fp in fps:
            if len(fp) != 64 or not all(c in "0123456789abcdef" for c in fp):
                raise ValueError(
                    f"Malformed trusted key fingerprint: '{fp}'. Expected 64-character lowercase SHA-256 hex digest."
                )
        return fps

    @field_validator("ML_MODEL_TRUSTED_KEY_FINGERPRINTS")
    @classmethod
    def validate_production_fingerprints(cls, v: list[str], info) -> list[str]:
        env = info.data.get("ENVIRONMENT", "development")
        if env == "production" and not v:
            raise ValueError(
                "In production, ML_MODEL_TRUSTED_KEY_FINGERPRINTS must be explicitly configured and non-empty."
            )
        return v

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

    @field_validator("ALLOW_UNMETERED_AI_TEST_BYPASS")
    @classmethod
    def validate_unmetered_bypass(cls, v: bool, info) -> bool:
        env = info.data.get("ENVIRONMENT", "development")
        if env == "production" and v:
            raise ValueError("In production, ALLOW_UNMETERED_AI_TEST_BYPASS is strictly forbidden.")
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    class Config:
        env_file = ".env"


settings = Settings()
