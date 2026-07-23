from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from gtts import gTTS
from gtts.tts import gTTSError
from pydantic import BaseModel, Field
from supabase import Client, create_client

from translator import records, translator


# ==================================================
# 1. 기본 경로 및 환경변수
# ==================================================

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TTS_DIR = STATIC_DIR / "tts"

STATIC_DIR.mkdir(parents=True, exist_ok=True)
TTS_DIR.mkdir(parents=True, exist_ok=True)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv(
    "SUPABASE_SERVICE_ROLE_KEY",
    "",
)

PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    "https://grandtalk-api.onrender.com",
).rstrip("/")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "SUPABASE_URL과 "
        "SUPABASE_SERVICE_ROLE_KEY를 설정해야 함."
    )


# ==================================================
# 2. Supabase 및 FastAPI 초기화
# ==================================================

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
)

app = FastAPI(
    title="GrandTalk API",
    version="1.1.0",
)

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)

origins = [
    value.strip()
    for value in os.getenv(
        "ALLOWED_ORIGINS",
        "*",
    ).split(",")
    if value.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================================================
# 3. 요청 모델
# ==================================================

class TranslationRequest(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=500,
    )

    sender_id: str = Field(
        min_length=1,
        max_length=100,
    )

    receiver_id: str = Field(
        min_length=1,
        max_length=100,
    )

    use_llm: bool | None = None


class MessageCreateRequest(TranslationRequest):
    corrected_text: str | None = Field(
        default=None,
        max_length=1000,
    )


class ReadRequest(BaseModel):
    message_id: str


# ==================================================
# 4. 감정·의도 데이터 정리 함수
# ==================================================

def normalize_text_list(value: Any) -> list[str]:
    """
    Supabase JSONB가 list, 문자열, None 등으로
    반환되는 경우를 모두 list[str]로 정리한다.
    """

    if value is None:
        return []

    if isinstance(value, str):
        stripped = value.strip()

        if not stripped:
            return []

        return [stripped]

    if isinstance(value, (list, tuple, set)):
        result: list[str] = []

        for item in value:
            text = str(item).strip()

            if text and text not in result:
                result.append(text)

        return result

    text = str(value).strip()

    return [text] if text else []


def join_text_list(value: Any) -> str:
    """
    감정·의도 배열을 TTS와 ESP32에서 읽기 쉬운
    하나의 문자열로 합친다.
    """

    values = normalize_text_list(value)

    return ", ".join(values)


def build_audio_url(message_id: str) -> str:
    return (
        f"{PUBLIC_BASE_URL}"
        f"/messages/{message_id}/audio"
    )


def normalize_message(
    message: dict[str, Any],
) -> dict[str, Any]:
    """
    DB의 emotions/intents 배열과 함께
    ESP32가 쉽게 읽을 단수형 emotion/intent도 반환한다.
    """

    normalized = dict(message)

    emotions = normalize_text_list(
        normalized.get("emotions")
        or normalized.get("emotion")
    )

    intents = normalize_text_list(
        normalized.get("intents")
        or normalized.get("intent")
    )

    normalized["emotions"] = emotions
    normalized["intents"] = intents

    # ESP32용 단수형 문자열 필드
    normalized["emotion"] = ", ".join(emotions)
    normalized["intent"] = ", ".join(intents)

    message_id = str(
        normalized.get("message_id", "")
    ).strip()

    if message_id:
        normalized["audio_url"] = build_audio_url(
            message_id
        )

    return normalized


# ==================================================
# 5. TTS 문장 생성
# ==================================================

def build_spoken_text(
    message: dict[str, Any],
) -> str:
    translated_text = str(
        message.get("translated_text")
        or message.get("original_text")
        or ""
    ).strip()

    emotion_text = join_text_list(
        message.get("emotions")
        or message.get("emotion")
    )

    intent_text = join_text_list(
        message.get("intents")
        or message.get("intent")
    )

    parts: list[str] = []

    if translated_text:
        parts.append(translated_text)

    if emotion_text:
        parts.append(
            f"이 메시지에 담긴 감정은 "
            f"{emotion_text}입니다."
        )

    if intent_text:
        parts.append(
            f"이 메시지의 의도는 "
            f"{intent_text}입니다."
        )

    return " ".join(parts).strip()


def safe_filename(value: str) -> str:
    cleaned = re.sub(
        r"[^a-zA-Z0-9_-]",
        "_",
        value,
    )

    return cleaned[:100] or "message"


def create_tts_file(
    message: dict[str, Any],
) -> Path:
    message_id = str(
        message.get("message_id", "")
    ).strip()

    spoken_text = build_spoken_text(message)

    if not spoken_text:
        raise HTTPException(
            status_code=400,
            detail="TTS로 읽을 내용이 없음.",
        )

    text_hash = hashlib.sha256(
        spoken_text.encode("utf-8")
    ).hexdigest()[:12]

    filename = (
        f"{safe_filename(message_id)}"
        f"_{text_hash}.mp3"
    )

    output_path = TTS_DIR / filename

    # 같은 문장은 다시 생성하지 않고 캐시 사용
    if (
        output_path.exists()
        and output_path.stat().st_size > 0
    ):
        return output_path

    try:
        tts = gTTS(
            text=spoken_text,
            lang="ko",
            slow=False,
        )

        tts.save(str(output_path))

    except (gTTSError, OSError) as exc:
        if output_path.exists():
            output_path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=500,
            detail=f"TTS 생성 실패: {exc}",
        ) from exc

    if (
        not output_path.exists()
        or output_path.stat().st_size == 0
    ):
        raise HTTPException(
            status_code=500,
            detail="생성된 TTS 파일이 비어 있음.",
        )

    return output_path


