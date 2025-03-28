FROM python:3.11-slim

WORKDIR /app

# Install OS-level dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    pkg-config \
    libx11-dev \
    libgtk-3-dev \
    libatlas-base-dev \
    libjpeg-dev \
    libpng-dev \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavfilter-dev \
    libswscale-dev \
    libavresample-dev \
    libv4l-dev \
    libopenblas-dev \
    liblapack-dev \
    libpq-dev \
    portaudio19-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy application files
COPY . /app

# Install Python requirements
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

EXPOSE 8080

CMD ["python", "web_app.py"]
