FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
# F-063: Multi-Arch-Index-Digest von python:3.13-slim (3.13.18-slim-trixie).
# Aufgeloest am 24.11.2026 via `docker buildx imagetools inspect python:3.13-slim`.

WORKDIR /app

# F-062: Reproduzierbare, hash-gepruefte Installation — identisch zum
# Haupt-Dockerfile. Build-Kontext ist das Repository-Root, damit die SSOT
# requirements.lock.txt erreichbar ist (wie bei Dockerfile:27-30).
COPY requirements.lock.txt .
RUN pip install --no-cache-dir --require-hashes --no-deps -r requirements.lock.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
