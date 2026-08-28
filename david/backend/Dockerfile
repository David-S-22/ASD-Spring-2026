FROM python:3.14

WORKDIR /app

COPY ./savings-service ./savings-service
# COPY ./prompts ./prompts
COPY requirements.txt ./requirements.txt

RUN pip install --no-cache-dir -r ./requirements.txt

EXPOSE 5002

CMD ["python", "-m", "savings-service.app"]
