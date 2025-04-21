FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    pkg-config \
    libatlas-base-dev \
    libjpeg-dev \
    libpng-dev \
    libavformat-dev \
    libavcodec-dev \
    libavfilter-dev \
    libswscale-dev \
    libv4l-dev \
    libopenblas-dev \
    liblapack-dev \
    portaudio19-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 8080

CMD ["python", "web_app.py"]
