# sangsangseoga-python

메인 백엔드 서버(Spring Boot)가 호출하는 FastAPI 기반 AI 서버입니다. 사용자의 요청(장르, 독자 연령, 진행 방식 등)에 맞는 프롬프트를 조립해 Gemini에 전달하고, 동화/소설/시/에세이 텍스트 생성과 삽화 이미지 생성을 담당합니다.

## 주요 기능

- **텍스트 생성** (`/api/ai/generate`, `/api/ai/generate/stream`)
  - 동화 · 소설 · 시 · 에세이 장르별로 설정 수집, 페이지/장면 기획, 본문 작성, 다시쓰기, 번역 등 다양한 `taskType`을 지원합니다.
  - 요청의 `bookType`, `meta.readerAge`, `meta.interactionMode`, `taskType`에 따라 `prompts/` 아래의 프롬프트 조각들을 조합해 최종 프롬프트를 만듭니다.
  - 스트리밍 버전은 SSE(`text/event-stream`)로 `delta`/`done`/`error` 이벤트를 전송합니다.
- **이미지 생성** (`/api/ai/generate-image`)
  - Gemini 2.5 Flash Image(`gemini-2.5-flash-image`)로 삽화를 생성해 base64 데이터 URI(`imageBase64`)로 응답합니다. (과거 Replicate 기반 URL 방식에서 전환됨. `imageUrl`은 항상 `null`)
- **응답 신뢰성 보정**
  - AI 응답이 JSON이 아니거나 필수 필드가 빠져 있으면 `status: FAILED`로 보정
  - `status: SUCCESS`인데 `result`가 비어 있으면 `FAILED`로 강제 보정 (`NEED_MORE_INPUT`은 예외)
- **토큰 사용량 응답**
  - 모든 텍스트/이미지 생성 응답에 `usage` 필드로 입출력 토큰 수(또는 이미지 수)를 포함해 반환합니다. Spring Boot가 `ai_generation_usage` 테이블에 적재할 수 있도록 컬럼명에 맞춰 camelCase로 내려줍니다.
- **성능 계측**
  - 요청별로 프롬프트 조립, Gemini 호출, 파싱, 응답 빌드 구간의 소요시간을 `[AI-PERF]` 로그로 stdout과 `logs/ai_perf.log`에 기록합니다.
  - 요청 추적을 위해 `X-Request-ID` 헤더를 그대로 사용하거나 없으면 새로 발급합니다.

## 프로젝트 구조

```
app/
  main.py                     # FastAPI 앱, 라우터, 성능 계측 미들웨어
  schemas/
    image_request.py          # 이미지 생성 요청 Pydantic 모델
  services/
    prompt_builder.py         # 텍스트 생성용 프롬프트 조립
    image_prompt_builder.py   # 이미지 생성용 프롬프트 조립
    gemini_service.py         # Gemini 텍스트 생성 호출, 응답 검증/보정, 토큰 사용량 추출
    gemini_image_service.py   # Gemini 이미지 생성 호출
    replicate_service.py      # (레거시, 현재 미사용) Replicate 기반 이미지 생성
  utils/
    perf_logger.py            # [AI-PERF] 로그 유틸
prompts/
  common/                     # 모든 요청에 공통으로 들어가는 규칙(safety, JSON 형식 등)
  reader_age/                 # 독자 연령별 프롬프트
  genre/                      # 장르(동화/소설/시/에세이)별 프롬프트
  interaction_mode/           # 제작 방식(자유/혼합/선택형)별 프롬프트
  task/                       # taskType별 세부 지시문 (공통/동화/소설/시/에세이)
logs/
  ai_perf.log                 # 요청별 성능 계측 로그
```

## 요구 사항

- Python 3.10+ (venv `.venv` 사용)
- 의존성: `requirements.txt` 참고 (`fastapi`, `uvicorn[standard]`, `python-dotenv`, `google-genai`, `replicate`)

## 환경 변수 (`.env`)

| 변수 | 필수 여부 | 기본값 | 설명 |
|---|---|---|---|
| `GEMINI_API_KEY` | 필수 | - | 없으면 서버 기동 시 즉시 실패 |
| `GEMINI_MODEL` | 선택 | `gemini-2.5-flash` | 텍스트 생성 모델 |
| `GEMINI_IMAGE_MODEL` | 선택 | `gemini-2.5-flash-image` | 이미지 생성 모델 |
| `REPLICATE_API_TOKEN` | 미사용 | - | 레거시 코드에서만 참조, 현재 이미지 생성 경로에서는 사용되지 않음 |
| `CORS_ALLOWED_ORIGINS` | 선택 | `http://localhost:5173` | 허용할 프론트엔드 오리진. 콤마로 여러 개 지정 가능(예: `https://app.example.com,https://www.example.com`) |

## 실행 방법

```bash
# 1. 가상환경 생성 및 활성화
python -m venv .venv
.venv\Scripts\activate        # Windows

# 2. 의존성 설치
pip install -r requirements.txt

# 3. .env 파일 생성 (위 환경 변수 참고)

# 4. 개발 서버 실행
uvicorn app.main:app --reload
```

기본적으로 `http://127.0.0.1:8000`에서 실행되며, CORS는 기본값으로 `http://localhost:5173`(프론트엔드 dev 서버)만 허용합니다(`CORS_ALLOWED_ORIGINS`로 변경 가능).

## Docker로 실행

```bash
docker build -t sangsangseoga-python .
docker run -p 8000:8000 --env-file .env sangsangseoga-python
```

non-root 계정으로 실행되며, `uvicorn`이 `--host 0.0.0.0`으로 바인딩되어 있어 다른 컨테이너(Spring Boot backend 등)에서도 접근 가능합니다. `be` 저장소의 `docker-compose.prod.yml`이 이 리포를 `../sangsangseoga-python` 상대 경로로 빌드해서 backend/redis와 함께 띄우는 구조입니다.

## CI/CD

- `.github/workflows/ci.yml`: `main` push/PR 시 의존성 설치, 문법 검증(`compileall`), Docker 빌드 검증을 수행합니다.
- `.github/workflows/cd.yml`: 위 CI가 성공한 커밋에 한해서만 EC2에 SSH로 접속해 자동 재배포합니다(`workflow_run` 트리거). CI가 실패하면 배포되지 않습니다.

## API 개요

### `GET /health`
인프라(`docker-compose` healthcheck 등)에서 사용하는 상태 확인용 엔드포인트. `{"status": "ok"}`를 반환합니다.

### `POST /api/ai/generate`
텍스트 생성 요청(dict body: `taskType`, `draft` 등)을 받아 검증된 envelope(`status`, `taskType`, `message`, `result`, `missingFields`, `warnings`, `nextAction`, `usage`)를 반환합니다.

### `POST /api/ai/generate/stream`
동일한 요청을 SSE로 스트리밍합니다. `delta` 이벤트로 원문 조각을, 마지막에 `done`(envelope) 또는 `error` 이벤트를 전송합니다.

### `POST /api/ai/generate-image`
`promptText`, `imageType`, `style`, `aspectRatio`, `bookType` 등을 받아 삽화를 생성하고 `{ success, message, imageUrl: null, imageBase64, usage }`를 반환합니다.

## 참고

- `app/services/replicate_service.py`는 현재 사용되지 않는 레거시 코드입니다(이미지 생성이 Gemini 2.5 Flash Image로 전환됨).
- `logs/ai_perf.log`와 uvicorn 콘솔 로그를 통해 요청별 처리 시간과 실제 요청/응답 내용을 확인할 수 있습니다.
