# Use official Python runtime as a parent image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements file first to leverage caching
COPY backend/requirements.txt ./backend/requirements.txt

# Install dependencies
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy the rest of the project files
COPY . .

# Set the port the container will listen on
ENV PORT 8080

# Command to run the application
CMD ["gunicorn", "-b", ":$PORT", "backend.app:app"]
CMD ["sh", "-c", "gunicorn -b :$PORT backend.app:app"]
