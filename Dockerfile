# Use Python 3.11-slim as a base (3.13 is bleeding-edge, not widely available)
FROM python:3.11-slim

# Create working dir
WORKDIR /app

# Install system packages required by dlib, pocketsphinx, opencv, pyaudio, Pillow, etc.
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
    libasound-dev \
    libportaudio2 \
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

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your code
COPY . /app

# EXPOSE the port your web_app.py uses (default is 8080 from Config())
EXPOSE 8080

# Default command to run your Flask SocketIO app
CMD ["python", "web_app.py"]
