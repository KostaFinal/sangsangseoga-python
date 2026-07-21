# Spring Boot backend와 같은 EC2에서 컨테이너로 뜨는 FastAPI AI 서버.
FROM python:3.11-slim
WORKDIR /app

# 의존성 레이어를 소스보다 먼저 캐싱해서 소스만 바뀐 재빌드 시 pip install을 반복하지 않게 한다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY prompts ./prompts

RUN groupadd -r app && useradd -r -g app app \
    && mkdir -p logs \
    && chown -R app:app /app
USER app

EXPOSE 8000

# --host 0.0.0.0을 명시하지 않으면 uvicorn 기본값(127.0.0.1)에 바인딩되어
# 같은 도커 네트워크의 backend 컨테이너에서 접근할 수 없다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
