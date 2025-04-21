# web_app.py
# Web application for liveness detection.
import eventlet
eventlet.monkey_patch()

import os
import cv2
import base64
import numpy as np
import logging
import random
import string
import qrcode
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import threading
import time
from typing import Dict, Any

from lib.config import Config
from lib.liveness_detector import LivenessDetector

# Initialise Flask app
app = Flask(__name__,
            static_folder='static',
            template_folder='templates')
app.config['SECRET_KEY'] = 'ajs871kn&43jn*03m1nj&!09nd8'

# Initialise socketio
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialise config
config = Config()

# Configure logging
logging.basicConfig(level=config.APP_LOGGING_LEVEL, format=config.LOGGING_FORMAT)
logging.getLogger('lib.speech_recognizer').setLevel(config.SPEECH_RECOGNIZER_LOGGING_LEVEL)
logging.getLogger('lib.action_detector').setLevel(config.ACTION_DETECTOR_LOGGING_LEVEL)
logging.getLogger('lib.challenge_manager').setLevel(config.CHALLENGE_MANAGER_LOGGING_LEVEL)
logging.getLogger('lib.liveness_detector').setLevel(config.LIVENESS_DETECTOR_LOGGING_LEVEL)
logger = logging.getLogger(__name__)

# Initialise active sessions
active_sessions: Dict[str, Dict[str, Any]] = {}

# Initialise verification codes
verification_codes: Dict[str, Dict[str, Any]] = {}

# Initialise last log time
last_log_time = {}

# Initialise warned unknown sessions
warned_unknown_sessions = set()

# Route for the landing page
@app.route('/')
def index():
    return render_template('index.html')

# Route for the verification page
@app.route('/verify/<code>')
def verify(code):
    # Check if code is a 6-digit number
    if not code.isdigit() or len(code) != 6:
        return render_template('error.html', message="Invalid code format", redirect_url="/")
    
    # Check if code is pending
    if code not in verification_codes or verification_codes[code]['status'] != 'pending':
        return render_template('error.html', message="Invalid or expired verification code", redirect_url="/")
    return render_template('verify.html', session_code=code) # Return verification page if code is valid

# Route for checking if a code is valid
@app.route('/check_code/<code>')
def check_code(code):
    logger.debug(f"Check code route called with code: {code}")
    is_valid = code in verification_codes and verification_codes[code]['status'] == 'pending'
    return jsonify({'valid': is_valid})

# Function to cleanup a session
def cleanup_session(session_id: str, code: str = None):
    if session_id in active_sessions:                                       # Check if session is active
        session_data = active_sessions[session_id]                          # Get session data
        if session_data['detector'] is not None:                            # Check if detector is not None
            if hasattr(session_data['detector'].speech_recognizer, "stop"): # Check if speech recognizer has stop method
                session_data['detector'].speech_recognizer.stop()           # Stop the speech recognizer
        code = code or session_data.get('code')                             # Get code
        if code and code in verification_codes:                             # Check if code is in verification codes
            qr_path = f"static/qr_codes/{code}.png"                         # Get QR code path
            if os.path.exists(qr_path):                                     # Check if QR code exists
                os.remove(qr_path)                                          # Delete the QR code
                logger.info(f"Deleted QR code for session {session_id}: {code}")
            verification_codes[code]['status'] = 'completed'                # Set the status of the code to completed
            del verification_codes[code]                                    # Delete the code from the verification codes dictionary
        del active_sessions[session_id]                                     # Delete the session from the active sessions dictionary
        logger.info(f"Cleaned up session {session_id} with code {code}")

# SocketIO event for when a client connects
@socketio.on('connect')
def handle_connect():
    session_id = request.sid # Get session ID
    logger.info(f"Client connected: {session_id}")

# SocketIO event for when a client disconnects
@socketio.on('disconnect')
def handle_disconnect():
    session_id = request.sid # Get session ID
    logger.info(f"Client disconnected: {session_id}")
    cleanup_session(session_id)

