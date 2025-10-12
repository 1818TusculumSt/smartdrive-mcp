# SmartDrive MCP - Dockerfile
# Isolated environment for OneDrive indexing with zero system pollution

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for image processing
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY onedrive_crawler.py .
COPY embeddings.py .
COPY config.py .
COPY smartdrive_server.py .
COPY document_intelligence.py .
COPY document_storage.py .

# Create directories for cache files
RUN mkdir -p /root/.cache

# Expose MCP server port (if needed)
EXPOSE 8080

# Default command: run the crawler interactively
CMD ["python", "onedrive_crawler.py"]
