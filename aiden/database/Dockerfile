FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files (except those in .dockerignore)
COPY . .

# Run the Flask application
CMD ["python", "app.py"]
