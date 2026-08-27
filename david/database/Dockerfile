FROM python:3.14

WORKDIR /app

COPY . ./database
COPY requirements.txt ./requirements.txt

RUN pip install --no-cache-dir -r ./requirements.txt

EXPOSE 6002

CMD ["python", "-m", "database.app"]
