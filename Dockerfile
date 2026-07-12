FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN mkdir -p storage/chroma storage/chunks storage/memoria

EXPOSE 8000

# Solo arranca la API. La ingesta se lanza con POST /api/v1/ingestar.
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
