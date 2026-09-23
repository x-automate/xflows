FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY apps/workers/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY packages/xflows-engine/xflows_engine ./xflows_engine
COPY apps/workers/app ./app

CMD ["python", "-m", "app.worker"]
