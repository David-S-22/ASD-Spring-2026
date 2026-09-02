FROM python:3.13-slim
WORKDIR /app
EXPOSE 6006

COPY . ./database

RUN pip install --no-cache-dir -r database/requirements.txt

CMD ["python", "-m", "database"]
