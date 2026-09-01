"""Jarvis Papa web application."""

from fastapi import HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from jarvis_papa.routes import create_app
from jarvis_papa.voice import voice_service

app = create_app()


class VoicePreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=600)


@app.get("/api/voice/status")
def voice_status() -> dict[str, object]:
    return voice_service.status()


@app.get("/api/voice/events")
def voice_events(after: int = Query(default=0, ge=0)) -> dict[str, object]:
    return {"events": voice_service.events.after(after)}


@app.post("/api/voice/preview")
def voice_preview(request: VoicePreviewRequest) -> dict[str, object]:
    return voice_service.speak(request.text).to_dict()


@app.get("/api/voice/audio/{file_name}")
def voice_audio(file_name: str) -> FileResponse:
    path = voice_service.resolve_audio(file_name)
    if path is None:
        raise HTTPException(status_code=404, detail="Audio introuvable.")
    media_type = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"
    return FileResponse(path=path, media_type=media_type, filename=path.name)
