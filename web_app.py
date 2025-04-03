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
import time
import threading
import json
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from typing import Dict, Any, Tuple, Optional
from io import BytesIO

# Assuming config and liveness_detector are in the same directory or PYTHONPATH
from config import Config
from liveness_detector import LivenessDetector

# Initialize Flask app
app = Flask(__name__,
            static_folder='static',
            template_folder='templates')
app.config['SECRET_KEY'] = 'liveness-detection-secret' # Change in production

# Initialize socketio with eventlet for async mode
socketio = SocketIO(
    app,
    cors_allowed_origins="*", # Restrict in production
    async_mode='eventlet',
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=5 * 1024 * 1024 # 5MB buffer for frames
)

# Initialize config
config = Config()

# Configure logging
logging.basicConfig(level=config.APP_LOGGING_LEVEL, format=config.LOGGING_FORMAT)
# Set specific levels for other modules if needed
# logging.getLogger('liveness_detector').setLevel(...)
logger = logging.getLogger(__name__)

# In-memory storage (Replace with persistent storage in production if needed)
active_sessions: Dict[str, Dict[str, Any]] = {}
verification_codes: Dict[str, Dict[str, Any]] = {}
frame_cache: Dict[str, Tuple[float, str]] = {} # Cache for encoded frames: {cache_key: (timestamp, base64_string)}

# Cache settings
FRAME_CACHE_SIZE = 50  # Max number of frames to cache
FRAME_CACHE_TTL = 3   # Time to live in seconds

# Target widths for resizing based on network quality (adjust as needed)
# Values represent the target width for landscape mode (4:3 aspect ratio)
TARGET_WIDTHS = {
    'high': 640,
    'medium': 480,
    'low': 320,
    'very_low': 240
}

# JPEG encoding quality for different network conditions
JPEG_QUALITY_MAP = {
    'high': 80, # Slightly higher quality for 'high'
    'medium': 65,
    'low': 50,
    'very_low': 35
}
DEFAULT_NETWORK_QUALITY = 'medium'

# Debug frame settings
DEBUG_QUALITY_REDUCTION_FACTOR = 0.7 # Reduce quality by 30% compared to main frame
DEBUG_TARGET_WIDTH_FACTOR = 0.8 # Reduce width by 20% compared to main frame

# Logging intervals
NETWORK_LOG_INTERVAL = 10  # Log network quality every 10 seconds
last_network_log_time: Dict[str, float] = {}

# --- Utility Functions ---

def generate_code(length: int = 6) -> str:
    """Generates a random digit code."""
    return ''.join(random.choices(string.digits, k=length))

def resize_with_aspect_ratio(image, target_width: Optional[int] = None, target_height: Optional[int] = None, inter=cv2.INTER_AREA):
    """Resizes an image while preserving aspect ratio."""
    (h, w) = image.shape[:2]
    if w == 0 or h == 0:
        return image # Cannot resize empty image

    if target_width is None and target_height is None:
        return image # No resize needed

    if target_width is None:
        if target_height >= h: return image # Don't upscale height
        r = target_height / float(h)
        dim = (int(w * r), target_height)
    else:
        if target_width >= w: return image # Don't upscale width
        r = target_width / float(w)
        dim = (target_width, int(h * r))

    # Ensure dimensions are positive
    if dim[0] <= 0 or dim[1] <= 0:
         logger.warning(f"Invalid resize dim calculated: {dim}. Original: {w}x{h}, TargetW: {target_width}, TargetH: {target_height}")
         return image # Return original if calculation fails

    resized = cv2.resize(image, dim, interpolation=inter)
    return resized

def encode_frame(frame, quality: int, format='.jpg') -> Optional[str]:
    """Encodes a frame to base64 string."""
    if frame is None:
        return None
    try:
        encode_params = []
        mime_type = ''
        if format == '.jpg':
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
            mime_type = 'image/jpeg'
        elif format == '.webp':
             encode_params = [cv2.IMWRITE_WEBP_QUALITY, quality]
             mime_type = 'image/webp'
        else:
             logger.warning(f"Unsupported encoding format: {format}")
             return None # Or fallback to JPEG

        success, buffer = cv2.imencode(format, frame, encode_params)
        if not success:
             logger.error(f"Failed to encode frame to {format}")
             # Attempt fallback to JPEG if WEBP failed
             if format == '.webp':
                  logger.info("Falling back to JPEG encoding for frame.")
                  return encode_frame(frame, quality, format='.jpg')
             return None

        encoded_string = base64.b64encode(buffer).decode('utf-8')
        return f"data:{mime_type};base64,{encoded_string}"
    except Exception as e:
        logger.error(f"Error encoding frame to {format}: {e}", exc_info=True)
        return None

