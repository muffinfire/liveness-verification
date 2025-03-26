"""Web application for liveness detection."""

import os
import cv2
import base64
import numpy as np
import logging
import random
import string
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import threading
import time
from typing import Dict, Any

from config import Config
from liveness_detector import LivenessDetector

app = Flask(__name__, 
            static_folder='static',
            template_folder='templates')
app.config['SECRET_KEY'] = 'liveness-detection-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

config = Config()

logging_level = logging.DEBUG if config.DEBUG else logging.INFO
logging.basicConfig(
    level=logging_level,
    format=config.LOGGING_FORMAT
)
logger = logging.getLogger(__name__)

active_sessions: Dict[str, Dict[str, Any]] = {}
verification_codes: Dict[str, Dict[str, Any]] = {}
last_log_time = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/verify/<code>')
def verify(code):
    logger.debug(f"Verify route called with code: {code}")
    if code not in verification_codes:
        return render_template('error.html', 
                               message="Invalid verification code", 
                               redirect_url="/")
    return render_template('verify.html', session_code=code)

@app.route('/check_code/<code>')
def check_code(code):
    logger.debug(f"Check code route called with code: {code}")
    is_valid = code in verification_codes
    return jsonify({'valid': is_valid})

@socketio.on('connect')
def handle_connect():
    session_id = request.sid
    logger.info(f"Client connected: {session_id}")

@socketio.on('disconnect')
def handle_disconnect():
    session_id = request.sid
    logger.info(f"Client disconnected: {session_id}")
    if session_id in active_sessions:
        if active_sessions[session_id]['detector'] is not None:
            active_sessions[session_id]['detector'].speech_recognizer.stop()
        del active_sessions[session_id]

@socketio.on('frame')
def handle_frame(data):
    session_id = request.sid
    if session_id not in active_sessions:
        logger.warning(f"Received frame from unknown session: {session_id}")
        return
    
    if active_sessions[session_id].get('attempts', 0) >= 3:
        emit('max_attempts_reached')
        return
    
    active_sessions[session_id]['last_activity'] = time.time()
    
    try:
        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
        image_array = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        
        detector = active_sessions[session_id]['detector']
        display_frame, exit_flag = detector.detect_liveness(frame)
        
        challenge_text, action_completed, word_completed, verification_result = \
            detector.challenge_manager.get_challenge_status()
        
        _, buffer = cv2.imencode('.jpg', display_frame)
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
        
        if exit_flag:
            active_sessions[session_id]['attempts'] = active_sessions[session_id].get('attempts', 0) + 1
            
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
        logger.info(f"Reset detector for session {session_id}, new challenge issued")
        emit('reset_confirmed')
    except Exception as e:
        logger.error(f"Error resetting verification: {e}")
        emit('error', {'message': str(e)})

@socketio.on('get_debug_status')
def handle_get_debug_status():
    logger.debug(f"Debug status requested: debug={config.DEBUG}, showDebugFrame={config.SHOW_DEBUG_FRAME}")
    emit('debug_status', {
        'debug': config.DEBUG,
        'showDebugFrame': config.SHOW_DEBUG_FRAME
    })

@socketio.on('generate_code')
def handle_generate_code():
    session_id = request.sid
    logger.info(f"Generate code request from session {session_id}")
    
    code = ''.join(random.choices(string.digits, k=6))
    verification_codes[code] = {
        'requester_id': session_id,
        'created_at': time.time(),
        'status': 'pending'
    }
    
    logger.info(f"Emitting verification code {code} to session {session_id}")
    emit('verification_code', {'code': code})
    
    def expire_code():
        time.sleep(600)
        if code in verification_codes and verification_codes[code]['status'] == 'pending':
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
            if current_time - session_data['last_activity'] > 300:
                inactive_sessions.append(session_id)
        
        for session_id in inactive_sessions:
            logger.info(f"Cleaning up inactive session: {session_id}")
            if active_sessions[session_id]['detector'] is not None:
                active_sessions[session_id]['detector'].speech_recognizer.stop()
            del active_sessions[session_id]
        
        time.sleep(60)

