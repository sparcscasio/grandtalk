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
# 1. 기본 경로
# ==================================================

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

STATIC_DIR = BASE_DIR / "static"
SYSTEM_AUDIO_DIR = STATIC_DIR / "system"
TTS_DIR = STATIC_DIR / "tts"

STATIC_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

SYSTEM_AUDIO_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

TTS_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ==================================================
# 2. 환경변수
# ==================================================

SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    "",
)

SUPABASE_SERVICE_ROLE_KEY = os.getenv(
    "SUPABASE_SERVICE_ROLE_KEY",
    "",
)

PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    "https://grandtalk-api.onrender.com",
).rstrip("/")

if (
    not SUPABASE_URL
    or not SUPABASE_SERVICE_ROLE_KEY
):
    raise RuntimeError(
        "SUPABASE_URL과 "
        "SUPABASE_SERVICE_ROLE_KEY를 설정해야 함."
    )


# ==================================================
# 3. 시스템 안내 음성
# ==================================================

SYSTEM_PROMPTS: dict[str, str] = {
    "tag_key.mp3": "키를 태그해 주세요.",
    "loading.mp3": "정보를 불러오는 중입니다.",
    "no_messages.mp3": (
        "조회된 메시지가 없습니다."
    ),
    "first_message.mp3": (
        "최초 메시지입니다."
    ),
    "last_message.mp3": (
        "마지막 메시지입니다."
    ),
    "network_error.mp3": (
        "서버 연결에 실패했습니다. "
        "잠시 후 다시 시도해 주세요."
    ),
}


def ensure_system_audio_files() -> None:
    """
    static/system 폴더에 안내 음성이 없으면
    서버 시작 시 자동으로 생성한다.

    파일을 Git에 포함했다면 생성 과정 없이
    기존 파일을 그대로 사용한다.
    """

    for filename, text in SYSTEM_PROMPTS.items():
        output_path = (
            SYSTEM_AUDIO_DIR / filename
        )

        if (
            output_path.exists()
            and output_path.stat().st_size > 0
        ):
            continue

        try:
            print(
                f"[system-audio] 생성: "
                f"{filename}"
            )

            temporary_path = (
                SYSTEM_AUDIO_DIR
                / f"{filename}.tmp"
            )

            tts = gTTS(
                text=text,
                lang="ko",
                slow=False,
            )

            tts.save(
                str(temporary_path)
            )

            temporary_path.replace(
                output_path
            )

        except Exception as exc:
            print(
                f"[system-audio] 생성 실패: "
                f"{filename}: {exc}"
            )


ensure_system_audio_files()


# ==================================================
# 4. Supabase 및 FastAPI
# ==================================================

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
)

app = FastAPI(
    title="GrandTalk API",
    version="1.2.0",
)

app.mount(
    "/static",
    StaticFiles(
        directory=str(STATIC_DIR)
    ),
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
# 5. 요청 모델
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


class MessageCreateRequest(
    TranslationRequest
):
    corrected_text: str | None = Field(
        default=None,
        max_length=1000,
    )


class ReadRequest(BaseModel):
    message_id: str


# ==================================================
# 6. 데이터 정규화
# ==================================================

def normalize_text_list(
    value: Any,
) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()

        if not text:
            return []

        return [text]

    if isinstance(
        value,
        (list, tuple, set),
    ):
        result: list[str] = []

        for item in value:
            text = str(item).strip()

            if (
                text
                and text not in result
            ):
                result.append(text)

        return result

    text = str(value).strip()

    if not text:
        return []

    return [text]


def join_text_list(
    value: Any,
) -> str:
    return ", ".join(
        normalize_text_list(value)
    )


def build_message_audio_url(
    message_id: str,
) -> str:
    return (
        f"{PUBLIC_BASE_URL}"
        f"/messages/{message_id}/audio"
    )


def normalize_message(
    message: dict[str, Any],
) -> dict[str, Any]:
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

    normalized["emotion"] = (
        ", ".join(emotions)
    )

    normalized["intent"] = (
        ", ".join(intents)
    )

    message_id = str(
        normalized.get(
            "message_id",
            "",
        )
    ).strip()

    if message_id:
        normalized["audio_url"] = (
            build_message_audio_url(
                message_id
            )
        )

    return normalized


# ==================================================
# 7. 메시지 조회 공통 함수
# ==================================================

def get_message_by_id(
    message_id: str,
) -> dict[str, Any]:
    try:
        response = (
            supabase.table("messages")
            .select("*")
            .eq(
                "message_id",
                message_id,
            )
            .limit(1)
            .execute()
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"메시지 조회 실패: {exc}"
            ),
        ) from exc

    rows = response.data or []

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                "메시지를 찾을 수 없음."
            ),
        )

    return rows[0]