def cleanup_session(session_id: str):
    """Cleans up resources for a disconnected or completed session."""
    if session_id in active_sessions:
        session_data = active_sessions.pop(session_id) # Remove session atomically
        code = session_data.get('code')
        logger.info(f"Cleaning up session {session_id} (Code: {code})")

        # Stop detector resources if they exist
        detector = session_data.get('detector')
        if detector and hasattr(detector, 'stop'):
            try:
                detector.stop() # Assuming detector has a stop method
            except Exception as e:
                logger.error(f"Error stopping detector for session {session_id}: {e}")

        # Clean up frame cache associated with this session? (Probably not necessary)

        # Update verification code status if applicable
        if code and code in verification_codes:
            verification_codes[code]['status'] = 'completed' # Mark as completed
            # Optionally remove from verification_codes after some time?
            # Or remove QR code file
            qr_path = f"static/qr_codes/{code}.png"
            if os.path.exists(qr_path):
                 try:
                     os.remove(qr_path)
                     logger.info(f"Removed QR code: {qr_path}")
                 except OSError as e:
                     logger.error(f"Error removing QR code {qr_path}: {e}")

        # Clean up network log time entry
        if session_id in last_network_log_time:
             del last_network_log_time[session_id]

    else:
        logger.warning(f"Attempted to clean up non-existent session: {session_id}")

def cleanup_inactive_sessions_task():
    """Background task to clean up inactive sessions."""
    while True:
        try:
            current_time = time.time()
            inactive_session_ids = []
            for session_id, session_data in list(active_sessions.items()): # Iterate over a copy
                last_activity = session_data.get('last_activity', 0)
                if current_time - last_activity > config.SESSION_TIMEOUT:
                    logger.info(f"Session {session_id} timed out (inactive for {current_time - last_activity:.0f}s).")
                    inactive_session_ids.append(session_id)

            for session_id in inactive_session_ids:
                cleanup_session(session_id)

            # Clean up expired frame cache entries
            expired_keys = [key for key, (timestamp, _) in frame_cache.items() if current_time - timestamp > FRAME_CACHE_TTL]
            for key in expired_keys:
                 if key in frame_cache: # Check again in case deleted by another thread
                     del frame_cache[key]
            if expired_keys:
                 logger.debug(f"Cleaned up {len(expired_keys)} expired frame cache entries.")

        except Exception as e:
            logger.error(f"Error in cleanup task: {e}", exc_info=True)

        eventlet.sleep(30) # Check every 30 seconds


# --- Flask Routes ---

@app.route('/')
def index():
    """Render the landing page."""
    return render_template('index.html')

@app.route('/verify/<code>')
def verify(code):
    """Render the verification page."""
    if not code or not code.isdigit() or len(code) != 6:
        return render_template('error.html', message="Invalid verification code format.", redirect_url="/"), 400
    if code not in verification_codes or verification_codes[code].get('status') != 'pending':
        return render_template('error.html', message="Verification code is invalid or has expired.", redirect_url="/"), 404
    return render_template('verify.html', session_code=code)

@app.route('/check_code/<code>')
def check_code(code):
    """Check if a verification code is valid and pending (API endpoint)."""
    is_valid = code in verification_codes and verification_codes[code].get('status') == 'pending'
    return jsonify({'valid': is_valid})

# --- Socket.IO Event Handlers ---

@socketio.on('connect')
def handle_connect():
    session_id = request.sid
    logger.info(f"Client connected: {session_id}")
    # Initialize session data structure immediately
    active_sessions[session_id] = {
        'last_activity': time.time(),
        'network_quality': DEFAULT_NETWORK_QUALITY,
        'orientation': {'isPortrait': False, 'width': 0, 'height': 0}, # Default orientation
        'attempts': 0
    }

@socketio.on('disconnect')
def handle_disconnect():
    session_id = request.sid
    logger.info(f"Client disconnected: {session_id}")
    cleanup_session(session_id)

