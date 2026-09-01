FROM python:3.13-slim

WORKDIR /app
EXPOSE 6001

COPY ./janelle/database ./database
COPY ./shared/backend ./shared/backend
COPY ./janelle/database/requirements.txt ./requirements.txt

RUN pip install --no-cache-dir -r ./requirements.txt

CMD ["python", "-m", "database"]
