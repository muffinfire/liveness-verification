FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libxext-dev \
    libsm6 \
    libxrender1 \
    libffi-dev \
    libsndfile1 \
    libportaudio2 \
    libasound-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libavformat-dev \
    libavcodec-dev \
    libswscale-dev \
    libpulse-dev \
    libfreetype6-dev \
    libharfbuzz-dev \
    libxcb1-dev \
    && rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /app

# Copy your files
COPY . /app

# Virtualenv optional; pip install directly
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# Entry point (change if needed)
CMD ["python", "main.py"]