@socketio.on('generate_code')
def handle_generate_code():
    """Generate verification code, QR code, and store."""
    session_id = request.sid
    code = generate_code()
    logger.info(f"Generating code {code} for requester {session_id}")

    # Ensure directory exists
    os.makedirs('static/qr_codes', exist_ok=True)

    verification_url = f"{request.url_root}verify/{code}".replace("http://", "https://", 1) # Use request root and ensure https
    qr_path = f"static/qr_codes/{code}.png"

    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(verification_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_img.save(qr_path)
    except Exception as e:
        logger.error(f"Failed to generate QR code for {code}: {e}", exc_info=True)
        emit('error', {'message': 'Failed to generate QR code.'})
        return

    verification_codes[code] = {
        'requester_id': session_id,
        'created_at': time.time(),
        'status': 'pending'
    }

    emit('verification_code', {
        'code': code,
        'qr_code': f"/static/qr_codes/{code}.png", # Relative path for client
         # Indicate if partner video background is enabled in config
        'enable_video_background': config.SHOW_PARTNER_VIDEO_IN_QR
    })

    # Start expiration timer for the code
    def expire_code_task(exp_code):
        eventlet.sleep(config.CODE_EXPIRATION_TIME) # Use config value
        if exp_code in verification_codes and verification_codes[exp_code]['status'] == 'pending':
            logger.info(f"Verification code {exp_code} expired.")
            if os.path.exists(qr_path):
                try:
                    os.remove(qr_path)
                except OSError as e:
                    logger.error(f"Error removing QR code for expired code {exp_code}: {e}")
            del verification_codes[exp_code]
            # Notify requester? Maybe not necessary.
    eventlet.spawn(expire_code_task, code) # Spawn as greenlet

@socketio.on('join_verification')
def handle_join_verification(data):
    """Handle verifier client joining a session."""
    session_id = request.sid
    code = data.get('code')
    client_info = data.get('clientInfo', {})

    logger.info(f"Verifier {session_id} attempting to join session with code: {code}")

    if not code or code not in verification_codes or verification_codes[code].get('status') != 'pending':
        logger.warning(f"Invalid/expired code {code} provided by {session_id}")
        emit('session_error', {'message': 'Invalid or expired verification code.'})
        return

    requester_id = verification_codes[code].get('requester_id')
    if not requester_id:
         logger.error(f"Requester ID not found for code {code}")
         emit('session_error', {'message': 'Internal error: Session data missing.'})
         return

    # Update code status and link verifier
    verification_codes[code]['status'] = 'in-progress'
    verification_codes[code]['verifier_id'] = session_id
    verification_codes[code]['client_info'] = client_info
    verification_codes[code]['start_time'] = time.time()

    # Update session data for the verifier
    if session_id not in active_sessions: # Should exist from 'connect' but double-check
         active_sessions[session_id] = {'last_activity': time.time()}

    active_sessions[session_id].update({
        'code': code,
        'detector': None, # Will be initialized shortly
        'attempts': 0,
        'network_quality': DEFAULT_NETWORK_QUALITY,
        'client_info': client_info,
        'orientation': { # Get initial orientation from clientInfo
            'isPortrait': client_info.get('isPortrait', False),
            'width': client_info.get('screenWidth', 0), # Or use viewport width?
            'height': client_info.get('screenHeight', 0)
        }
    })
    active_sessions[session_id]['last_activity'] = time.time()

    logger.info(f"Verifier {session_id} joined session {code}. Requester: {requester_id}. Initial Orientation: {'Portrait' if active_sessions[session_id]['orientation']['isPortrait'] else 'Landscape'}")

    # Add verifier to the room specific to this code
    join_room(code)

    # Notify the requester that the verifier has joined
    emit('verification_started', {
        'code': code,
        'partner_video': config.SHOW_PARTNER_VIDEO_IN_QR # Send flag based on config
    }, room=requester_id)

    # Initialize Liveness Detector
    try:
        detector = LivenessDetector(config=config) # Pass config
        active_sessions[session_id]['detector'] = detector
        challenge_text = detector.get_initial_challenge() # Get first challenge
        logger.info(f"Liveness detector initialized for {session_id}. Initial challenge: {challenge_text}")
        emit('challenge', {'text': challenge_text})
    except Exception as e:
         logger.error(f"Failed to initialize LivenessDetector for {session_id}: {e}", exc_info=True)
         emit('session_error', {'message': 'Failed to start verification process.'})
         # Clean up partially started session
         cleanup_session(session_id)


@socketio.on('process_frame')
def handle_process_frame(data):
    """Main handler for processing video frames from the verifier."""
    start_time = time.time()
    session_id = request.sid
    code = data.get('code')

    # --- Basic Validation ---
    if session_id not in active_sessions or active_sessions[session_id].get('code') != code:
        logger.warning(f"Frame from invalid session: {session_id}, Code: {code}")
        emit('session_error', {'message': 'Invalid session or code.'})
        return

    detector = active_sessions[session_id].get('detector')
    if not detector:
        logger.error(f"Detector not initialized for session {session_id}")
        emit('session_error', {'message': 'Verification process not ready.'})
        return

    if active_sessions[session_id]['attempts'] >= config.MAX_VERIFICATION_ATTEMPTS:
        logger.warning(f"Max attempts reached for session {session_id}, ignoring frame.")
        # Ensure client knows max attempts were reached
        emit('max_attempts_reached')
        # No cleanup here, disconnect or timeout will handle it
        return

    active_sessions[session_id]['last_activity'] = time.time()

    # --- Get Frame Data and Metadata ---
    image_b64 = data.get('image', '').split(',')[-1] # Get data part of base64 string
    timestamp = data.get('timestamp') # Client timestamp for latency calculation
    is_portrait = data.get('isPortrait', active_sessions[session_id]['orientation'].get('isPortrait', False))
    network_quality = data.get('networkQuality', active_sessions[session_id].get('network_quality', DEFAULT_NETWORK_QUALITY))

    # Update session orientation and network quality
    active_sessions[session_id]['orientation']['isPortrait'] = is_portrait
    active_sessions[session_id]['network_quality'] = network_quality

    # --- Decode Frame ---
    try:
        if not image_b64:
            logger.warning(f"Received empty image data from {session_id}")
            return # Ignore empty frames
        image_bytes = base64.b64decode(image_b64)
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            logger.warning(f"Failed to decode frame from {session_id}")
            return
    except Exception as e:
        logger.error(f"Error decoding frame from {session_id}: {e}", exc_info=True)
        emit('error', {'message': 'Failed to process image data.'})
        return

    processing_start_time = time.time()

    # --- Process Frame with Liveness Detector ---
    try:
        orientation_data = active_sessions[session_id]['orientation']
        result = detector.process_frame(frame, orientation_data) # Pass orientation
        # result contains: frame, debug_frame, challenge_text, action_completed, etc.
    except Exception as e:
        logger.error(f"Error during detector processing for {session_id}: {e}", exc_info=True)
        emit('error', {'message': 'Error during liveness detection.'})
        return

    processing_time = time.time() - processing_start_time

    # --- Prepare Frames for Sending (Resize & Encode) ---
    encoding_start_time = time.time()

    # Determine target width and quality based on network and orientation
    target_base_width = TARGET_WIDTHS.get(network_quality, TARGET_WIDTHS[DEFAULT_NETWORK_QUALITY])
    jpeg_quality = JPEG_QUALITY_MAP.get(network_quality, JPEG_QUALITY_MAP[DEFAULT_NETWORK_QUALITY])

    # Adjust target width for portrait mode if needed (detector might handle this internally)
    # If the detector doesn't rotate, we might adjust target dimensions here.
    # Assuming detector provides frames in correct orientation for display:
    target_width_main = target_base_width

    # Resize main frame (result['frame'])
    resized_main_frame = resize_with_aspect_ratio(result.get('frame'), target_width=target_width_main)

    # Encode main frame (try WebP first for partner, fallback to JPEG)
    encoded_main_frame_partner = encode_frame(resized_main_frame, jpeg_quality, format='.webp')
    encoded_main_frame_verifier = encode_frame(resized_main_frame, jpeg_quality, format='.jpg') # Verifier gets JPEG

    # Prepare debug frame if needed
    encoded_debug_frame = None
    if config.SHOW_DEBUG_FRAME and result.get('debug_frame') is not None:
        debug_frame = result['debug_frame']
        # Calculate reduced quality and width for debug frame
        debug_quality = int(jpeg_quality * DEBUG_QUALITY_REDUCTION_FACTOR)
        debug_target_width = int(target_width_main * DEBUG_TARGET_WIDTH_FACTOR)
        resized_debug_frame = resize_with_aspect_ratio(debug_frame, target_width=debug_target_width)
        encoded_debug_frame = encode_frame(resized_debug_frame, debug_quality, format='.jpg')

    encoding_time = time.time() - encoding_start_time

    # --- Emit Results ---
    emit_start_time = time.time()

    # Data for the verifier client
    verifier_data = {
        'image': encoded_main_frame_verifier,
        'debug_image': encoded_debug_frame,
        'challenge': result.get('challenge_text'),
        'action_completed': result.get('action_completed', False),
        'word_completed': result.get('word_completed', False),
        'blink_completed': result.get('blink_completed', False),
        'time_remaining': result.get('time_remaining', 0),
        'verification_result': result.get('verification_result', 'PENDING'),
        'exit_flag': result.get('exit_flag', False),
        'duress_detected': result.get('duress_detected', False),
        'timestamp': timestamp, # Echo back timestamp for latency calculation
        'isPortrait': is_portrait # Confirm orientation used
    }
    emit('processed_frame', verifier_data, room=session_id)

    # Data for the requester client (partner video)
    if config.SHOW_PARTNER_VIDEO_IN_QR and code in verification_codes:
         requester_id = verification_codes[code].get('requester_id')
         if requester_id:
             partner_data = {
                 'image': encoded_main_frame_partner, # Send WebP if available
                 'code': code,
                 'challenge_text': result.get('challenge_text'), # Send current challenge
                 'timestamp': timestamp,
                 'isPortrait': is_portrait
             }
             emit('partner_video_frame', partner_data, room=requester_id)

    emit_time = time.time() - emit_start_time
    total_time = time.time() - start_time

    # Log performance periodically
    current_time = time.time()
    if session_id not in last_network_log_time or current_time - last_network_log_time.get(session_id, 0) > NETWORK_LOG_INTERVAL:
         logger.info(f"PERF STATS - Session: {session_id}, Quality: {network_quality}, TargetW: {target_width_main}, JPEG-Q: {jpeg_quality}, Orient: {'P' if is_portrait else 'L'}")
         logger.info(f"PERF TIMES - Total: {total_time:.3f}s, Processing: {processing_time:.3f}s, Encoding: {encoding_time:.3f}s, Emit: {emit_time:.3f}s")
         last_network_log_time[session_id] = current_time


    # --- Handle Verification Completion/Failure ---
    if result.get('exit_flag'):
        verification_result = result.get('verification_result', 'FAIL')
        duress_detected = result.get('duress_detected', False)
        logger.info(f"Verification ended for session {session_id}. Result: {verification_result}, Duress: {duress_detected}")

        active_sessions[session_id]['attempts'] += 1
        attempt_count = active_sessions[session_id]['attempts']

        requester_id = verification_codes.get(code, {}).get('requester_id')

        # Notify requester immediately of the final result
        if requester_id:
             emit('verification_result', {
                 'result': 'FAIL' if duress_detected else verification_result, # Override PASS if duress
                 'code': code,
                 'duress_detected': duress_detected
             }, room=requester_id)

        # Check if final attempt or pass/duress
        if verification_result == 'PASS' or duress_detected or attempt_count >= config.MAX_VERIFICATION_ATTEMPTS:
            logger.info(f"Finalizing session {session_id} after attempt {attempt_count}. Result: {verification_result}, Duress: {duress_detected}")
            # Let client show result, cleanup will happen on disconnect or timeout
        else: # Failed attempt, but more attempts remain
             logger.info(f"Attempt {attempt_count}/{config.MAX_VERIFICATION_ATTEMPTS} failed for session {session_id}. Resetting challenge.")
             try:
                 detector.reset() # Reset detector for next attempt
                 challenge_text = detector.get_initial_challenge()
                 emit('challenge', {'text': challenge_text}, room=session_id) # Send new challenge
             except Exception as e:
                  logger.error(f"Error resetting detector for {session_id} after failed attempt: {e}", exc_info=True)
                  emit('session_error', {'message': 'Error starting next attempt.'})
                  # Consider cleaning up if reset fails critically
                  # cleanup_session(session_id)


@socketio.on('reset')
def handle_reset(data):
    """Handle reset request from verifier (e.g., after failed attempt)."""
    session_id = request.sid
    code = data.get('code')

    if session_id not in active_sessions or active_sessions[session_id].get('code') != code:
        logger.warning(f"Reset request from invalid session: {session_id}, Code: {code}")
        return

    detector = active_sessions[session_id].get('detector')
    if not detector:
        logger.error(f"Cannot reset: Detector not found for session {session_id}")
        return

    attempt_count = active_sessions[session_id].get('attempts', 0)
    if attempt_count >= config.MAX_VERIFICATION_ATTEMPTS:
         logger.warning(f"Reset denied for {session_id}: Max attempts reached.")
         emit('max_attempts_reached') # Ensure client knows
         return

    logger.info(f"Resetting challenge for session {session_id} (Attempt {attempt_count + 1})")
    try:
        detector.reset()
        challenge_text = detector.get_initial_challenge()
        emit('reset_confirmed', room=session_id) # Confirm reset to client
        emit('challenge', {'text': challenge_text}, room=session_id) # Send new challenge
    except Exception as e:
        logger.error(f"Error resetting detector for {session_id}: {e}", exc_info=True)
        emit('error', {'message': 'Failed to reset verification challenge.'})


@socketio.on('client_network_quality')
def handle_client_network_quality(data):
    """Store client's reported network quality."""
    session_id = request.sid
    if session_id in active_sessions:
        quality = data.get('quality')
        latency = data.get('latency')
        if quality in TARGET_WIDTHS: # Validate quality string
             active_sessions[session_id]['network_quality'] = quality
             # Optional: Log client report if needed for debugging
             # logger.debug(f"Client {session_id} reported quality: {quality}, latency: {latency:.0f}ms")
        else:
             logger.warning(f"Invalid network quality '{quality}' reported by {session_id}")


@socketio.on('orientation_change')
def handle_orientation_change(data):
    """Store client's reported orientation."""
    session_id = request.sid
    if session_id in active_sessions:
        is_portrait = data.get('isPortrait', False)
        width = data.get('width', 0)
        height = data.get('height', 0)
        active_sessions[session_id]['orientation'] = {
            'isPortrait': is_portrait,
            'width': width,
            'height': height
        }
        # Log if needed: logger.debug(f"Orientation updated for {session_id}: {'Portrait' if is_portrait else 'Landscape'}")


@socketio.on('get_debug_status')
def handle_get_debug_status():
    """Send debug configuration to client."""
    emit('debug_status', {
        'debug': config.APP_DEBUG_MODE, # Use central config flag
        'showDebugFrame': config.SHOW_DEBUG_FRAME
    })


@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    """Process audio chunk (requires detector integration)."""
    session_id = request.sid
    if session_id in active_sessions:
        detector = active_sessions[session_id].get('detector')
        audio_data = data.get('audio') # Expecting raw bytes (ArrayBuffer) or base64 string
        if detector and audio_data and hasattr(detector, 'process_audio_chunk'):
            try:
                 # If data is base64, decode first
                 # if isinstance(audio_data, str):
                 #     audio_data = base64.b64decode(audio_data)

                 detector.process_audio_chunk(audio_data)
            except Exception as e:
                 logger.error(f"Error processing audio chunk for {session_id}: {e}")
        # else: logger.debug("Audio chunk received but no detector or method found.")


# --- Main Execution ---

if __name__ == '__main__':
    logger.info("Starting Flask-SocketIO server...")
    # Create static directories if they don't exist
    os.makedirs('static/qr_codes', exist_ok=True)

    # Start background task using eventlet's cooperative threading
    eventlet.spawn(cleanup_inactive_sessions_task)

    # Run the app using eventlet WSGI server for SocketIO compatibility
    try:
        socketio.run(app,
                     host=config.HOST,
                     port=config.PORT,
                     debug=config.BROWSER_DEBUG, # Use Flask's debug mode control
                     use_reloader=config.BROWSER_DEBUG # Use reloader only in debug mode
                     )
    except KeyboardInterrupt:
         logger.info("Server shutting down.")
    except Exception as e:
         logger.critical(f"Server failed to start or crashed: {e}", exc_info=True)