import uvicorn

from jarvis_papa.config import settings


def run() -> None:
    """Start Jarvis on the local machine only by default."""

    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    uvicorn.run(
        "jarvis_papa.app:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    run()