# SocketIO event for when a client sends an audio chunk
@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    session_id = request.sid # Get session ID
    logger.debug(f"Received audio chunk event from session: {session_id}")

    # Check if session is active
    if session_id not in active_sessions:

        # Check if session is unknown
        if session_id not in warned_unknown_sessions:
            logger.warning(f"Received audio chunk from unknown session: {session_id}")
            warned_unknown_sessions.add(session_id) # Add session to warned unknown sessions to prevent spamming
        return
    try:
        audio_chunk = base64.b64decode(data['audio']) # Decode audio chunk
        detector = active_sessions[session_id]['detector'] # Get detector
        detector.speech_recognizer.process_audio_chunk(audio_chunk) # Process audio chunk
    except Exception as e:
        logger.error(f"Error processing audio chunk from session {session_id}: {e}")

# SocketIO event for when a client sends a frame
@socketio.on('frame')
def handle_frame(data):
    session_id = request.sid # Get session ID

    # Check if session is active
    if session_id not in active_sessions:
        logger.warning(f"Received frame from unknown session: {session_id}")
        return
    
    # Check if attempts are greater than 3
    if active_sessions[session_id].get('attempts', 0) >= 3:
        emit('max_attempts_reached') # Emit max attempts reached
        cleanup_session(session_id) # Cleanup session
        return
    active_sessions[session_id]['last_activity'] = time.time() # Update last activity time for session
    try:
        image_data = data['image'].split(',')[1]            # Split image data
        image_bytes = base64.b64decode(image_data)          # Decode image data
        image_array = np.frombuffer(image_bytes, np.uint8)  # Convert image data to numpy array 
        frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR) # Decode image array to frame for processing by liveness detector
        detector = active_sessions[session_id]['detector']  # Get liveness detector
        frame, exit_flag = detector.detect_liveness(frame)  # Detect liveness and get exit flag
        head_pose = detector.head_pose                      # Get head pose from detector
        blink_counter = detector.blink_count                # Get blink counter from detector
        last_speech = detector.last_speech or ""            # Get last speech from detector
        challenge_text, action_completed, word_completed, verification_result = \
            detector.challenge_manager.get_challenge_status(head_pose, blink_counter, last_speech) # Get challenge status
        _, buffer = cv2.imencode('.jpg', frame)                     # Encode frame to buffer for display
        encoded_frame = base64.b64encode(buffer).decode('utf-8')    # Encode frame to base64 due to socketio limitation

        # Emit processed frame to requester for display
        emit('processed_frame', {
            'image': f'data:image/jpeg;base64,{encoded_frame}',     # Emit processed frame
            'challenge': challenge_text,                            # Emit challenge text
            'action_completed': action_completed,                   # Emit action completed
            'word_completed': word_completed,                       # Emit word completed
            'time_remaining': detector.challenge_manager.get_challenge_time_remaining(), # Emit time remaining
            'verification_result': verification_result,             # Emit verification result
            'exit_flag': exit_flag                                  # Emit exit flag
        })

        # If exit flag and verification result are in ['PASS', 'FAIL']
        if exit_flag and verification_result in ['PASS', 'FAIL']:
            active_sessions[session_id]['attempts'] = active_sessions[session_id].get('attempts', 0) + 1 # Update attempts

            # If verification result is PASS or attempts are greater than 3
            if verification_result == 'PASS' or active_sessions[session_id]['attempts'] >= 3:
                cleanup_session(session_id) # Cleanup session
    except Exception as e:
        logger.error(f"Error processing frame: {e}")
        emit('error', {'message': str(e)})

# SocketIO event for when a client sends a reset request
@socketio.on('reset')
def handle_reset(data):
    session_id = request.sid
    code = data.get('code')

    # Check if session is active to prevent unknown session reset requests
    if session_id not in active_sessions:
        logger.warning(f"Reset request from unknown session: {session_id}")
        return
    try:
        detector = active_sessions[session_id]['detector']
        detector.reset()
        active_sessions[session_id]['attempts'] = active_sessions[session_id].get('attempts', 0) + 1
        logger.info(f"Reset detector for session {session_id}, new challenge issued, attempt {active_sessions[session_id]['attempts']}")
        emit('reset_confirmed')
    except Exception as e:
        logger.error(f"Error resetting verification: {e}")
        emit('error', {'message': str(e)})

