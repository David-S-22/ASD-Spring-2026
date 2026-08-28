FROM python:3.14

WORKDIR /app

COPY ./david/backend/savings-service ./savings-service
COPY ./david/backend/prompts ./prompts
COPY ./david/backend/requirements.txt ./requirements.txt
COPY ./shared/backend ./shared/backend

RUN pip install --no-cache-dir -r ./requirements.txt

EXPOSE 5002

CMD ["python", "-m", "savings-service.app"]
