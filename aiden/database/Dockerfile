FROM python:3.13-slim

WORKDIR /app

# Copy all application files (except those in .dockerignore)
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the Flask application
CMD ["python", "app.py"]
