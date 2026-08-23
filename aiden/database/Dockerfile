FROM python:3.13-slim

WORKDIR /app

# Copy database package into /app/database to preserve package structure
COPY ./aiden/database ./database

# Copy shared models
COPY ./shared/backend ./shared/backend

# Install dependencies
RUN pip install --no-cache-dir -r database/requirements.txt

# Set PYTHONPATH so Python can find the database package
ENV PYTHONPATH=/app

# Run the Flask application as a module
CMD ["python", "-m", "database"]