# SocketIO event for when a client requests debug status (used in app.js to toggle debug mode)
@socketio.on('get_debug_status')
def handle_get_debug_status():
    logger.debug("Debug status requested")
    emit('debug_status', {
        'debug': config.BROWSER_DEBUG,
        'showDebugFrame': config.SHOW_DEBUG_FRAME
    })

# SocketIO event for when a client requests a verification code
@socketio.on('generate_code')
def handle_generate_code():
    session_id = request.sid
    logger.info(f"Generate code request from session {session_id}")
    code = ''.join(random.choices(string.digits, k=6))
    verification_url = f"{config.BASE_URL}/verify/{code}"
    
    # Create QR code with transparent background for overlay
    qr = qrcode.QRCode(version=1, box_size=10, border=5) # Create QR code with transparent background
    qr.add_data(verification_url) # Add verification URL to QR code
    qr.make(fit=True) # Make QR code fit the data
    
    # Create QR code with transparent background
    qr_img = qr.make_image(fill='black', back_color=(255, 255, 255, 0)) # Create QR code with transparent background
    
    # Save the QR code with transparent background
    qr_path = f"static/qr_codes/{code}.png" # Save QR code to static/qr_codes directory
    qr_img.save(qr_path) # Save QR code to static/qr_codes directory

    # Add verification code to verification codes dictionary
    verification_codes[code] = {
        'requester_id': session_id,
        'created_at': time.time(),
        'status': 'pending'
    }
    
    logger.info(f"Emitting verification code {code} with QR code to session {session_id}")
    emit('verification_code', {
        'code': code, 
        'qr_code': f"/static/qr_codes/{code}.png",
        'enable_video_background': True  # Flag to enable video background in QR code
    })

    # Expire code after 10 minutes
    def expire_code():
        time.sleep(config.CODE_EXPIRATION_TIME)
        if code in verification_codes and verification_codes[code]['status'] == 'pending':
            qr_path = f"static/qr_codes/{code}.png"
            if os.path.exists(qr_path):
                os.remove(qr_path)
                logger.info(f"Deleted QR code for expired code: {code}")
            del verification_codes[code]
            logger.info(f"Expired verification code {code}")
    expiration_thread = threading.Thread(target=expire_code) # Create thread to expire code
    expiration_thread.daemon = True # Set thread as daemon
    expiration_thread.start() # Start thread

# Function to cleanup inactive sessions
def cleanup_inactive_sessions():
    while True:
        current_time = time.time()
        inactive_sessions = []
        for session_id, session_data in active_sessions.items():
            if current_time - session_data['last_activity'] > config.SESSION_TIMEOUT:
                inactive_sessions.append(session_id)
        for session_id in inactive_sessions:
            cleanup_session(session_id)
        time.sleep(10)

# SocketIO event for when a client joins a verification session
@socketio.on('join_verification')
def handle_join_verification(data):
    session_id = request.sid
    code = data.get('code')
    logger.info(f"Client {session_id} joining verification session with code: {code}")

    # Check if code is valid
    if not code or code not in verification_codes or verification_codes[code]['status'] != 'pending':
        emit('session_error', {'message': 'Invalid or expired verification code'})
        return
    verification_codes[code]['status'] = 'in-progress' # Set status of code to in-progress
    verification_codes[code]['verifier_id'] = session_id # Add verifier ID to verification codes dictionary
    active_sessions[session_id] = {
        'code': code,
        'detector': None,
        'last_activity': time.time(),
        'attempts': 0
    }
    join_room(code) # Join room with code
    requester_id = verification_codes[code]['requester_id']
    emit('verification_started', {
        'code': code, 
        'partner_video': True  # Flag to indicate partner video should be shown
    }, room=requester_id)
    detector = LivenessDetector(config) # Create liveness detector
    active_sessions[session_id]['detector'] = detector # Add detector to active sessions dictionary
    challenge_text, _, _, _ = detector.challenge_manager.get_challenge_status(
        detector.head_pose, detector.blink_count, detector.last_speech or ""
    )
    emit('challenge', {'text': challenge_text}) # Emit challenge text

