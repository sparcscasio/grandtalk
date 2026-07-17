# GrandTalk — 손주 말투 통역기

구성:
- `backend/`: FastAPI + Kiwi + 선택적 OpenAI LLM 후처리
- `docs/`: GitHub Pages용 PWA
- `supabase/schema.sql`: 메시지 테이블
- `esp32/grandtalk_esp32.ino`: ESP32 폴링 클라이언트

## 1. Supabase
1. 새 프로젝트 생성
2. SQL Editor에서 `supabase/schema.sql` 실행
3. Project URL과 `service_role` 키 확인

## 2. 로컬 백엔드
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# .env 값 입력
uvicorn main:app --reload
```
- 상태: `http://127.0.0.1:8000/health`
- Swagger: `http://127.0.0.1:8000/docs`

## 3. Render 배포
저장소를 GitHub에 올린 뒤 Render에서 Blueprint 또는 Web Service로 배포함.
- Root directory: `backend`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- 환경변수: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ALLOWED_ORIGINS`
- LLM 사용 시: `USE_LLM=true`, `OPENAI_API_KEY`, `OPENAI_MODEL`

## 4. PWA
`docs/config.js`의 API 주소를 Render URL로 수정함.
GitHub 저장소 Settings → Pages → main branch → `/docs`로 배포함.
그 뒤 Render의 `ALLOWED_ORIGINS`를 GitHub Pages 주소로 제한함.

## 5. ESP32
Arduino IDE에서 다음 라이브러리를 설치함.
- ArduinoJson
- ESP32 보드 패키지

`esp32/grandtalk_esp32.ino`의 Wi-Fi, API URL, 수신자 ID를 수정한 뒤 업로드함.

## 주의
- `SUPABASE_SERVICE_ROLE_KEY`와 `OPENAI_API_KEY`는 프론트엔드나 ESP32에 넣지 않음.
- Render 무료 서버는 유휴 상태에서 잠들 수 있어 첫 요청이 느릴 수 있음.
- LLM API는 무료 배포와 별개로 사용료가 발생할 수 있음.
