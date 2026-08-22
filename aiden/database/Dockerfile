FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files (except those in .dockerignore)
COPY . .

# Expose port 6004 - Flask application is available to wider internet
# To make it internal only (Kubernetes or Docker Compose internal network only):
# Change the app.run() call to: app.run(host='localhost', port=6004)
# Or in docker-compose.yml, remove the ports mapping and rely on service name resolution
EXPOSE 6004

# Run the Flask application
CMD ["python", "app.py"]
