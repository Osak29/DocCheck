"""
Configuration centralisee de l'application, chargee depuis les variables
d'environnement (ou un fichier .env a la racine du projet).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./doccheck.db"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    alerte_j_moins: int = 30

    api_base_url: str = "http://localhost:8000"


settings = Settings()