# SocketIO event for when a client sends a frame
@socketio.on('process_frame')
def handle_process_frame(data):
    session_id = request.sid
    code = data.get('code')

    # Check if session is active and code is valid
    if session_id not in active_sessions or active_sessions[session_id]['code'] != code:
        logger.warning(f"Received frame from unknown or invalid session: {session_id}, code: {code}")
        emit('session_error', {'message': 'Invalid session or code'})
        return
    
    # Check if attempts are greater than 3
    if active_sessions[session_id].get('attempts', 0) >= 3:
        emit('max_attempts_reached')
        cleanup_session(session_id, code)
        return
    active_sessions[session_id]['last_activity'] = time.time() # Update last activity time for session
    try:
        image_data = data['image'].split(',')[1] # Split image data for decoding
        image_bytes = base64.b64decode(image_data) # Decode image data as bytes because of socketio limitation
    except Exception as e:
        logger.error(f"Failed to decode base64 image data: {e}")
        emit('error', {'message': 'Invalid image data'})
        return
    
    nparr = np.frombuffer(image_bytes, np.uint8) # Convert image data to numpy array 
    
    # Check if image data is empty
    if nparr.size == 0:
        logger.debug("Received empty frame buffer; waiting for next frame")
        emit('waiting_for_camera', {'message': 'Camera not ready yet'})
        return
    
    frame = None # Initialise frame
    max_retries = 10 # Maximum number of retries
    retry_delay = 0.1 # Delay between retries

    # Try to decode image data
    for attempt in range(max_retries):
        try:
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR) # Decode image data
            if frame is None:
                logger.debug(f"Failed to decode frame on attempt {attempt + 1}/{max_retries}")
                time.sleep(retry_delay)
                continue
            logger.debug(f"Frame decoded successfully: shape={frame.shape}")
            break
        except Exception as e:
            logger.error(f"Error decoding frame on attempt {attempt + 1}/{max_retries}: {e}")
            time.sleep(retry_delay)

    # Check if frame is None
    if frame is None:
        logger.error(f"Failed to decode frame after {max_retries} attempts")
        emit('error', {'message': 'Unable to process frame'})
        return
    try:
        detector = active_sessions[session_id]['detector'] # Get detector
        result = detector.process_frame(frame) # Process frame
        frame = result['frame'] # Get frame
        debug_frame = result['debug_frame'] # Get debug frame
        if frame is not None:
            _, buffer_disp = cv2.imencode('.jpg', frame) # Encode frame to buffer
            disp_b64 = base64.b64encode(buffer_disp).decode('utf-8') # Encode buffer to base64
            logger.debug("Display frame encoded")
            
            # Send partner video frame to requester if available
            if code in verification_codes and 'requester_id' in verification_codes[code]:
                requester_id = verification_codes[code]['requester_id']
                # Send the partner's video frame to be displayed in the QR code background
                emit('partner_video_frame', {
                    'image': f"data:image/jpeg;base64,{disp_b64}", # Emit partner video frame
                    'code': code # Emit code
                }, room=requester_id) # Emit to requester
        else:
            disp_b64 = None
            logger.debug("Display frame is None")
        debug_b64 = None

        # Check if debug frame is not None
        if debug_frame is not None:
            _, buffer_dbg = cv2.imencode('.jpg', debug_frame) # Encode debug frame to buffer
            debug_b64 = base64.b64encode(buffer_dbg).decode('utf-8') # Encode buffer to base64
            logger.debug("Debug frame encoded")
        else:
            logger.debug("Debug frame is None")
        emit_data = {
            'image': f"data:image/jpeg;base64,{disp_b64}" if disp_b64 else None,            # Emit image
            'debug_image': f"data:image/jpeg;base64,{debug_b64}" if debug_b64 else None,    # Emit debug image
            'challenge': result['challenge_text'],                                          # Emit challenge text
            'action_completed': result['action_completed'],                                 # Emit action completed
            'word_completed': result['word_completed'],                                     # Emit word completed
            'blink_completed': result['blink_completed'],                                   # Emit blink completed
            'time_remaining': result['time_remaining'],                                     # Emit time remaining
            'verification_result': result['verification_result'],                           # Emit verification result
            'exit_flag': result['exit_flag'],                                               # Emit exit flag
            'duress_detected': result['duress_detected']                                    # Emit duress detected
        }
        logger.debug(f"Emitting processed_frame: has_image={bool(disp_b64)}, has_debug={bool(debug_b64)}")
        emit('processed_frame', emit_data) # Emit processed frame

        # Check if exit flag is True
        if result['exit_flag']:
            active_sessions[session_id]['attempts'] = active_sessions[session_id].get('attempts', 0) + 1
            logger.debug(f"Attempt {active_sessions[session_id]['attempts']} for session {session_id}")
            requester_id = verification_codes[code]['requester_id'] # Get requester ID

            # Check if duress detected is True
            if result['duress_detected']:
                emit('verification_result', {
                    'result': 'FAIL',
                    'code': code,
                    'duress_detected': True
                }, room=requester_id) # Emit verification result
                cleanup_session(session_id, code) # Cleanup session

            # Check if verification result is PASS
            elif result['verification_result'] == 'PASS':
                emit('verification_result', {
                    'result': 'PASS',
                    'code': code,
                    'duress_detected': False
                }, room=requester_id) # Emit verification result
                cleanup_session(session_id, code) # Cleanup session

            # Check if verification result is FAIL or time remaining is 0
            elif result['verification_result'] == 'FAIL' or result['time_remaining'] <= 0:
                if active_sessions[session_id]['attempts'] >= 3:
                    emit('verification_result', {
                        'result': 'FAIL',
                        'code': code,
                        'duress_detected': False
                    }, room=requester_id) # Emit verification result
                    cleanup_session(session_id, code) # Cleanup session
                else:
                    detector.reset() # Reset detector
                    logger.info(f"Reset detector after failure/timeout for session {session_id}, attempt {active_sessions[session_id]['attempts']}")
                    challenge_text, _, _, _ = detector.challenge_manager.get_challenge_status(
                        detector.head_pose, detector.blink_count, detector.last_speech or ""
                    )
                    emit('challenge', {'text': challenge_text}) # Emit challenge text
    except Exception as e:
        logger.error(f"Error processing frame: {e}")
        emit('error', {'message': str(e)})

# SocketIO event for when a client sends a verification complete event
@socketio.on('verification_complete')
def handle_verification_complete(data):
    code = data.get('code') # Get code
    result = data.get('result') # Get result

    # Check if code is valid
    if code and code in verification_codes:
        requester_id = verification_codes[code]['requester_id'] # Get requester ID
        emit('verification_result', {
            'result': result,
            'code': code
        }, room=requester_id) # Emit verification result
        for session_id, session_data in list(active_sessions.items()):
            if session_data.get('code') == code:
                cleanup_session(session_id, code) # Cleanup session if code matches
        logger.info(f"Verification {code} completed with result: {result}")

# Main function
if __name__ == '__main__':
    os.makedirs('static/qr_codes', exist_ok=True) # Create qr_codes directory if it doesn't exist

    # Create thread to cleanup inactive sessions
    cleanup_thread = threading.Thread(target=cleanup_inactive_sessions) # Create thread to cleanup inactive sessions
    cleanup_thread.daemon = True # Set thread as daemon to run in background
    cleanup_thread.start() # Start thread to cleanup inactive sessions

    # Run app
    socketio.run(
        app, 
        host=config.HOST, 
        port=config.PORT, 
        debug=config.BROWSER_DEBUG, 
        use_reloader=False)

