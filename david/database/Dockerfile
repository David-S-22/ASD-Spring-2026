FROM python:3.14

WORKDIR /app

COPY . ./database

RUN pip install --no-cache-dir -r ./database/requirements.txt

EXPOSE 6002

CMD ["python", "-m", "database.app"]
