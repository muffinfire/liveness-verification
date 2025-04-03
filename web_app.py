"""Web application for liveness detection.

This module implements the Flask web server and Socket.IO communication for the
liveness detection system. It handles client connections, processes video and audio
streams, and coordinates verification sessions between requesters and subjects.
"""
import eventlet
eventlet.monkey_patch()

# THEN: Import other libraries
import os
import cv2
import base64
import numpy as np
import logging
import random
import string
import qrcode
import time
import threading
import json
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from typing import Dict, Any, List, Tuple, Optional
from io import BytesIO

from config import Config
from liveness_detector import LivenessDetector


# Initialize Flask app
app = Flask(__name__,
            static_folder='static',
            template_folder='templates')
app.config['SECRET_KEY'] = 'liveness-detection-secret'

# Initialize socketio with optimized settings
socketio = SocketIO(
    app, 
    cors_allowed_origins="*",
    async_mode='eventlet',  # Use eventlet for better performance with many concurrent connections
    ping_timeout=60,        # Increase ping timeout for more stable connections
    ping_interval=25,       # Reduce ping interval for faster disconnection detection
    max_http_buffer_size=5 * 1024 * 1024  # 5MB buffer for larger frames if needed
)

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

# Cache for encoded frames to reduce redundant processing
frame_cache = {}
FRAME_CACHE_SIZE = 30  # Maximum number of frames to cache (increased from 20)
FRAME_CACHE_TTL = 5   # Time to live in seconds (increased from 5)

# JPEG encoding quality for different network conditions - UPDATED: reduced quality values
JPEG_QUALITY = {
    'high': 30,    # Reduced from 90
    'medium': 30,  # Reduced from 80
    'low': 30,     # Reduced from 70
    'very_low': 30, # Reduced from 60
    'ultra_low': 30 # New ultra-low setting
}

# Default network quality
DEFAULT_NETWORK_QUALITY = 'medium'

# Debug frame quality reduction factor
DEBUG_QUALITY_REDUCTION = 10  # Reduce debug frame quality by this amount compared to main frame

# Network quality logging
last_network_log_time = {}
NETWORK_LOG_INTERVAL = 5  # Log network quality every 5 seconds

@app.route('/')
def index():
    """Render the landing page."""
    return render_template('index.html')

@app.route('/verify/<code>')
def verify(code):
    """Render the verification page for a given code.
    
    Args:
        code: The 6-digit verification code
        
    Returns:
        Rendered verification page or error page
    """
    if not code.isdigit() or len(code) != 6:
        return render_template('error.html', message="Invalid code format", redirect_url="/")
    if code not in verification_codes or verification_codes[code]['status'] != 'pending':
        return render_template('error.html', message="Invalid or expired verification code", redirect_url="/")
    return render_template('verify.html', session_code=code)

@app.route('/check_code/<code>')
def check_code(code):
    """Check if a verification code is valid.
    
    Args:
        code: The verification code to check
        
    Returns:
        JSON response indicating if the code is valid
    """
    logger.debug(f"Check code route called with code: {code}")
    is_valid = code in verification_codes and verification_codes[code]['status'] == 'pending'
    return jsonify({'valid': is_valid})

