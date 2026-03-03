from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    ollama_base_url: str
    ollama_api_key: str
    ollama_model: str
    llm_timeout_seconds: int = 120
    llm_max_retries: int = 3


settings = Settings()

if not settings.ollama_api_key:
    raise RuntimeError('OLLAMA_API_KEY is required for ai_observer_brain startup')
