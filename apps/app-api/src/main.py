from fastapi import FastAPI

from src.config.settings import load_settings


def create_app() -> FastAPI:
    settings = load_settings()
    application = FastAPI(title="AI Call QA & Sales Coach API")
    application.state.settings = settings

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
