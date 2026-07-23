from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import Client, create_client
from fastapi.staticfiles import StaticFiles

from translator import records, translator

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("SUPABASE_URL과 SUPABASE_SERVICE_ROLE_KEY를 설정해야 함.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
app = FastAPI(title="GrandTalk API", version="1.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")

origins = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TranslationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    sender_id: str = Field(min_length=1, max_length=100)
    receiver_id: str = Field(min_length=1, max_length=100)
    use_llm: bool | None = None


class MessageCreateRequest(TranslationRequest):
    corrected_text: str | None = Field(default=None, max_length=1000)


class ReadRequest(BaseModel):
    message_id: str


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "grandtalk-api", "status": "ok"}


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "dictionary_size": len(records)}


@app.post("/translate")
def translate(request: TranslationRequest) -> dict[str, Any]:
    result = translator.translate(request.text, use_llm=request.use_llm)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return {"sender_id": request.sender_id, "receiver_id": request.receiver_id, **result}


@app.post("/messages")
def create_message(request: MessageCreateRequest) -> dict[str, Any]:
    result = translator.translate(request.text, use_llm=request.use_llm)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    corrected = (request.corrected_text or "").strip()
    message = {
        "message_id": f"msg_{uuid.uuid4().hex[:16]}",
        "sender_id": request.sender_id,
        "receiver_id": request.receiver_id,
        "original_text": result["original"],
        "translated_raw": result["translated_raw"],
        "translated_text": corrected or result["translated"],
        "detected_terms": result["detected_terms"],
        "emotions": result["emotions"],
        "intents": result["intents"],
        "warnings": result["warnings"],
        "audio_url": None,
        "is_read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "read_at": None,
    }
    try:
        response = supabase.table("messages").insert(message).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"메시지 저장 실패: {exc}") from exc
    return {"success": True, "message": response.data[0]}


@app.get("/devices/{receiver_id}/pending")
def pending(receiver_id: str) -> dict[str, Any]:
    try:
        response = (
            supabase.table("messages")
            .select("*")
            .eq("receiver_id", receiver_id)
            .eq("is_read", False)
            .order("created_at")
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"메시지 조회 실패: {exc}") from exc
    messages = response.data or []
    return {"has_message": bool(messages), "message_count": len(messages), "messages": messages}


@app.get("/devices/{receiver_id}/next")
def next_message(receiver_id: str) -> dict[str, Any]:
    try:
        response = (
            supabase.table("messages")
            .select("*")
            .eq("receiver_id", receiver_id)
            .eq("is_read", False)
            .order("created_at")
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"메시지 조회 실패: {exc}") from exc
    messages = response.data or []
    return {"has_message": bool(messages), "message": messages[0] if messages else None}


@app.post("/messages/read")
def mark_read(request: ReadRequest) -> dict[str, Any]:
    read_at = datetime.now(timezone.utc).isoformat()
    try:
        response = (
            supabase.table("messages")
            .update({"is_read": True, "read_at": read_at})
            .eq("message_id", request.message_id)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"읽음 처리 실패: {exc}") from exc
    if not response.data:
        raise HTTPException(status_code=404, detail="메시지를 찾을 수 없음.")
    return {"success": True, "message_id": request.message_id, "is_read": True, "read_at": read_at}
