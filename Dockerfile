# Use official Python runtime as a parent image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements file first to leverage caching
COPY backend/requirements.txt ./backend/requirements.txt

# Install dependencies
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy application source code explicitly
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Set the port the container will listen on
ENV PORT 8080

# Command to run the application using Gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:8080", "backend.app:app"]
