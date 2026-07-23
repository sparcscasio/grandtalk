from pathlib import Path

from gtts import gTTS


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "static" / "system"

SYSTEM_PROMPTS = {
    "tag_key.mp3": "키를 태그해 주세요.",
    "loading.mp3": "정보를 불러오는 중입니다.",
    "no_messages.mp3": "조회된 메시지가 없습니다.",
    "first_message.mp3": "최초 메시지입니다.",
    "last_message.mp3": "마지막 메시지입니다.",
    "network_error.mp3": (
        "서버 연결에 실패했습니다. "
        "잠시 후 다시 시도해 주세요."
    ),
}


def main() -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    for filename, text in SYSTEM_PROMPTS.items():
        output_path = OUTPUT_DIR / filename

        print(
            f"생성 중: {filename} -> {text}"
        )

        tts = gTTS(
            text=text,
            lang="ko",
            slow=False,
        )

        tts.save(str(output_path))

        print(
            f"생성 완료: {output_path}"
        )


if __name__ == "__main__":
    main()