# ==================================================
# 6. 메시지 조회 공통 함수
# ==================================================

def get_message_by_id(
    message_id: str,
) -> dict[str, Any]:
    try:
        response = (
            supabase.table("messages")
            .select("*")
            .eq("message_id", message_id)
            .limit(1)
            .execute()
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"메시지 조회 실패: {exc}",
        ) from exc

    rows = response.data or []

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="메시지를 찾을 수 없음.",
        )

    return rows[0]


# ==================================================
# 7. 기본 API
# ==================================================

@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "grandtalk-api",
        "status": "ok",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "dictionary_size": len(records),
    }


# ==================================================
# 8. 통역 API
# ==================================================

@app.post("/translate")
def translate(
    request: TranslationRequest,
) -> dict[str, Any]:
    result = translator.translate(
        request.text,
        use_llm=request.use_llm,
    )

    if not result["success"]:
        raise HTTPException(
            status_code=400,
            detail=result["message"],
        )

    return {
        "sender_id": request.sender_id,
        "receiver_id": request.receiver_id,
        **result,
    }


# ==================================================
# 9. 메시지 생성
# ==================================================

@app.post("/messages")
def create_message(
    request: MessageCreateRequest,
) -> dict[str, Any]:
    result = translator.translate(
        request.text,
        use_llm=request.use_llm,
    )

    if not result["success"]:
        raise HTTPException(
            status_code=400,
            detail=result["message"],
        )

    corrected = (
        request.corrected_text or ""
    ).strip()

    message_id = (
        f"msg_{uuid.uuid4().hex[:16]}"
    )

    emotions = normalize_text_list(
        result.get("emotions")
    )

    intents = normalize_text_list(
        result.get("intents")
    )

    message = {
        "message_id": message_id,
        "sender_id": request.sender_id,
        "receiver_id": request.receiver_id,
        "original_text": result["original"],
        "translated_raw": result[
            "translated_raw"
        ],
        "translated_text": (
            corrected
            or result["translated"]
        ),
        "detected_terms": result[
            "detected_terms"
        ],
        "emotions": emotions,
        "intents": intents,
        "warnings": result["warnings"],
        "audio_url": build_audio_url(
            message_id
        ),
        "is_read": False,
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "read_at": None,
    }

    try:
        response = (
            supabase.table("messages")
            .insert(message)
            .execute()
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"메시지 저장 실패: {exc}",
        ) from exc

    saved_message = (
        response.data[0]
        if response.data
        else message
    )

    return {
        "success": True,
        "message": normalize_message(
            saved_message
        ),
    }


# ==================================================
# 10. 읽지 않은 메시지 전체 조회
# ==================================================

@app.get("/devices/{receiver_id}/pending")
def pending(
    receiver_id: str,
) -> dict[str, Any]:
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
        raise HTTPException(
            status_code=500,
            detail=f"메시지 조회 실패: {exc}",
        ) from exc

    rows = response.data or []

    messages = [
        normalize_message(row)
        for row in rows
    ]

    return {
        "has_message": bool(messages),
        "message_count": len(messages),
        "messages": messages,
    }


# ==================================================
# 11. 다음 읽지 않은 메시지
# ==================================================

@app.get("/devices/{receiver_id}/next")
def next_message(
    receiver_id: str,
) -> dict[str, Any]:
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
        raise HTTPException(
            status_code=500,
            detail=f"메시지 조회 실패: {exc}",
        ) from exc

    rows = response.data or []

    message = (
        normalize_message(rows[0])
        if rows
        else None
    )

    return {
        "has_message": message is not None,
        "message": message,
    }


# ==================================================
# 12. 단일 메시지 조회
# ==================================================

@app.get("/messages/{message_id}")
def get_message(
    message_id: str,
) -> dict[str, Any]:
    message = get_message_by_id(
        message_id
    )

    return {
        "success": True,
        "message": normalize_message(
            message
        ),
    }


# ==================================================
# 13. 메시지 TTS MP3
# ==================================================

@app.get("/messages/{message_id}/audio")
def message_audio(
    message_id: str,
) -> FileResponse:
    message = get_message_by_id(
        message_id
    )

    output_path = create_tts_file(
        message
    )

    return FileResponse(
        path=output_path,
        media_type="audio/mpeg",
        filename=f"{message_id}.mp3",
        headers={
            "Cache-Control": (
                "public, max-age=3600"
            ),
        },
    )


# ==================================================
# 14. 읽음 처리
# ==================================================

@app.post("/messages/read")
def mark_read(
    request: ReadRequest,
) -> dict[str, Any]:
    read_at = datetime.now(
        timezone.utc
    ).isoformat()

    try:
        response = (
            supabase.table("messages")
            .update({
                "is_read": True,
                "read_at": read_at,
            })
            .eq(
                "message_id",
                request.message_id,
            )
            .execute()
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"읽음 처리 실패: {exc}",
        ) from exc

    if not response.data:
        raise HTTPException(
            status_code=404,
            detail="메시지를 찾을 수 없음.",
        )

    return {
        "success": True,
        "message_id": request.message_id,
        "is_read": True,
        "read_at": read_at,
    }