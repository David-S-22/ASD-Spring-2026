# Bills backend (:5005) - JSON API and HTMX fragments. Build context is sophia/backend/.
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir Flask==3.1.3 flask-cors==4.0.1 requests==2.34.2

COPY . ./sophia/backend/

ENV PYTHONPATH=/app

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

ENV PORT=5005
EXPOSE 5005

CMD ["python", "-m", "sophia.backend.app"]
