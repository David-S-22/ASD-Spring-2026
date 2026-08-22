# Bills backend (:5005) - JSON API and HTMX fragments. Build context is sophia/backend/.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./sophia/backend/

ENV PYTHONPATH=/app

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

ENV PORT=5005
EXPOSE 5005

CMD ["python", "-m", "sophia.backend.app"]
