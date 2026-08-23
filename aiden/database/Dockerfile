FROM python:3.13-slim

WORKDIR /app

# Copy database package into /app/database to preserve package structure
COPY . ./database

# Install dependencies
RUN pip install --no-cache-dir -r database/requirements.txt

# Run the Flask application as a module
CMD ["python", "-m", "database"]
