FROM python:3.13-slim
WORKDIR /app
EXPOSE 5006

COPY . ./backend

RUN pip install --no-cache-dir -r backend/requirements.txt

CMD ["python", "-m", "backend"]