# ==================================================
# 8. TTS 문장 생성
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
            "이 메시지에 담긴 감정은 "
            f"{emotion_text}입니다."
        )

    if intent_text:
        parts.append(
            "이 메시지의 의도는 "
            f"{intent_text}입니다."
        )

    return " ".join(parts).strip()


def safe_filename(
    value: str,
) -> str:
    cleaned = re.sub(
        r"[^a-zA-Z0-9_-]",
        "_",
        value,
    )

    return cleaned[:100] or "message"


def create_message_tts_file(
    message: dict[str, Any],
) -> Path:
    message_id = str(
        message.get(
            "message_id",
            "",
        )
    ).strip()

    spoken_text = build_spoken_text(
        message
    )

    if not spoken_text:
        raise HTTPException(
            status_code=400,
            detail=(
                "TTS로 읽을 내용이 없음."
            ),
        )

    text_hash = hashlib.sha256(
        spoken_text.encode("utf-8")
    ).hexdigest()[:12]

    filename = (
        f"{safe_filename(message_id)}"
        f"_{text_hash}.mp3"
    )

    output_path = (
        TTS_DIR / filename
    )

    if (
        output_path.exists()
        and output_path.stat().st_size > 0
    ):
        return output_path

    temporary_path = (
        TTS_DIR
        / f"{filename}.tmp"
    )

    try:
        tts = gTTS(
            text=spoken_text,
            lang="ko",
            slow=False,
        )

        tts.save(
            str(temporary_path)
        )

        temporary_path.replace(
            output_path
        )

    except (
        gTTSError,
        OSError,
    ) as exc:
        if temporary_path.exists():
            temporary_path.unlink(
                missing_ok=True
            )

        raise HTTPException(
            status_code=500,
            detail=(
                f"TTS 생성 실패: {exc}"
            ),
        ) from exc

    if (
        not output_path.exists()
        or output_path.stat().st_size == 0
    ):
        raise HTTPException(
            status_code=500,
            detail=(
                "생성된 TTS 파일이 비어 있음."
            ),
        )

    return output_path


# ==================================================
# 9. 읽음 처리 공통 함수
# ==================================================

def update_message_as_read(
    message_id: str,
) -> dict[str, Any]:
    """
    이미 읽은 메시지에 다시 요청해도
    오류 없이 읽음 상태를 반환하도록 한다.
    """

    message = get_message_by_id(
        message_id
    )

    if bool(message.get("is_read")):
        return {
            "success": True,
            "message_id": message_id,
            "is_read": True,
            "read_at": message.get(
                "read_at"
            ),
            "already_read": True,
        }

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
                message_id,
            )
            .execute()
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"읽음 처리 실패: {exc}"
            ),
        ) from exc

    if not response.data:
        raise HTTPException(
            status_code=404,
            detail=(
                "메시지를 찾을 수 없음."
            ),
        )

    return {
        "success": True,
        "message_id": message_id,
        "is_read": True,
        "read_at": read_at,
        "already_read": False,
    }


