# Liveness Detection Web Application
### Overview
This project is a Flask-based web application designed to perform liveness detection for identity verification. It integrates computer vision and speech recognition to ensure that a user is a live person (not a photo, video, or spoof) by issuing challenges such as head movements and spoken words. The application uses real-time video processing via WebSockets, QR code-based session management, and a modular architecture for extensibility.
#### Key features include:
* Real-time video frame processing using OpenCV and dlib.
* Liveness challenges combining head pose detection, blink detection, and speech recognition.
* WebSocket communication for low-latency client-server interaction.
* QR code generation for secure session verification.
* Duress detection to identify coerced verifications.
* Configurable settings for timeouts, thresholds, and debug modes.

This application is built with security and usability in mind, suitable for scenarios like remote authentication or access control systems.
#### Prerequisites
* Python 3.8+: Ensure Python is installed on your system.
* pip: Python package manager for installing dependencies.
* Webcam: Required for video input during verification.
* Microphone: Required for speech recognition challenges.

#### Installation
1. Clone the Repository

       git clone https://github.com/yourusername/liveness-detection.git
       cd liveness-detection

3. Create a Virtual Environment

       python -m venv venv
       source venv/bin/activate  # On Windows: venv\Scripts\activate

4.  Install Dependencies
Install the required Python packages listed in requirements.txt:

        pip install -r requirements.txt

Example requirements.txt (create this file if not provided):

    flask
    flask-socketio
    opencv-python
    numpy
    dlib
    qrcode
    pillow

Note: dlib may require additional system dependencies (e.g., cmake, libopenblas). On Ubuntu, install them with:
bash

    sudo apt-get install build-essential cmake libopenblas-dev liblapack-dev libx11-dev libgtk-3-dev

5.  Download dlib Shape Predictor
* Download the pre-trained facial landmark predictor (shape_predictor_68_face_landmarks.dat) from dlib’s official source
* Extract and place it in the project root directory.

SSL Certificates (Optional)
* For HTTPS, provide cert.pem and key.pem in the project root or update config.py with correct paths.

#### Usage
1. Configure Settings
Edit config.py to adjust parameters such as:
* HOST and PORT: Server address and port.
* DEBUG: Enable/disable debug mode.
* SESSION_TIMEOUT: Session inactivity timeout.
* BASE_URL: Base URL for QR code generation.
* CERTFILE and KEYFILE: Paths to SSL certificates.

Example config.py: (python)

    class Config:
       HOST = '0.0.0.0'
       PORT = 8080
       DEBUG = True
       SESSION_TIMEOUT = 300  # 5 minutes
       BASE_URL = 'http://localhost:8080'
       CERTFILE = 'cert.pem'
       KEYFILE = 'key.pem'
       SHOW_DEBUG_FRAME = True
       HEAD_POSE_THRESHOLD_HORIZONTAL = 0.2
       HEAD_POSE_THRESHOLD_UP = 20
       HEAD_POSE_THRESHOLD_DOWN = 20
       FACE_POSITION_HISTORY_LENGTH = 10
       LOGGING_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

2. Run the Application
Start the Flask server:

       python web_app.py

The server will run on the configured HOST and PORT (e.g., http://localhost:8080).

3. Access the Web Interface
* Open a browser and navigate to the server URL (e.g., http://localhost:8080).
* The homepage (index.html) allows initiating a verification session.
* A QR code will be generated; scan it with another device to start the verification process.

4. Perform Verification
* The verifier device will display a video feed and a challenge (e.g., "Turn left and say blue").
* Follow the instructions (head movement and speech).
* The system will process the video and audio in real-time, displaying results on-screen.
* Verification ends with a "PASS" or "FAIL" result, or restarts if attempts remain (max 3).

### Architecture
#### blink_detector.py
Handles eye detection and blink analysis using facial landmarks. It calculates the Eye Aspect Ratio (EAR) with dlib to detect blinks or falls back to Haar cascades if dlib fails. Outputs blink counts and debug visualizations.

####  challenge_manager.py
Manages liveness challenges (e.g., "Turn left and say clock"). Issues random challenges, verifies user actions (head pose, blinks, speech), and tracks completion status with timeouts and duress detection.

####  config.py
Defines configuration settings for the system, including camera resolution, thresholds for face and blink detection, challenge parameters, and available challenges. Centralizes all tunable constants.

####  face_detector.py
Detects faces in video frames using Haar cascades and estimates head pose (left, right, up, down, center) based on face position. Provides face regions and movement detection for liveness analysis.

####  liveness_detector.py
The core module integrating all components (face detection, blink detection, speech recognition, challenge management). Processes video frames to determine liveness, updates UI with status, and manages verification flow.

####  speech_recognizer.py
Implements real-time speech recognition using PocketSphinx. Listens for specific keywords (e.g., "clock," "verify") tied to challenges and updates the system with detected speech.

####  web_app.py
The Flask-based web application with SocketIO for real-time communication. Serves the UI, generates verification codes and QR codes, processes video frames from clients, and manages session state.

#### action_detector.py
Detects specific head movements (e.g., turn left, look up) using dlib facial landmarks. Tracks action completion for challenges, enhancing liveness verification accuracy.

#### static/js/app.js
Client-side logic for the verification page (verify.html). Captures webcam frames, sends them to the server via SocketIO, updates the UI with challenge status, and handles results (pass, fail, duress) with visual effects.

#### static/js/landing.js
Manages the landing page (index.html) interactions. Handles code generation, QR code display, and code submission, communicating with the server via SocketIO to initiate or join verification sessions.



Data Flow
1. Client connects via WebSocket and requests a verification code.
2. Server generates a QR code linking to a verification URL.
3. Verifier scans the QR code, joins the session, and streams video/audio.
4. Server processes frames, updates challenge status, and sends results back in real-time.
5. Verification completes with a result sent to both requester and verifier.

Features
* Real-Time Processing: Video frames are analyzed instantly using OpenCV.
* Multi-Factor Challenges: Combines head movements and speech for robust liveness proof.
* Session Management: Tracks active sessions and expires inactive ones.
* Duress Detection: Flags "verify" as a duress signal, failing the verification.
* Debug Mode: Optional debug frames show facial landmarks and EAR values.

Limitations
* Requires a webcam and microphone, limiting use on devices without these.
* dlib dependency may be challenging to install on some systems.
* In-memory session storage (not persistent across restarts).
* No user authentication beyond QR codes; add as needed for production.

License
This project is licensed under the MIT License. See the LICENSE file for details.
Acknowledgments
Built with Flask, SocketIO, OpenCV, and dlib.

Inspired by anti-spoofing techniques in biometric authentication.

