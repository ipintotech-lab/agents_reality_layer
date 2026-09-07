from fastapi import FastAPI

from reality_layer import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="Reality Layer", version=__version__)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
