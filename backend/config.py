"""Pydantic Settings — credentials from .env file + environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # CTFd
    ctfd_url: str = "http://localhost:8000"
    ctfd_user: str = "admin"
    ctfd_pass: str = "admin"
    ctfd_token: str = ""

    # API Keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Provider-specific (optional, for Bedrock/Azure/Zen fallback)
    aws_region: str = "us-east-1"
    aws_bearer_token: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    opencode_zen_api_key: str = ""

    # Infra
    sandbox_image: str = "ctf-sandbox"
    max_concurrent_challenges: int = 10
    max_attempts_per_challenge: int = 3
    container_memory_limit: str = "16g"
    sandbox_network: str = ""
    allow_internet: bool = True
    max_tokens_per_challenge: int = 1_000_000
    challenge_timeout_seconds: int = 1_800
    solvers_per_swarm: int = 3
    max_solvers_per_swarm: int = 3
    evidence_db_path: str = "logs/evidence.sqlite3"
    blackboard_default_worker_lease_seconds: int = 300
    blackboard_intent_max_attempts: int = 3
    knowledge_db_path: str = "logs/knowledge.sqlite3"
    knowledge_enabled: bool = True
    knowledge_top_k: int = 5
    knowledge_max_chars: int = 8_000
    knowledge_query_timeout_ms: int = 200

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}