def cleanup_session(session_id: str, code: str = None):
    """Clean up resources associated with a session.
    
    Args:
        session_id: The Socket.IO session ID
        code: Optional verification code associated with the session
    """
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
    """Handle client connection to Socket.IO."""
    session_id = request.sid
    logger.info(f"Client connected: {session_id}")

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection from Socket.IO."""
    session_id = request.sid
    logger.info(f"Client disconnected: {session_id}")
    cleanup_session(session_id)

@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    """Process audio chunk from client.
    
    Args:
        data: Dictionary containing audio data and metadata
    """
    session_id = request.sid
    
    # Rate limit debug logging
    current_time = time.time()
    if session_id not in last_log_time or current_time - last_log_time.get(session_id, 0) > 5:
        logger.debug(f"Received audio chunk event from session: {session_id}")
        last_log_time[session_id] = current_time
        
    if session_id not in active_sessions:
        logger.warning(f"Received audio chunk from unknown session: {session_id}")
        return
    try:
        audio_chunk = base64.b64decode(data['audio'])
        detector = active_sessions[session_id]['detector']
        detector.speech_recognizer.process_audio_chunk(audio_chunk)
    except Exception as e:
        logger.error(f"Error processing audio chunk from session {session_id}: {e}")

@socketio.on('client_network_quality')
def handle_client_network_quality(data):
    """Handle network quality information from client.
    
    Args:
        data: Dictionary containing network quality information
    """
    session_id = request.sid
    if session_id not in active_sessions:
        return
    
    quality = data.get('quality')
    latency = data.get('latency', 0)
    
    if quality and quality in JPEG_QUALITY:
        # Store network quality in session data
        active_sessions[session_id]['network_quality'] = quality
        
        # Log network quality updates (rate-limited)
        current_time = time.time()
        if session_id not in last_log_time or current_time - last_log_time.get(session_id, 0) > 10:
            logger.debug(f"Client {session_id} reported network quality: {quality}, latency: {latency}ms")
            last_log_time[session_id] = current_time
        
        # Always log network quality periodically for debugging
        if session_id not in last_network_log_time or current_time - last_network_log_time.get(session_id, 0) > NETWORK_LOG_INTERVAL:
            logger.info(f"NETWORK STATS - Session: {session_id}, Quality: {quality}, Latency: {latency}ms, JPEG Quality: {JPEG_QUALITY[quality]}")
            last_network_log_time[session_id] = current_time

@socketio.on('frame')
def handle_frame(data):
    """Legacy frame handler (deprecated).
    
    Args:
        data: Dictionary containing frame data
    """
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
        
        # Use network quality from client if provided, otherwise use default
        network_quality = data.get('network_quality', DEFAULT_NETWORK_QUALITY)
        jpeg_quality = JPEG_QUALITY.get(network_quality, JPEG_QUALITY[DEFAULT_NETWORK_QUALITY])
        
        # Encode with appropriate quality
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
        _, buffer = cv2.imencode('.jpg', frame, encode_params)
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
    """Reset the verification process.
    
    Args:
        data: Dictionary containing reset request data
    """
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
    """Send debug status to client."""
    logger.debug("Debug status requested")
    emit('debug_status', {
        'debug': True,  # UPDATED: Force debug mode to true for testing
        'showDebugFrame': config.SHOW_DEBUG_FRAME
    })

@socketio.on('generate_code')
def handle_generate_code():
    """Generate a verification code and QR code.
    
    Creates a unique 6-digit verification code and associated QR code,
    then sends them to the client.
    """
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
    
    # Start a thread to expire the code after 10 minutes
    def expire_code():
        time.sleep(600)  # 10 minutes
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
    """Periodically clean up inactive sessions to free resources."""
    while True:
        current_time = time.time()
        inactive_sessions = []
        
        # Find inactive sessions
        for session_id, session_data in active_sessions.items():
            if current_time - session_data['last_activity'] > config.SESSION_TIMEOUT:
                inactive_sessions.append(session_id)
        
        # Clean up inactive sessions
        for session_id in inactive_sessions:
            cleanup_session(session_id)
        
        # Clean up expired frame cache entries
        expired_keys = []
        for key, (timestamp, _) in frame_cache.items():
            if current_time - timestamp > FRAME_CACHE_TTL:
                expired_keys.append(key)
        
        for key in expired_keys:
            del frame_cache[key]
            
        # Sleep before next cleanup cycle
        time.sleep(10)

@socketio.on('join_verification')
def handle_join_verification(data):
    """Handle a client joining a verification session.
    
    Args:
        data: Dictionary containing join request data
    """
    session_id = request.sid
    code = data.get('code')
    client_info = data.get('clientInfo', {})
    
    logger.info(f"Client {session_id} joining verification session with code: {code}")
    
    if not code or code not in verification_codes or verification_codes[code]['status'] != 'pending':
        emit('session_error', {'message': 'Invalid or expired verification code'})
        return
    
    # Update verification code status
    verification_codes[code]['status'] = 'in-progress'
    verification_codes[code]['verifier_id'] = session_id
    verification_codes[code]['client_info'] = client_info
    
    # Initialize session data
    active_sessions[session_id] = {
        'code': code,
        'detector': None,
        'last_activity': time.time(),
        'attempts': 0,
        'network_quality': DEFAULT_NETWORK_QUALITY,
        'client_info': client_info
    }
    
    # Join the room for this verification code
    join_room(code)
    
    # Notify the requester that verification has started
    requester_id = verification_codes[code]['requester_id']
    emit('verification_started', {
        'code': code, 
        'partner_video': True  # Flag to indicate partner video should be shown
    }, room=requester_id)
    
    # Initialize the liveness detector
    detector = LivenessDetector(config)
    active_sessions[session_id]['detector'] = detector
    
    # Get the initial challenge
    challenge_text, _, _, _ = detector.challenge_manager.get_challenge_status(
        detector.head_pose, detector.blink_count, detector.last_speech or ""
    )
    
    # Send the challenge to the client
    emit('challenge', {'text': challenge_text})

# Function to resize frame based on network quality
def resize_frame_by_quality(frame, quality):
    """Resize frame based on network quality.
    
    Args:
        frame: The original frame
        quality: Network quality level
        
    Returns:
        Resized frame
    """
    if quality == 'ultra_low':
        return cv2.resize(frame, (160, 120))
    elif quality == 'very_low':
        return cv2.resize(frame, (240, 180))
    elif quality == 'low':
        return cv2.resize(frame, (320, 240))
    elif quality == 'medium':
        return cv2.resize(frame, (480, 360))
    return frame  # No resize for high quality

@socketio.on('process_frame')
def handle_process_frame(data):
    """Process a video frame from the client.
    
    Args:
        data: Dictionary containing frame data and metadata
    """
    session_id = request.sid
    code = data.get('code')
    timestamp = data.get('timestamp')
    detection_mode = data.get('detectionMode', 'normal')
    
    # Validate session
    if session_id not in active_sessions or active_sessions[session_id]['code'] != code:
        logger.warning(f"Received frame from unknown or invalid session: {session_id}, code: {code}")
        emit('session_error', {'message': 'Invalid session or code'})
        return
    
    # Check if max attempts reached
    if active_sessions[session_id].get('attempts', 0) >= 3:
        emit('max_attempts_reached')
        cleanup_session(session_id, code)
        return
    
    # Update last activity timestamp
    active_sessions[session_id]['last_activity'] = time.time()
    
    # Get network quality from client if provided, otherwise use stored or default
    network_quality = data.get('networkQuality', 
                              active_sessions[session_id].get('network_quality', 
                                                            DEFAULT_NETWORK_QUALITY))
    
    # Update stored network quality
    active_sessions[session_id]['network_quality'] = network_quality
    
    # Decode image data
    try:
        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
    except Exception as e:
        logger.error(f"Failed to decode base64 image data: {e}")
        emit('error', {'message': 'Invalid image data'})
        return
    
    # Convert to numpy array
    nparr = np.frombuffer(image_bytes, np.uint8)
    if nparr.size == 0:
        logger.debug("Received empty frame buffer; waiting for next frame")
        emit('waiting_for_camera', {'message': 'Camera not ready yet'})
        return
    
    # Decode frame with optimized retry logic
    frame = None
    max_retries = 3  # Reduced from 10 to 3 for faster processing
    retry_delay = 0.05  # Reduced from 0.1 to 0.05 for faster processing
    
    for attempt in range(max_retries):
        try:
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                if attempt == max_retries - 1:  # Only log on last attempt
                    logger.debug(f"Failed to decode frame on attempt {attempt + 1}/{max_retries}")
                time.sleep(retry_delay)
                continue
            break
        except Exception as e:
            if attempt == max_retries - 1:  # Only log on last attempt
                logger.error(f"Error decoding frame on attempt {attempt + 1}/{max_retries}: {e}")
            time.sleep(retry_delay)
    
    if frame is None:
        logger.error(f"Failed to decode frame after {max_retries} attempts")
        emit('error', {'message': 'Unable to process frame'})
        return
    
    # Process the frame
    try:
        detector = active_sessions[session_id]['detector']
        
        # Update detector processing mode based on client detection mode
        if detection_mode == 'blink' and hasattr(detector, 'update_processing_mode'):
            detector.update_processing_mode('blink_detection')
        elif detection_mode == 'action' and hasattr(detector, 'update_processing_mode'):
            detector.update_processing_mode('action_detection')
        
        # Process the frame
        result = detector.process_frame(frame)
        frame = result['frame']
        debug_frame = result['debug_frame']
        
        # Process and encode display frame if available
        disp_b64 = None
        if frame is not None:
            # Use appropriate JPEG quality based on network conditions
            jpeg_quality = JPEG_QUALITY.get(network_quality, JPEG_QUALITY[DEFAULT_NETWORK_QUALITY])

            # Image format
            image_format = 'jpeg'
            
            # Resize frame based on network quality
            frame = resize_frame_by_quality(frame, network_quality)
            
            # Log frame size and quality periodically
            current_time = time.time()
            if session_id not in last_network_log_time or current_time - last_network_log_time.get(session_id, 0) > NETWORK_LOG_INTERVAL:
                logger.info(f"FRAME STATS - Session: {session_id}, Quality: {network_quality}, Size: {frame.shape[1]}x{frame.shape[0]}, JPEG Quality: {jpeg_quality}")
                last_network_log_time[session_id] = current_time
            
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
            
            # Generate a cache key based on frame content and quality
            frame_hash = hash(frame.tobytes()) % 10000000  # Simple hash of frame content
            cache_key = f"{frame_hash}_{jpeg_quality}"
            
            # Check if we have this frame cached
            current_time = time.time()
            if cache_key in frame_cache and current_time - frame_cache[cache_key][0] < FRAME_CACHE_TTL:
                disp_b64 = frame_cache[cache_key][1]
                logger.debug("Using cached display frame")
            else:
                # Try WebP encoding first if supported
                try:
                    _, buffer_disp = cv2.imencode('.webp', frame, [cv2.IMWRITE_WEBP_QUALITY, jpeg_quality])
                    disp_b64 = base64.b64encode(buffer_disp).decode('utf-8')
                    image_format = 'webp'
                except:
                    # Fall back to JPEG if WebP is not supported
                    _, buffer_disp = cv2.imencode('.jpg', frame, encode_params)
                    disp_b64 = base64.b64encode(buffer_disp).decode('utf-8')
                    image_format = 'jpeg'
                
                # Cache the encoded frame
                if len(frame_cache) >= FRAME_CACHE_SIZE:
                    # Remove oldest entry if cache is full
                    oldest_key = min(frame_cache.keys(), key=lambda k: frame_cache[k][0])
                    del frame_cache[oldest_key]
                
                frame_cache[cache_key] = (current_time, disp_b64)
            
            # Send partner video frame to requester if available
            if code in verification_codes and 'requester_id' in verification_codes[code]:
                requester_id = verification_codes[code]['requester_id']
                # Send the partner's video frame and challenge info to be displayed in the QR code background
                challenge_text = result['challenge_text'] if result['challenge_text'] else "Waiting for challenge..."
                action_text = "Waiting for action..."
                word_text = "Waiting for word..."
                
                if challenge_text and "and say" in challenge_text.lower():
                    parts = challenge_text.split("and say")
                    if len(parts) == 2:
                        action_text = parts[0].strip()
                        word_text = "Say " + parts[1].strip()
                
                # Send optimized partner video frame
                emit('partner_video_frame', {
                    'image': f"data:image/{image_format};base64,{disp_b64}",
                    'code': code,
                    'action_text': action_text,
                    'word_text': word_text,
                    'challenge_text': challenge_text,
                    'timestamp': timestamp  # Echo back timestamp for latency calculation
                }, room=requester_id)
        else:
            logger.debug("Display frame is None")
        
        # Process and encode debug frame if needed
        debug_b64 = None
        if debug_frame is not None and config.SHOW_DEBUG_FRAME:
            # Use lower quality for debug frames to save bandwidth
            debug_quality = max(50, JPEG_QUALITY.get(network_quality, 70) - DEBUG_QUALITY_REDUCTION)
            
            # Resize debug frame based on network quality
            debug_frame = resize_frame_by_quality(debug_frame, network_quality)
            
            debug_encode_params = [cv2.IMWRITE_JPEG_QUALITY, debug_quality]
            _, buffer_dbg = cv2.imencode('.jpg', debug_frame, debug_encode_params)
            debug_b64 = base64.b64encode(buffer_dbg).decode('utf-8')
        
        # Prepare response data
        emit_data = {
            'image': f"data:image/jpeg;base64,{disp_b64}" if disp_b64 else None,
            'debug_image': f"data:image/jpeg;base64,{debug_b64}" if debug_b64 else None,
            'challenge': result['challenge_text'],
            'action_completed': result['action_completed'],
            'word_completed': result['word_completed'],
            'blink_completed': result.get('blink_completed', False),
            'time_remaining': result['time_remaining'],
            'verification_result': result['verification_result'],
            'exit_flag': result['exit_flag'],
            'duress_detected': result['duress_detected'],
            'timestamp': timestamp  # Echo back timestamp for latency calculation
        }
        
        # Send processed frame data to client
        emit('processed_frame', emit_data)
        
        # Send network quality information to client
        emit('network_quality', {
            'quality': network_quality,
            'jpeg_quality': jpeg_quality
        })
        
        # Handle verification completion
        if result['exit_flag']:
            active_sessions[session_id]['attempts'] = active_sessions[session_id].get('attempts', 0) + 1
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
    """Handle verification completion notification.
    
    Args:
        data: Dictionary containing verification result data
    """
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
    # Create directory for QR codes if it doesn't exist
    os.makedirs('static/qr_codes', exist_ok=True)
    
    # Start session cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_inactive_sessions)
    cleanup_thread.daemon = True
    cleanup_thread.start()
    
    # Use eventlet for better performance with many concurrent connections
    import eventlet
    eventlet.monkey_patch()
    
    # Run the Socket.IO server
    socketio.run(
        app,
        host=config.HOST,
        port=config.PORT,
        debug=config.BROWSER_DEBUG
    )