# ==================================================
# 10. 기본 API
# ==================================================

@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "grandtalk-api",
        "status": "ok",
        "version": "1.2.0",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    system_audio_status = {
        filename: (
            SYSTEM_AUDIO_DIR
            / filename
        ).exists()
        for filename
        in SYSTEM_PROMPTS
    }

    return {
        "status": "ok",
        "dictionary_size": len(records),
        "system_audio": (
            system_audio_status
        ),
    }


@app.get("/system-audio")
def system_audio_list() -> dict[str, Any]:
    return {
        "success": True,
        "audio": {
            filename: (
                f"{PUBLIC_BASE_URL}"
                f"/static/system/"
                f"{filename}"
            )
            for filename
            in SYSTEM_PROMPTS
        },
    }


# ==================================================
# 11. 통역
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
        "receiver_id": (
            request.receiver_id
        ),
        **result,
    }


# ==================================================
# 12. 메시지 생성
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

    translated_text = (
        corrected
        or str(
            result.get(
                "translated",
                "",
            )
        ).strip()
        or str(
            result.get(
                "translated_raw",
                "",
            )
        ).strip()
        or str(
            result.get(
                "original",
                request.text,
            )
        ).strip()
    )

    message = {
        "message_id": message_id,
        "sender_id": request.sender_id,
        "receiver_id": (
            request.receiver_id
        ),
        "original_text": result.get(
            "original",
            request.text,
        ),
        "translated_raw": result.get(
            "translated_raw",
            translated_text,
        ),
        "translated_text": (
            translated_text
        ),
        "detected_terms": result.get(
            "detected_terms",
            [],
        ),
        "emotions": emotions,
        "intents": intents,
        "warnings": result.get(
            "warnings",
            [],
        ),
        "audio_url": (
            build_message_audio_url(
                message_id
            )
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
            detail=(
                f"메시지 저장 실패: {exc}"
            ),
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
# 13. 읽지 않은 메시지 조회
# ==================================================

@app.get(
    "/devices/{receiver_id}/pending"
)
def pending(
    receiver_id: str,
) -> dict[str, Any]:
    try:
        response = (
            supabase.table("messages")
            .select("*")
            .eq(
                "receiver_id",
                receiver_id,
            )
            .eq(
                "is_read",
                False,
            )
            .order("created_at")
            .execute()
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"메시지 조회 실패: {exc}"
            ),
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


@app.get(
    "/devices/{receiver_id}/next"
)
def next_message(
    receiver_id: str,
) -> dict[str, Any]:
    try:
        response = (
            supabase.table("messages")
            .select("*")
            .eq(
                "receiver_id",
                receiver_id,
            )
            .eq(
                "is_read",
                False,
            )
            .order("created_at")
            .limit(1)
            .execute()
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"메시지 조회 실패: {exc}"
            ),
        ) from exc

    rows = response.data or []

    message = (
        normalize_message(rows[0])
        if rows
        else None
    )

    return {
        "has_message": (
            message is not None
        ),
        "message": message,
    }


# ==================================================
# 14. 단일 메시지 조회
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
# 15. 메시지 TTS
# ==================================================

@app.get(
    "/messages/{message_id}/audio"
)
def message_audio(
    message_id: str,
) -> FileResponse:
    message = get_message_by_id(
        message_id
    )

    output_path = (
        create_message_tts_file(
            message
        )
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
# 16. 읽음 처리
# ==================================================

@app.post("/messages/read")
def mark_read(
    request: ReadRequest,
) -> dict[str, Any]:
    return update_message_as_read(
        request.message_id
    )


@app.post(
    "/messages/{message_id}/read"
)
def mark_read_by_path(
    message_id: str,
) -> dict[str, Any]:
    """
    ESP32에서 JSON 본문 없이 간단하게
    호출하기 위한 읽음 처리 API.
    """

    return update_message_as_read(
        message_id
    )