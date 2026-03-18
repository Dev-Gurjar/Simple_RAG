"""Application configuration - loaded from environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """All app settings pulled from env vars / .env file."""

    # --- App ---
    APP_NAME: str = "Construction RAG Chatbot"
    DEBUG: bool = False
    API_VERSION: str = "v1"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # --- Auth / JWT ---
    JWT_SECRET: str = "CHANGE-ME-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # --- Supabase ---
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""  # service-role key (server-side)

    # --- Qdrant ---
    QDRANT_URL: str = ""
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION_PREFIX: str = "tenant"  # tenant_{id}

    # --- Cohere (Embeddings) ---
    COHERE_API_KEY: str = ""
    EMBEDDING_MODEL: str = "embed-english-v3.0"
    EMBEDDING_DIMS: int = 1024

    # --- Groq (LLM) ---
    GROQ_API_KEY: str = ""
    LLM_MODEL: str = "llama-3.3-70b-versatile"
    LLM_MAX_TOKENS: int = 2048
    LLM_TEMPERATURE: float = 0.3

    # --- Kaggle Docling ---
    DOCLING_URL: str = ""  # ngrok URL to Kaggle notebook
    DOCLING_API_KEY: str = ""
    DOCLING_VERIFY_SSL: bool = True

    # --- Chunking ---
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 64

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
