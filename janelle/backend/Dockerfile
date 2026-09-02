FROM python:3.13-slim

WORKDIR /app
EXPOSE 5001

COPY janelle/backend ./backend

RUN pip install --no-cache-dir -r backend/requirements.txt

CMD ["python", "-m", "backend"]
