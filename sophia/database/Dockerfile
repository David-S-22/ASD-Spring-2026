# Bills database API (:6005) - thin SQLite CRUD layer. Build context is sophia/database/.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

RUN useradd --create-home appuser && mkdir -p /data && chown appuser:appuser /data
USER appuser

ENV PORT=6005
ENV DB_PATH=/data/bills.db
EXPOSE 6005

CMD ["python", "app.py"]
