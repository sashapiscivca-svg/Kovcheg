from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Configuration settings for the FastAPI backend."""
    ARK_MODULES_PATH: str = "/app/data"
    API_PORT: int = 8000
    API_HOST: str = "0.0.0.0" 

settings = Settings()
