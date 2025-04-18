"""Web application for liveness detection."""

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

# Initialize Flask app
app = Flask(__name__,
            static_folder='static',
            template_folder='templates')
app.config['SECRET_KEY'] = 'liveness-detection-secret'

# Initialize socketio
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialize config
config = Config()

# Configure logging
logging.basicConfig(level=config.APP_LOGGING_LEVEL, format=config.LOGGING_FORMAT)
logging.getLogger('speech_recognizer').setLevel(config.SPEECH_RECOGNIZER_LOGGING_LEVEL)
logging.getLogger('action_detector').setLevel(config.ACTION_DETECTOR_LOGGING_LEVEL)
logging.getLogger('challenge_manager').setLevel(config.CHALLENGE_MANAGER_LOGGING_LEVEL)
logging.getLogger('liveness_detector').setLevel(config.LIVENESS_DETECTOR_LOGGING_LEVEL)
logger = logging.getLogger(__name__)

# Initialize active sessions
active_sessions: Dict[str, Dict[str, Any]] = {}

# Initialize verification codes
verification_codes: Dict[str, Dict[str, Any]] = {}

# Initialize last log time
last_log_time = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/verify/<code>')
def verify(code):
    if not code.isdigit() or len(code) != 6:
        return render_template('error.html', message="Invalid code format", redirect_url="/")
    if code not in verification_codes or verification_codes[code]['status'] != 'pending':
        return render_template('error.html', message="Invalid or expired verification code", redirect_url="/")
    return render_template('verify.html', session_code=code)

@app.route('/check_code/<code>')
def check_code(code):
    logger.debug(f"Check code route called with code: {code}")
    is_valid = code in verification_codes and verification_codes[code]['status'] == 'pending'
    return jsonify({'valid': is_valid})

def cleanup_session(session_id: str, code: str = None):
    if session_id in active_sessions:
        session_data = active_sessions[session_id]
        if session_data['detector'] is not None:
            if hasattr(session_data['detector'].speech_recognizer, "stop"):
                session_data['detector'].speech_recognizer.stop()
        code = code or session_data.get('code')
        if code and code in verification_codes:
            qr_path = f"static/qr_codes/{code}.png"
            if os.path.exists(qr_path):
                os.remove(qr_path)
                logger.info(f"Deleted QR code for session {session_id}: {code}")
            verification_codes[code]['status'] = 'completed'
            del verification_codes[code]
        del active_sessions[session_id]
        logger.info(f"Cleaned up session {session_id} with code {code}")

@socketio.on('connect')
def handle_connect():
    session_id = request.sid
    logger.info(f"Client connected: {session_id}")

@socketio.on('disconnect')
def handle_disconnect():
    session_id = request.sid
    logger.info(f"Client disconnected: {session_id}")
    cleanup_session(session_id)

@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    session_id = request.sid
    logger.debug(f"Received audio chunk event from session: {session_id}")
    if session_id not in active_sessions:
        logger.warning(f"Received audio chunk from unknown session: {session_id}")
        return
    try:
        audio_chunk = base64.b64decode(data['audio'])
        detector = active_sessions[session_id]['detector']
        detector.speech_recognizer.process_audio_chunk(audio_chunk)
    except Exception as e:
        logger.error(f"Error processing audio chunk from session {session_id}: {e}")

@socketio.on('frame')
def handle_frame(data):
    session_id = request.sid
    if session_id not in active_sessions:
        logger.warning(f"Received frame from unknown session: {session_id}")
        return
    if active_sessions[session_id].get('attempts', 0) >= 3:
        emit('max_attempts_reached')
        cleanup_session(session_id)
        return
    active_sessions[session_id]['last_activity'] = time.time()
    try:
        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
        image_array = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        detector = active_sessions[session_id]['detector']
        frame, exit_flag = detector.detect_liveness(frame)
        head_pose = detector.head_pose
        blink_counter = detector.blink_count
        last_speech = detector.last_speech or ""
        challenge_text, action_completed, word_completed, verification_result = \
            detector.challenge_manager.get_challenge_status(head_pose, blink_counter, last_speech)
        _, buffer = cv2.imencode('.jpg', frame)
        encoded_frame = base64.b64encode(buffer).decode('utf-8')
        emit('processed_frame', {
            'image': f'data:image/jpeg;base64,{encoded_frame}',
            'challenge': challenge_text,
            'action_completed': action_completed,
            'word_completed': word_completed,
            'time_remaining': detector.challenge_manager.get_challenge_time_remaining(),
            'verification_result': verification_result,
            'exit_flag': exit_flag
        })
        if exit_flag and verification_result in ['PASS', 'FAIL']:
            active_sessions[session_id]['attempts'] = active_sessions[session_id].get('attempts', 0) + 1
            if verification_result == 'PASS' or active_sessions[session_id]['attempts'] >= 3:
                cleanup_session(session_id)
    except Exception as e:
        logger.error(f"Error processing frame: {e}")
        emit('error', {'message': str(e)})

