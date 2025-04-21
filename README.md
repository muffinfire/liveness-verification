# Liveness Verification System

A real-time web-based liveness detection system for identity verification using webcam input, facial landmarks, blink detection, head pose analysis, and keyword speech recognition.

Built with Flask, Flask-SocketIO, OpenCV, Dlib, and PocketSphinx. Designed for containerised deployment behind a reverse proxy (e.g., Nginx).

---

## Features

- One-time code and QR code generation for secure sessions
- Head pose + blink + keyword speech verification
- WebSocket-powered live video/audio streaming
- Auto-expiring sessions and challenge logic
- Duress word detection (`verify`)
- Designed for local or containerised production use

---

## Tech Stack

- **Backend**: Flask, Flask-SocketIO (via `eventlet`), OpenCV, Dlib, PocketSphinx
- **Frontend**: Vanilla JS, Socket.IO, HTML/CSS
- **Packaging**: Docker + `docker-compose`
- **Reverse Proxy Ready**: Tested behind Nginx Proxy Manager

---

## Quick Install (With Docker)

### Step 1: Clone the Repo

```bash
git clone https://github.com/muffinfire/facedetection.git
cd facedetection
```

### Step 2: Build & Run the App

```bash
bash install_liveness.sh
```

This script:

- Creates a system user
- Clones the public repo from the `Prod` branch
- Builds the Docker image
- Starts the container
- App will be available at: `http://<your-server-ip>:8001`

### Step 3 (Optional): Uninstall Everything

```bash
bash uninstall_liveness.sh
```

Removes the container, repo folder, and optionally the system user.

---

## Docker Overview

```yaml
# docker-compose.yml
services:
  liveness-verification:
    build: .
    container_name: liveness-verification
    ports:
      - "8001:8080"
    environment:
      - PORT=8080
      - SECRET_KEY=ajs871kn&43jn*03m1nj&!09nd8
    restart: unless-stopped
```

```dockerfile
# Dockerfile (Python 3.11-slim)
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential cmake pkg-config \
    libatlas-base-dev libjpeg-dev libpng-dev \
    libavformat-dev libavcodec-dev libavfilter-dev \
    libswscale-dev libv4l-dev \
    libopenblas-dev liblapack-dev \
    portaudio19-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app
EXPOSE 8080
CMD ["python", "web_app.py"]
```

---

## Project Structure

```
├── Dockerfile
├── README.md
├── bin
│   ├── haarcascade_frontalface_default.xml
│   └── shape_predictor_68_face_landmarks.dat
├── docker-compose.yml
├── lib
│   ├── action_detector.py
│   ├── blink_detector.py
│   ├── challenge_manager.py
│   ├── config.py
│   ├── face_detector.py
│   ├── liveness_detector.py
│   ├── speech_recognizer.py
│   └── utils
│       └── landmarksv2.py
├── models
│   └── en-us
│       └── [pocketsphinx model files...]
├── requirements.txt
├── static
│   ├── css
│   │   └── style.css
│   ├── favicon.ico
│   ├── js
│   │   ├── app.js
│   │   └── landing.js
│   └── qr_codes
├── templates
│   ├── error.html
│   ├── index.html
│   └── verify.html
└── web_app.py
```

---

## How It Works (Frontend Flow)

1. **Landing Page (`/`)**
   - User can generate a code + QR, or enter one to verify

2. **Verification Page (`/verify/<code>`)**
   - Captures webcam + audio
   - Waits for real-time challenges
   - Displays action, word, blink, and time feedback
   - Auto-fails on duress word or inactivity

---

## Configuration Notes

Most relevant runtime options from `lib/config.py`:

- `SESSION_TIMEOUT`: max session life in seconds (default: 120)
- `CODE_EXPIRATION_TIME`: QR code expiry window in seconds (default: 600)
- `CHALLENGE_TIMEOUT`: how long a challenge can run (default: 30)
- `BROWSER_DEBUG` and `SHOW_DEBUG_FRAME`: control front-end debug visibility
- `BLINK_THRESHOLD` and `MIN_BLINK_FRAMES`: control blink detection sensitivity
- `BLINK_COUNTER_THRESHOLD`: control number of blinks to count as a challenge completion
- `HEAD_POSE_THRESHOLD_*`: tweak visual gesture sensitivity
- `SPEECH_KEYWORDS`: valid words and weights for recognition (can be added to)
- `ACTION_SPEECH_WINDOW`: allowed time between action and speech (seconds)
- `BASE_URL`: must match public-facing hostname or proxy URL for QR to work

These can be tuned by editing `config.py` directly or injecting via environment.

---

## App Usage Notes

- **Request Verification**: click 'Generate Code' to get a 6-digit code and QR
- **Join a Session**: scan the QR or enter the code on the landing page
- **Camera Access**: is required for both video and speech inputs
- **Complete Challenges**: follow on-screen instructions; up to 3 tries allowed
- **Result Feedback**: UI will show ✅ or ❌ per challenge component
- **Debug View**: optional visual overlay for dev/testing purposes

---

## Security Notes

- QR codes expire after 10 minutes
- Sessions are cleaned up automatically
- Saying `verify` triggers duress protocol (auto-fail)
- Meant to run behind HTTPS via reverse proxy (e.g., Nginx)

---

## Debugging

```bash
# Check logs
sudo docker logs liveness-verification

# Rebuild manually
sudo docker compose down
sudo docker compose up --build
```

---

## Uninstall

```bash
bash uninstall_liveness.sh
```

Options:
- `REMOVE_USER=true` to delete `livenessuser`
- `REMOVE_VOLUMES=true` to prune Docker volumes

---

## License

This software is free for personal and non-commercial use.  
Commercial use, resale, or distribution in for-profit environments is strictly prohibited without prior written consent from the author.  
All intellectual property rights are retained by Adam Baumgartner (muffinfire).

---

## Author

Built by Adam Baumgartner (muffinfire)
