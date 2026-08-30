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
COPY delta_sync.py .
COPY indexing_core.py .
COPY document_intelligence.py .
COPY document_storage.py .

# Create directories for cache files
RUN mkdir -p /root/.cache

# Streamable HTTP MCP port
EXPOSE 8000

# Default command: run the MCP server (Streamable HTTP on 127.0.0.1:8000)
CMD ["python", "smartdrive_server.py"]
