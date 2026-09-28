from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # LLM
    ANTHROPIC_API_KEY: str = ""
    LLM_MODEL: str = "claude-sonnet-5"
    LLM_MODEL_FAST: str = "claude-haiku-4-5-20251001"
    LLM_MAX_TOKENS: int = 2000
    AGENT_MAX_STEPS: int = 6
    TOOL_OUTPUT_MAX_CHARS: int = 12000

    # Embeddings
    EMBED_PROVIDER: str = "local"
    EMBED_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBED_DIM: int = 384

    # Postgres / Redis
    DATABASE_URL: str = "postgresql://incident:incident@localhost:5432/incident"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Slack (Socket Mode)
    SLACK_BOT_TOKEN: str = ""
    SLACK_APP_TOKEN: str = ""
    SLACK_INCIDENT_CHANNEL: str = ""

    # API
    API_KEY: str = "change-me"
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # Adapters
    ADAPTER_MODE: str = "mock"
    MOCK_SCENARIO: str = "A_pool_exhaustion"
    PROMETHEUS_URL: str = ""
    LOKI_URL: str = ""
    GITHUB_TOKEN: str = ""

    # Retrieval tuning
    RETRIEVAL_TOP_K: int = 3
    RETRIEVAL_CANDIDATES: int = 20
    W_VEC: float = 0.35
    W_FTS: float = 0.15
    W_FP: float = 0.20
    W_SVC: float = 0.15
    W_CODE: float = 0.15
    DECAY_HALF_LIFE_DAYS: int = 365
    PATTERN_MIN_CLUSTER: int = 3
    PATTERN_DISTANCE_THRESHOLD: float = 0.25

    # Safety
    ALLOW_ACTIONS: bool = False


settings = Settings()