@socketio.on('join_verification')
def handle_join_verification(data):
    session_id = request.sid
    code = data.get('code')
    
    logger.info(f"Client {session_id} joining verification session with code: {code}")
    if not code or code not in verification_codes:
        emit('session_error', {'message': 'Invalid verification code'})
        return
    
    if verification_codes[code]['status'] == 'in-progress':
        emit('session_error', {'message': 'This verification session is already in progress'})
        return
    
    verification_codes[code]['status'] = 'in-progress'
    verification_codes[code]['verifier_id'] = session_id
    
    active_sessions[session_id] = {
        'code': code,
        'detector': None,
        'last_activity': time.time(),
        'attempts': 0
    }
    
    detector = LivenessDetector(config)
    active_sessions[session_id]['detector'] = detector
    
    join_room(code)
    requester_id = verification_codes[code]['requester_id']
    emit('verification_started', {'code': code}, room=requester_id)
    
    challenge_text, _, _, _ = detector.challenge_manager.get_challenge_status()
    emit('challenge', {'text': challenge_text})

@socketio.on('process_frame')
def handle_process_frame(data):
    session_id = request.sid
    code = data.get('code')
    
    current_time = time.time()
    if config.DEBUG and (session_id not in last_log_time or current_time - last_log_time.get(session_id, 0) >= 1.0):
        logger.debug(f"Processing frame for session {session_id}, code {code}")
        last_log_time[session_id] = current_time
    
    if session_id not in active_sessions:
        logger.warning(f"Received frame from unknown session: {session_id}")
        emit('session_error', {'message': 'Invalid session'})
        return
    
    active_sessions[session_id]['last_activity'] = time.time()
    
    try:
        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        logger.debug(f"Frame decoded: shape={frame.shape if frame is not None else 'None'}")
        
        detector = active_sessions[session_id]['detector']
        result = detector.process_frame(frame)
        
        display_frame = result['display_frame']
        debug_frame = result['debug_frame']
        
        if display_frame is not None:
            _, buffer_disp = cv2.imencode('.jpg', display_frame)
            disp_b64 = base64.b64encode(buffer_disp).decode('utf-8')
            logger.debug("Display frame encoded")
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
            'time_remaining': result['time_remaining'],
            'verification_result': result['verification_result'],
            'exit_flag': result['exit_flag']
        }
        logger.debug(f"Emitting processed_frame: has_image={bool(disp_b64)}, has_debug={bool(debug_b64)}")
        emit('processed_frame', emit_data)
        
        if result['exit_flag']:
            active_sessions[session_id]['attempts'] = active_sessions[session_id].get('attempts', 0) + 1
            if result['verification_result'] == 'PASS' or active_sessions[session_id]['attempts'] >= 3:
                if code and code in verification_codes:
                    verification_codes[code]['status'] = 'completed'
                    verification_codes[code]['result'] = result['verification_result']
                    requester_id = verification_codes[code]['requester_id']
                    emit('verification_result', {
                        'result': result['verification_result'],
                        'code': code
                    }, room=requester_id)
            elif result['verification_result'] == 'FAIL':
                detector.reset()  # Reset on failure to start a new challenge
                logger.info(f"Reset detector after failure for session {session_id}")
    except Exception as e:
        logger.error(f"Error processing frame: {e}")
        emit('error', {'message': str(e)})

@socketio.on('verification_complete')
def handle_verification_complete(data):
    code = data.get('code')
    result = data.get('result')
    
    if code and code in verification_codes:
        verification_codes[code]['status'] = 'completed'
        verification_codes[code]['result'] = result
        
        requester_id = verification_codes[code]['requester_id']
        emit('verification_result', {
            'result': result,
            'code': code
        }, room=requester_id)
        
        logger.info(f"Verification {code} completed with result: {result}")

if __name__ == '__main__':
    cleanup_thread = threading.Thread(target=cleanup_inactive_sessions)
    cleanup_thread.daemon = True
    cleanup_thread.start()
    
    socketio.run(
        app,
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
        certfile=config.CERTFILE,
        keyfile=config.KEYFILE
    )