@socketio.on('reset')
def handle_reset(data):
    session_id = request.sid
    code = data.get('code')
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

@socketio.on('get_debug_status')
def handle_get_debug_status():
    logger.debug("Debug status requested")
    emit('debug_status', {
        'debug': config.BROWSER_DEBUG,
        'showDebugFrame': config.SHOW_DEBUG_FRAME
    })

@socketio.on('generate_code')
def handle_generate_code():
    session_id = request.sid
    logger.info(f"Generate code request from session {session_id}")
    code = ''.join(random.choices(string.digits, k=6))
    verification_url = f"{config.BASE_URL}/verify/{code}"
    
    # Create QR code with transparent background for overlay
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(verification_url)
    qr.make(fit=True)
    
    # Create QR code with transparent background
    qr_img = qr.make_image(fill='black', back_color=(255, 255, 255, 0))
    
    # Save the QR code with transparent background
    qr_path = f"static/qr_codes/{code}.png"
    qr_img.save(qr_path)
    
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
    def expire_code():
        time.sleep(600)
        if code in verification_codes and verification_codes[code]['status'] == 'pending':
            qr_path = f"static/qr_codes/{code}.png"
            if os.path.exists(qr_path):
                os.remove(qr_path)
                logger.info(f"Deleted QR code for expired code: {code}")
            del verification_codes[code]
            logger.info(f"Expired verification code {code}")
    expiration_thread = threading.Thread(target=expire_code)
    expiration_thread.daemon = True
    expiration_thread.start()

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

@socketio.on('join_verification')
def handle_join_verification(data):
    session_id = request.sid
    code = data.get('code')
    logger.info(f"Client {session_id} joining verification session with code: {code}")
    if not code or code not in verification_codes or verification_codes[code]['status'] != 'pending':
        emit('session_error', {'message': 'Invalid or expired verification code'})
        return
    verification_codes[code]['status'] = 'in-progress'
    verification_codes[code]['verifier_id'] = session_id
    active_sessions[session_id] = {
        'code': code,
        'detector': None,
        'last_activity': time.time(),
        'attempts': 0
    }
    join_room(code)
    requester_id = verification_codes[code]['requester_id']
    emit('verification_started', {
        'code': code, 
        'partner_video': True  # Flag to indicate partner video should be shown
    }, room=requester_id)
    detector = LivenessDetector(config)
    active_sessions[session_id]['detector'] = detector
    challenge_text, _, _, _ = detector.challenge_manager.get_challenge_status(
        detector.head_pose, detector.blink_count, detector.last_speech or ""
    )
    emit('challenge', {'text': challenge_text})

