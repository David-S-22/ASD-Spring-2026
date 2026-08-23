FROM python:3.13-slim
WORKDIR /app
EXPOSE 5004

# Copy backend package into /app/backend to preserve package structure
COPY . ./backend

# Install dependencies
RUN pip install --no-cache-dir -r backend/requirements.txt

# Run the Flask application as a module
CMD ["python" "-m" "backend"]
