# Use Debian 12 (Bookworm) based Python image
FROM python:3.13-bookworm

# Set working directory
WORKDIR /app

# Install system dependencies
# Node.js 20.x, FFmpeg, and curl
RUN apt-get update && apt-get install -y \
    curl \
    ffmpeg \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-cache the tiktoken BPE encoding so real token counting also works
# when the container later runs without internet access.
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

# Install Playwright OS dependencies and browser
RUN playwright install --with-deps

# Copy node scripts and install their dependencies
COPY node_scripts/package.json node_scripts/package-lock.json* ./node_scripts/
RUN cd node_scripts && npm install

# Copy the rest of the application
COPY . .

# Expose port
EXPOSE 5000

# Run the application
CMD ["python", "app.py"]