@socketio.on('process_frame')
def handle_process_frame(data):
    session_id = request.sid
    code = data.get('code')
    if session_id not in active_sessions or active_sessions[session_id]['code'] != code:
        logger.warning(f"Received frame from unknown or invalid session: {session_id}, code: {code}")
        emit('session_error', {'message': 'Invalid session or code'})
        return
    if active_sessions[session_id].get('attempts', 0) >= 3:
        emit('max_attempts_reached')
        cleanup_session(session_id, code)
        return
    active_sessions[session_id]['last_activity'] = time.time()
    try:
        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
    except Exception as e:
        logger.error(f"Failed to decode base64 image data: {e}")
        emit('error', {'message': 'Invalid image data'})
        return
    nparr = np.frombuffer(image_bytes, np.uint8)
    if nparr.size == 0:
        logger.debug("Received empty frame buffer; waiting for next frame")
        emit('waiting_for_camera', {'message': 'Camera not ready yet'})
        return
    frame = None
    max_retries = 10
    retry_delay = 0.1
    for attempt in range(max_retries):
        try:
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                logger.debug(f"Failed to decode frame on attempt {attempt + 1}/{max_retries}")
                time.sleep(retry_delay)
                continue
            logger.debug(f"Frame decoded successfully: shape={frame.shape}")
            break
        except Exception as e:
            logger.error(f"Error decoding frame on attempt {attempt + 1}/{max_retries}: {e}")
            time.sleep(retry_delay)
    if frame is None:
        logger.error(f"Failed to decode frame after {max_retries} attempts")
        emit('error', {'message': 'Unable to process frame'})
        return
    try:
        detector = active_sessions[session_id]['detector']
        result = detector.process_frame(frame)
        frame = result['frame']
        debug_frame = result['debug_frame']
        if frame is not None:
            _, buffer_disp = cv2.imencode('.jpg', frame)
            disp_b64 = base64.b64encode(buffer_disp).decode('utf-8')
            logger.debug("Display frame encoded")
            
            # Send partner video frame to requester if available
            if code in verification_codes and 'requester_id' in verification_codes[code]:
                requester_id = verification_codes[code]['requester_id']
                # Send the partner's video frame to be displayed in the QR code background
                emit('partner_video_frame', {
                    'image': f"data:image/jpeg;base64,{disp_b64}",
                    'code': code
                }, room=requester_id)
        else:
            disp_b64 = None
            logger.debug("Display frame is None")
        debug_b64 = None
        if debug_frame is not None:
            _, buffer_dbg = cv2.imencode('.jpg', debug_frame)
            debug_b64 = base64.b64encode(buffer_dbg).decode('utf-8')
            logger.debug("Debug frame encoded")
        else:
            logger.debug("Debug frame is None")
        emit_data = {
            'image': f"data:image/jpeg;base64,{disp_b64}" if disp_b64 else None,
            'debug_image': f"data:image/jpeg;base64,{debug_b64}" if debug_b64 else None,
            'challenge': result['challenge_text'],
            'action_completed': result['action_completed'],
            'word_completed': result['word_completed'],
            'blink_completed': result['blink_completed'],
            'time_remaining': result['time_remaining'],
            'verification_result': result['verification_result'],
            'exit_flag': result['exit_flag'],
            'duress_detected': result['duress_detected']
        }
        logger.debug(f"Emitting processed_frame: has_image={bool(disp_b64)}, has_debug={bool(debug_b64)}")
        emit('processed_frame', emit_data)
        if result['exit_flag']:
            active_sessions[session_id]['attempts'] = active_sessions[session_id].get('attempts', 0) + 1
            logger.debug(f"Attempt {active_sessions[session_id]['attempts']} for session {session_id}")
            requester_id = verification_codes[code]['requester_id']
            if result['duress_detected']:
                emit('verification_result', {
                    'result': 'FAIL',
                    'code': code,
                    'duress_detected': True
                }, room=requester_id)
                cleanup_session(session_id, code)
            elif result['verification_result'] == 'PASS':
                emit('verification_result', {
                    'result': 'PASS',
                    'code': code,
                    'duress_detected': False
                }, room=requester_id)
                cleanup_session(session_id, code)
            elif result['verification_result'] == 'FAIL' or result['time_remaining'] <= 0:
                if active_sessions[session_id]['attempts'] >= 3:
                    emit('verification_result', {
                        'result': 'FAIL',
                        'code': code,
                        'duress_detected': False
                    }, room=requester_id)
                    cleanup_session(session_id, code)
                else:
                    detector.reset()
                    logger.info(f"Reset detector after failure/timeout for session {session_id}, attempt {active_sessions[session_id]['attempts']}")
                    challenge_text, _, _, _ = detector.challenge_manager.get_challenge_status(
                        detector.head_pose, detector.blink_count, detector.last_speech or ""
                    )
                    emit('challenge', {'text': challenge_text})
    except Exception as e:
        logger.error(f"Error processing frame: {e}")
        emit('error', {'message': str(e)})

@socketio.on('verification_complete')
def handle_verification_complete(data):
    code = data.get('code')
    result = data.get('result')
    if code and code in verification_codes:
        requester_id = verification_codes[code]['requester_id']
        emit('verification_result', {
            'result': result,
            'code': code
        }, room=requester_id)
        for session_id, session_data in list(active_sessions.items()):
            if session_data.get('code') == code:
                cleanup_session(session_id, code)
        logger.info(f"Verification {code} completed with result: {result}")

if __name__ == '__main__':
    os.makedirs('static/qr_codes', exist_ok=True)
    cleanup_thread = threading.Thread(target=cleanup_inactive_sessions)
    cleanup_thread.daemon = True
    cleanup_thread.start()
    socketio.run(
        app,
        host=config.HOST,
        port=config.PORT,
        debug=config.BROWSER_DEBUG,
    )
