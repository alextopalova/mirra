from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    youcam_api_key: str = ""
    youcam_api_secret: str = ""
    allowed_origin: str = "http://localhost:5173"
    use_mocks: bool = True

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
