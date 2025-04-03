"""Web application for liveness detection with orientation support.

This module implements the Flask web server and Socket.IO communication for the
liveness detection system. It handles client connections, processes video and audio
streams, and coordinates verification sessions between requesters and subjects.
"""
import eventlet
eventlet.monkey_patch() # Must be called before standard library imports like time, socket

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

# Assuming config and liveness_detector are in the same directory or PYTHONPATH
from config import Config
from liveness_detector import LivenessDetector


# Initialize Flask app
app = Flask(__name__,
            static_folder='static',
            template_folder='templates')
app.config['SECRET_KEY'] = 'liveness-detection-secret' # Change in production

# Initialize socketio with optimized settings
socketio = SocketIO(
    app,
    cors_allowed_origins="*", # Restrict in production
    async_mode='eventlet',  # Use eventlet for better performance with many concurrent connections
    ping_timeout=60,        # Increase ping timeout for more stable connections
    ping_interval=25,       # Reduce ping interval for faster disconnection detection
    max_http_buffer_size=5 * 1024 * 1024  # 5MB buffer for larger frames if needed
)

# Initialize config
config = Config()

# Configure logging using config values
logging.basicConfig(level=config.APP_LOGGING_LEVEL, format=config.LOGGING_FORMAT)
# Set specific levels for other modules if needed (as per original file)
logging.getLogger('speech_recognizer').setLevel(config.SPEECH_RECOGNIZER_LOGGING_LEVEL)
logging.getLogger('action_detector').setLevel(config.ACTION_DETECTOR_LOGGING_LEVEL)
logging.getLogger('challenge_manager').setLevel(config.CHALLENGE_MANAGER_LOGGING_LEVEL)
logging.getLogger('liveness_detector').setLevel(config.LIVENESS_DETECTOR_LOGGING_LEVEL)
logger = logging.getLogger(__name__)

# In-memory storage (Replace with persistent storage in production if needed)
active_sessions: Dict[str, Dict[str, Any]] = {}
verification_codes: Dict[str, Dict[str, Any]] = {}
frame_cache: Dict[str, Tuple[float, str]] = {} # Cache for encoded frames: {cache_key: (timestamp, base64_string)}

# Cache settings (using values from the fetched file)
FRAME_CACHE_SIZE = 30  # Max number of frames to cache
FRAME_CACHE_TTL = 5   # Time to live in seconds

# Target widths for resizing based on network quality (adjust as needed)
# Using widths from my previous suggestion for better granularity
TARGET_WIDTHS = {
    'high': 640,
    'medium': 480,
    'low': 320,
    'very_low': 240
}

# JPEG encoding quality for different network conditions (using values from fetched file)
JPEG_QUALITY_MAP = {
    'high': 70,
    'medium': 50,
    'low': 40,
    'very_low': 30
}
DEFAULT_NETWORK_QUALITY = 'medium'

# Debug frame settings (using factors from previous suggestion for relative scaling)
DEBUG_QUALITY_REDUCTION_FACTOR = 0.7 # Reduce quality by 30% compared to main frame
DEBUG_TARGET_WIDTH_FACTOR = 0.8 # Reduce width by 20% compared to main frame

# Logging intervals
NETWORK_LOG_INTERVAL = 5  # Log network quality every 5 seconds (from fetched file)
last_network_log_time: Dict[str, float] = {} # Ensure this is defined globally


# --- Utility Functions ---

def generate_code(length: int = 6) -> str:
    """Generates a random digit code."""
    return ''.join(random.choices(string.digits, k=length))

# Utility function to resize an image while preserving aspect ratio (from previous fix)
def resize_with_aspect_ratio(image, target_width: Optional[int] = None, target_height: Optional[int] = None, inter=cv2.INTER_AREA):
    """Resizes an image while preserving aspect ratio."""
    (h, w) = image.shape[:2]
    if w == 0 or h == 0:
        logger.warning("Attempted to resize an image with zero width or height.")
        return image # Cannot resize empty image

    if target_width is None and target_height is None:
        return image # No resize needed

    # Avoid upscaling beyond original dimensions
    if target_width is not None and target_width >= w and target_height is None:
         logger.debug(f"Resize skipped: Target width ({target_width}) >= original width ({w}).")
         return image
    if target_height is not None and target_height >= h and target_width is None:
         logger.debug(f"Resize skipped: Target height ({target_height}) >= original height ({h}).")
         return image

    # Calculate dimensions
    if target_width is None:
        # Calculate width based on target height
        r = target_height / float(h)
        dim = (int(w * r), target_height)
    else:
        # Calculate height based on target width
        r = target_width / float(w)
        dim = (target_width, int(h * r))

    # Ensure dimensions are positive
    if dim[0] <= 0 or dim[1] <= 0:
         logger.warning(f"Invalid resize dim calculated: {dim}. Original: {w}x{h}, TargetW: {target_width}, TargetH: {target_height}")
         return image # Return original if calculation fails

    resized = cv2.resize(image, dim, interpolation=inter)
    return resized

# Utility function to encode frames (from previous fix, handling WebP and fallback)
def encode_frame(frame, quality: int, format='.jpg') -> Optional[str]:
    """Encodes a frame to base64 string with specified quality and format."""
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
             logger.warning(f"Unsupported encoding format requested: {format}. Defaulting to JPEG.")
             format = '.jpg' # Fallback to JPEG
             encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
             mime_type = 'image/jpeg'

        success, buffer = cv2.imencode(format, frame, encode_params)
        if not success:
             logger.error(f"Failed to encode frame to {format}")
             # Attempt fallback to JPEG if WEBP failed
             if format == '.webp':
                  logger.info("Falling back to JPEG encoding for frame after WebP failure.")
                  return encode_frame(frame, quality, format='.jpg')
             return None

        encoded_string = base64.b64encode(buffer).decode('utf-8')
        return f"data:{mime_type};base64,{encoded_string}"
    except cv2.error as cv_err: # Catch specific OpenCV errors
         logger.error(f"OpenCV error encoding frame to {format}: {cv_err}", exc_info=False) # Don't need full traceback for common errors
         # Attempt fallback to JPEG if WEBP failed due to OpenCV error
         if format == '.webp':
              logger.info("Falling back to JPEG encoding for frame after WebP OpenCV error.")
              return encode_frame(frame, quality, format='.jpg')
         return None
    except Exception as e:
        logger.error(f"General error encoding frame to {format}: {e}", exc_info=True)
        return None

# Combined cleanup function (based on fetched file structure)
def cleanup_session(session_id: str, code: str = None):
    """Clean up resources associated with a session.

    Args:
        session_id: The Socket.IO session ID
        code: Optional verification code associated with the session
    """
    if session_id in active_sessions:
        session_data = active_sessions.pop(session_id) # Remove session atomically
        code = code or session_data.get('code')
        logger.info(f"Cleaning up session {session_id} (Code: {code})")

        # Stop detector resources if they exist
        detector = session_data.get('detector')
        if detector:
             # Stop speech recognizer if it exists and has a stop method
             if hasattr(detector, 'speech_recognizer') and hasattr(detector.speech_recognizer, "stop"):
                 try:
                     detector.speech_recognizer.stop()
                     logger.debug(f"Stopped speech recognizer for session {session_id}")
                 except Exception as e:
                      logger.error(f"Error stopping speech recognizer for session {session_id}: {e}")
             # Add general detector stop if needed
             if hasattr(detector, 'stop'):
                 try:
                     detector.stop()
                     logger.debug(f"Stopped main detector resources for session {session_id}")
                 except Exception as e:
                     logger.error(f"Error stopping detector for session {session_id}: {e}")


        # Update verification code status if applicable and remove file/entry
        if code and code in verification_codes:
             verification_codes[code]['status'] = 'completed' # Mark as completed first
             qr_path = f"static/qr_codes/{code}.png"
             if os.path.exists(qr_path):
                 try:
                     os.remove(qr_path)
                     logger.info(f"Deleted QR code for completed session {session_id}: {code}")
                 except OSError as e:
                     logger.error(f"Error removing QR code {qr_path}: {e}")
             # Remove the code entry entirely after cleanup
             if code in verification_codes:
                 del verification_codes[code]
                 logger.debug(f"Removed verification code entry: {code}")

        # Clean up network log time entry
        if session_id in last_network_log_time:
             del last_network_log_time[session_id]

    else:
        logger.warning(f"Attempted to clean up non-existent session: {session_id}")

# Background task function (based on fetched file structure)
def cleanup_inactive_sessions():
    """Periodically clean up inactive sessions to free resources."""
    while True:
        try:
            current_time = time.time()
            inactive_session_ids = []

            # Find inactive sessions by iterating over a copy of keys
            for session_id in list(active_sessions.keys()):
                # Check if session still exists before accessing data
                if session_id in active_sessions:
                    session_data = active_sessions[session_id]
                    last_activity = session_data.get('last_activity', 0)
                    if current_time - last_activity > config.SESSION_TIMEOUT:
                        logger.info(f"Session {session_id} timed out (inactive for {current_time - last_activity:.0f}s).")
                        inactive_session_ids.append(session_id)
                else:
                    logger.warning(f"Session {session_id} disappeared during inactive check.")


            # Clean up inactive sessions
            for session_id in inactive_session_ids:
                cleanup_session(session_id)

            # Clean up expired frame cache entries
            # Iterate over a copy of keys to avoid runtime errors during deletion
            expired_keys = [key for key, (timestamp, _) in list(frame_cache.items()) if current_time - timestamp > FRAME_CACHE_TTL]
            cleaned_count = 0
            for key in expired_keys:
                 if key in frame_cache: # Check again in case deleted by another thread/process
                     del frame_cache[key]
                     cleaned_count += 1
            if cleaned_count > 0:
                 logger.debug(f"Cleaned up {cleaned_count} expired frame cache entries.")

        except Exception as e:
            logger.error(f"Error in cleanup task: {e}", exc_info=True)

        # Sleep before next cleanup cycle (use eventlet sleep)
        eventlet.sleep(10) # Check every 10 seconds (from fetched file)

# --- Flask Routes (identical to fetched file) ---

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
    if not code or not code.isdigit() or len(code) != 6:
        logger.warning(f"Invalid code format received: {code}")
        return render_template('error.html', message="Invalid code format.", redirect_url="/"), 400
    if code not in verification_codes or verification_codes[code].get('status') != 'pending':
        logger.warning(f"Invalid or non-pending code accessed: {code}, Status: {verification_codes.get(code, {}).get('status')}")
        return render_template('error.html', message="Verification code is invalid or has expired.", redirect_url="/"), 404
    logger.info(f"Rendering verification page for code: {code}")
    return render_template('verify.html', session_code=code)

@app.route('/check_code/<code>')
def check_code(code):
    """Check if a verification code is valid and pending (API endpoint).

    Args:
        code: The verification code to check

    Returns:
        JSON response indicating if the code is valid
    """
    logger.debug(f"Check code route called with code: {code}")
    is_valid = code in verification_codes and verification_codes[code].get('status') == 'pending'
    logger.debug(f"Code {code} validity check result: {is_valid}")
    return jsonify({'valid': is_valid})

# --- Socket.IO Event Handlers ---

@socketio.on('connect')
def handle_connect():
    """Handle client connection to Socket.IO."""
    session_id = request.sid
    logger.info(f"Client connected: {session_id}")
    # Initialize basic session structure immediately
    active_sessions[session_id] = {
        'last_activity': time.time(),
        'network_quality': DEFAULT_NETWORK_QUALITY,
        'orientation': {'isPortrait': False, 'width': 0, 'height': 0},
        'attempts': 0,
        'code': None, # Will be set on join
        'detector': None
    }

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection from Socket.IO."""
    session_id = request.sid
    logger.info(f"Client disconnected: {session_id}")
    # Pass associated code if available for more robust cleanup
    code_to_clean = active_sessions.get(session_id, {}).get('code')
    cleanup_session(session_id, code=code_to_clean)


@socketio.on('generate_code')
def handle_generate_code():
    """Generate a verification code and QR code (from fetched file, verified).

    Creates a unique 6-digit verification code and associated QR code,
    then sends them to the client.
    """
    session_id = request.sid
    logger.info(f"Generate code request from session {session_id}")
    code = generate_code() # Use utility function

    # Ensure directory exists
    qr_dir = 'static/qr_codes'
    os.makedirs(qr_dir, exist_ok=True)

    # Construct verification URL using config base URL
    verification_url = f"{config.BASE_URL.rstrip('/')}/verify/{code}"
    qr_path_rel = f"static/qr_codes/{code}.png" # Relative path for client
    qr_path_abs = os.path.join(qr_dir, f"{code}.png") # Absolute path for saving

    try:
        # Create QR code (using settings from fetched file - may differ slightly)
        qr = qrcode.QRCode(version=1, box_size=10, border=5) # border=5 from fetched file
        qr.add_data(verification_url)
        qr.make(fit=True)

        # Create QR code image (using settings from fetched file - potential transparency)
        # Assuming fill='black' and back_color=(255, 255, 255, 0) means transparent background
        qr_img = qr.make_image(fill_color='black', back_color=(255, 255, 255, 0)) # Transparent background?

        qr_img.save(qr_path_abs)
        logger.info(f"QR code saved to: {qr_path_abs}")
    except Exception as e:
        logger.error(f"Failed to generate or save QR code for {code}: {e}", exc_info=True)
        emit('error', {'message': 'Failed to generate QR code.'})
        return

    # Store verification code details
    verification_codes[code] = {
        'requester_id': session_id,
        'created_at': time.time(),
        'status': 'pending'
    }

    logger.info(f"Emitting verification code {code} with QR code path {qr_path_rel} to session {session_id}")
    emit('verification_code', {
        'code': code,
        'qr_code': f"/{qr_path_rel}", # Ensure leading slash for URL path
        # Flag from fetched file (seems hardcoded True)
        'enable_video_background': config.SHOW_PARTNER_VIDEO_IN_QR # Use config value
    })

    # Start a thread/greenlet to expire the code (using eventlet.spawn)
    def expire_code_task(exp_code):
        eventlet.sleep(config.CODE_EXPIRATION_TIME) # Use config value
        if exp_code in verification_codes and verification_codes[exp_code]['status'] == 'pending':
            logger.info(f"Verification code {exp_code} expired.")
            qr_to_remove = os.path.join(qr_dir, f"{exp_code}.png")
            if os.path.exists(qr_to_remove):
                try:
                    os.remove(qr_to_remove)
                    logger.info(f"Deleted QR code for expired code: {exp_code}")
                except OSError as e:
                    logger.error(f"Error removing QR code for expired code {exp_code}: {e}")
            # Remove from dict after file removal attempt
            if exp_code in verification_codes:
                 del verification_codes[exp_code]

    eventlet.spawn(expire_code_task, code) # Use eventlet spawn for background task


@socketio.on('join_verification')
def handle_join_verification(data):
    """Handle a client joining a verification session (from fetched file, verified).

    Args:
        data: Dictionary containing join request data
    """
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
         logger.warning(f"Session {session_id} not found in active_sessions during join. Re-initializing.")
         active_sessions[session_id] = {'last_activity': time.time()} # Basic re-init

    # Get initial orientation from clientInfo
    is_portrait = client_info.get('isPortrait', False)
    screen_width = client_info.get('screenWidth', 0)
    screen_height = client_info.get('screenHeight', 0)

    active_sessions[session_id].update({
        'code': code,
        'detector': None, # Will be initialized shortly
        'attempts': 0,
        'network_quality': DEFAULT_NETWORK_QUALITY,
        'client_info': client_info,
        'orientation': {
            'isPortrait': is_portrait,
            'width': screen_width,
            'height': screen_height
        },
        'last_activity': time.time() # Update activity time
    })


    logger.info(f"Verifier {session_id} joined session {code}. Requester: {requester_id}. Initial Orientation: {'Portrait' if is_portrait else 'Landscape'} ({screen_width}x{screen_height})")

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
        # Get initial challenge using the detector's method
        challenge_text = detector.get_initial_challenge()
        logger.info(f"Liveness detector initialized for {session_id}. Initial challenge: {challenge_text}")
        emit('challenge', {'text': challenge_text})
    except Exception as e:
         logger.error(f"Failed to initialize LivenessDetector for {session_id}: {e}", exc_info=True)
         emit('session_error', {'message': 'Failed to start verification process.'})
         # Clean up partially started session
         cleanup_session(session_id, code=code)


@socketio.on('process_frame')
def handle_process_frame(data):
    """Process a video frame from the client, applying aspect ratio fix.

    Args:
        data: Dictionary containing frame data and metadata
    """
    start_time = time.time()
    session_id = request.sid
    code = data.get('code')
    timestamp = data.get('timestamp') # Client timestamp for latency calculation

    # --- Basic Validation ---
    if session_id not in active_sessions or active_sessions[session_id].get('code') != code:
        logger.warning(f"Frame from invalid session: {session_id}, Code: {code}")
        # Avoid emitting error here, could flood client if connection is flapping
        return

    detector = active_sessions[session_id].get('detector')
    if not detector:
        logger.error(f"Detector not initialized for session {session_id}, ignoring frame.")
        return

    max_attempts = config.MAX_VERIFICATION_ATTEMPTS
    if active_sessions[session_id]['attempts'] >= max_attempts:
        logger.warning(f"Max attempts ({max_attempts}) reached for session {session_id}, ignoring frame.")
        # Optionally emit max attempts reached again if needed
        # emit('max_attempts_reached', room=session_id)
        return

    active_sessions[session_id]['last_activity'] = time.time()

    # --- Get Frame Data and Metadata ---
    image_b64 = data.get('image', '').split(',')[-1] # Get data part of base64 string
    is_portrait = data.get('isPortrait', active_sessions[session_id]['orientation'].get('isPortrait', False))
    network_quality = data.get('networkQuality', active_sessions[session_id].get('network_quality', DEFAULT_NETWORK_QUALITY))

    # Validate network quality string
    if network_quality not in JPEG_QUALITY_MAP:
         logger.warning(f"Invalid network quality '{network_quality}' received from {session_id}. Using default.")
         network_quality = DEFAULT_NETWORK_QUALITY

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
        if nparr.size == 0:
             logger.warning(f"Received frame buffer with size 0 from {session_id}")
             return # Ignore zero-size frames

        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            logger.warning(f"Failed to decode frame from {session_id} (imdecode returned None)")
            return
    except Exception as e:
        logger.error(f"Error decoding frame from {session_id}: {e}", exc_info=True)
        # emit('error', {'message': 'Failed to process image data.'}) # Avoid flooding client
        return

    processing_start_time = time.time()

    # --- Process Frame with Liveness Detector ---
    try:
        # Pass orientation data to the detector if it supports it
        orientation_data = active_sessions[session_id]['orientation']

        # Check if detector supports orientation data (optional but good practice)
        if hasattr(detector, 'process_frame_with_orientation'):
             result = detector.process_frame_with_orientation(frame, orientation_data)
        else:
             # Fallback if method doesn't exist (or always use the basic one if preferred)
             result = detector.process_frame(frame)
        # result contains: frame, debug_frame, challenge_text, action_completed, etc.
    except Exception as e:
        logger.error(f"Error during detector processing for {session_id}: {e}", exc_info=True)
        emit('error', {'message': 'Error during liveness detection.'}, room=session_id) # Send error to specific client
        return

    processing_time = time.time() - processing_start_time

    # --- Prepare Frames for Sending (Resize & Encode using corrected functions) ---
    encoding_start_time = time.time()

    # Determine target width and quality based on network
    target_base_width = TARGET_WIDTHS.get(network_quality, TARGET_WIDTHS[DEFAULT_NETWORK_QUALITY])
    jpeg_quality = JPEG_QUALITY_MAP.get(network_quality, JPEG_QUALITY_MAP[DEFAULT_NETWORK_QUALITY])

    # Aspect ratio fix: Use resize_with_aspect_ratio based on target width
    # The function itself handles preserving the aspect ratio.
    resized_main_frame = resize_with_aspect_ratio(result.get('frame'), target_width=target_base_width)

    # Encode main frame (try WebP first for partner, fallback to JPEG; Verifier gets JPEG)
    encoded_main_frame_partner = encode_frame(resized_main_frame, jpeg_quality, format='.webp')
    if encoded_main_frame_partner is None: # If WebP failed and fallback also failed
         logger.error(f"Failed to encode main frame (partner) for {session_id}")
         # Maybe send a placeholder or skip? For now, proceed without it.
         pass

    # Verifier always gets JPEG for wider compatibility maybe? Or use WebP if available? Let's stick to JPEG for verifier for now.
    encoded_main_frame_verifier = encode_frame(resized_main_frame, jpeg_quality, format='.jpg')
    if encoded_main_frame_verifier is None:
        logger.error(f"Failed to encode main frame (verifier) for {session_id}")
        # If verifier frame fails, we probably can't continue usefully
        return


    # Prepare debug frame if needed
    encoded_debug_frame = None
    if config.SHOW_DEBUG_FRAME and result.get('debug_frame') is not None:
        debug_frame = result['debug_frame']
        # Calculate reduced quality and width for debug frame using factors
        debug_quality = max(20, int(jpeg_quality * DEBUG_QUALITY_REDUCTION_FACTOR)) # Ensure minimum quality
        debug_target_width = int(target_base_width * DEBUG_TARGET_WIDTH_FACTOR)

        resized_debug_frame = resize_with_aspect_ratio(debug_frame, target_width=debug_target_width)
        encoded_debug_frame = encode_frame(resized_debug_frame, debug_quality, format='.jpg') # Debug frame always JPEG
        if encoded_debug_frame is None:
             logger.warning(f"Failed to encode debug frame for {session_id}")

    encoding_time = time.time() - encoding_start_time

    # --- Emit Results ---
    emit_start_time = time.time()

    # Data for the verifier client
    verifier_data = {
        # Use encoded frames; handle None cases
        'image': encoded_main_frame_verifier,
        'debug_image': encoded_debug_frame,
        # Get results from detector output dictionary
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
         if requester_id and encoded_main_frame_partner: # Only send if encoding succeeded
             challenge_text = result['challenge_text'] if result['challenge_text'] else "Waiting for challenge..."
             # Extract action/word text as per original file logic
             action_text = "Waiting for action..."
             word_text = "Waiting for word..."
             if challenge_text and "and say" in challenge_text.lower():
                 parts = challenge_text.split("and say")
                 if len(parts) == 2:
                     action_text = parts[0].strip()
                     word_text = "Say " + parts[1].strip()

             partner_data = {
                 'image': encoded_main_frame_partner, # Send WebP if available
                 'code': code,
                 'action_text': action_text, # From fetched logic
                 'word_text': word_text, # From fetched logic
                 'challenge_text': challenge_text, # Send current challenge
                 'timestamp': timestamp,
                 'isPortrait': is_portrait
             }
             emit('partner_video_frame', partner_data, room=requester_id)

    emit_time = time.time() - emit_start_time
    total_time = time.time() - start_time

    # Log performance periodically (using logic from fetched file)
    current_time = time.time()
    if session_id not in last_network_log_time or current_time - last_network_log_time.get(session_id, 0) > NETWORK_LOG_INTERVAL:
         log_frame_width = resized_main_frame.shape[1] if resized_main_frame is not None else 0
         log_frame_height = resized_main_frame.shape[0] if resized_main_frame is not None else 0
         logger.info(f"PERF STATS - Session: {session_id}, Quality: {network_quality}, TargetW: {target_base_width}, Frame: {log_frame_width}x{log_frame_height}, JPEG-Q: {jpeg_quality}, Orient: {'P' if is_portrait else 'L'}")
         logger.info(f"PERF TIMES - Total: {total_time:.3f}s, Processing: {processing_time:.3f}s, Encoding: {encoding_time:.3f}s, Emit: {emit_time:.3f}s")
         last_network_log_time[session_id] = current_time


    # --- Handle Verification Completion/Failure (using logic from fetched file) ---
    if result.get('exit_flag'):
        verification_result = result.get('verification_result', 'FAIL')
        duress_detected = result.get('duress_detected', False)
        logger.info(f"Verification ended for session {session_id}. Result: {verification_result}, Duress: {duress_detected}")

        active_sessions[session_id]['attempts'] += 1
        attempt_count = active_sessions[session_id]['attempts']

        requester_id = verification_codes.get(code, {}).get('requester_id')

        # Notify requester immediately of the final result
        if requester_id:
             final_result_for_requester = 'FAIL' if duress_detected else verification_result
             logger.info(f"Emitting final result '{final_result_for_requester}' (Duress: {duress_detected}) to requester {requester_id} for code {code}")
             emit('verification_result', {
                 'result': final_result_for_requester,
                 'code': code,
                 'duress_detected': duress_detected
             }, room=requester_id)
        else:
             logger.warning(f"Requester ID not found for code {code} when emitting final result.")

        # Check if final attempt or pass/duress - logic from fetched file
        if verification_result == 'PASS' or duress_detected or attempt_count >= max_attempts:
            logger.info(f"Finalizing session {session_id} after attempt {attempt_count}. Result: {verification_result}, Duress: {duress_detected}. Max Attempts: {max_attempts}")
            # Cleanup will happen on disconnect or timeout, don't cleanup immediately here
            # unless explicitly needed. Fetched file logic implies timeout/disconnect cleanup.
        else: # Failed attempt, but more attempts remain
             logger.info(f"Attempt {attempt_count}/{max_attempts} failed for session {session_id}. Resetting challenge.")
             try:
                 detector.reset() # Reset detector for next attempt
                 challenge_text = detector.get_initial_challenge()
                 emit('challenge', {'text': challenge_text}, room=session_id) # Send new challenge
             except Exception as e:
                  logger.error(f"Error resetting detector for {session_id} after failed attempt: {e}", exc_info=True)
                  emit('session_error', {'message': 'Error starting next attempt.'}, room=session_id)
                  # Consider cleaning up if reset fails critically
                  # cleanup_session(session_id, code=code)

# --- Other Event Handlers (from fetched file, verified) ---

@socketio.on('reset')
def handle_reset(data):
    """Reset the verification process (from fetched file).

    Args:
        data: Dictionary containing reset request data
    """
    session_id = request.sid
    code = data.get('code')

    if session_id not in active_sessions or active_sessions[session_id].get('code') != code:
        logger.warning(f"Reset request from invalid session: {session_id}, Code: {code}")
        return

    detector = active_sessions[session_id].get('detector')
    if not detector:
        logger.error(f"Cannot reset: Detector not found for session {session_id}")
        return

    max_attempts = config.MAX_VERIFICATION_ATTEMPTS
    attempt_count = active_sessions[session_id].get('attempts', 0) # Current attempts before reset

    if attempt_count >= max_attempts:
         logger.warning(f"Reset denied for {session_id}: Max attempts ({max_attempts}) reached.")
         emit('max_attempts_reached', room=session_id) # Ensure client knows
         return

    # Note: The original fetched file increments attempts *before* reset in handle_frame/exit_flag logic.
    # Here, we log the upcoming attempt number. Reset itself doesn't increment.
    logger.info(f"Resetting challenge for session {session_id} (Attempt {attempt_count + 1}/{max_attempts})")
    try:
        detector.reset()
        challenge_text = detector.get_initial_challenge()
        emit('reset_confirmed', room=session_id) # Confirm reset to client
        emit('challenge', {'text': challenge_text}, room=session_id) # Send new challenge
    except Exception as e:
        logger.error(f"Error resetting detector for {session_id}: {e}", exc_info=True)
        emit('error', {'message': 'Failed to reset verification challenge.'}, room=session_id)


@socketio.on('client_network_quality')
def handle_client_network_quality(data):
    """Handle network quality information from client (from fetched file).

    Args:
        data: Dictionary containing network quality information
    """
    session_id = request.sid
    if session_id not in active_sessions:
        # Log lightly or ignore if session doesn't exist
        # logger.debug(f"Received network quality from unknown session: {session_id}")
        return

    quality = data.get('quality')
    latency = data.get('latency', 0)

    if quality and quality in JPEG_QUALITY_MAP: # Use correct map
        # Store network quality in session data
        active_sessions[session_id]['network_quality'] = quality

        # Log network quality updates (rate-limited)
        current_time = time.time()
        # Use the global last_network_log_time dictionary
        if session_id not in last_network_log_time or current_time - last_network_log_time.get(session_id, 0) > NETWORK_LOG_INTERVAL:
            logger.info(f"NETWORK STATS (Client Report) - Session: {session_id}, Quality: {quality}, Latency: {latency:.0f}ms, JPEG Quality: {JPEG_QUALITY_MAP[quality]}")
            last_network_log_time[session_id] = current_time
    else:
        logger.warning(f"Invalid network quality '{quality}' reported by {session_id}")


@socketio.on('orientation_change')
def handle_orientation_change(data):
    """Handle orientation change information from client (from fetched file).

    Args:
        data: Dictionary containing orientation information
    """
    session_id = request.sid
    if session_id not in active_sessions:
        # logger.debug(f"Received orientation change from unknown session: {session_id}")
        return

    is_portrait = data.get('isPortrait', False)
    width = data.get('width', 0)
    height = data.get('height', 0)

    # Store orientation data in session
    active_sessions[session_id]['orientation'] = {
        'isPortrait': is_portrait,
        'width': width,
        'height': height
    }

    logger.info(f"Client {session_id} reported orientation change: {'portrait' if is_portrait else 'landscape'}, {width}x{height}")


@socketio.on('get_debug_status')
def handle_get_debug_status():
    """Send debug status to client (from fetched file)."""
    logger.debug(f"Debug status requested by {request.sid}")
    emit('debug_status', {
        'debug': config.APP_DEBUG_MODE,  # Use central config flag
        'showDebugFrame': config.SHOW_DEBUG_FRAME
    })


@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    """Process audio chunk from client (from fetched file).

    Args:
        data: Dictionary containing audio data and metadata
    """
    session_id = request.sid

    # Rate limit debug logging if needed (similar to fetched file)
    # current_time = time.time()
    # if session_id not in last_log_time or current_time - last_log_time.get(session_id, 0) > 5:
    #     logger.debug(f"Received audio chunk event from session: {session_id}")
    #     last_log_time[session_id] = current_time

    if session_id not in active_sessions:
        logger.warning(f"Received audio chunk from unknown session: {session_id}")
        return

    detector = active_sessions[session_id].get('detector')
    if not detector or not hasattr(detector, 'speech_recognizer'):
         logger.warning(f"Audio chunk received for session {session_id}, but detector or speech_recognizer not ready.")
         return

    try:
        # Assuming data['audio'] is base64 encoded string from client JS example
        audio_chunk_b64 = data.get('audio')
        if not audio_chunk_b64:
             logger.warning(f"Received empty audio chunk from {session_id}")
             return

        audio_chunk = base64.b64decode(audio_chunk_b64)

        # Pass chunk to the detector's speech recognizer component
        if hasattr(detector.speech_recognizer, 'process_audio_chunk'):
             detector.speech_recognizer.process_audio_chunk(audio_chunk)
        else:
              logger.warning(f"Detector's speech recognizer for session {session_id} lacks 'process_audio_chunk' method.")

    except base64.binascii.Error as b64_err:
         logger.error(f"Error decoding base64 audio chunk from session {session_id}: {b64_err}")
    except Exception as e:
        logger.error(f"Error processing audio chunk from session {session_id}: {e}", exc_info=True)


# --- Deprecated/Legacy Handlers (kept from fetched file for reference/completeness) ---

@socketio.on('frame')
def handle_frame(data):
    """Legacy frame handler (deprecated - should use process_frame)."""
    logger.warning(f"Received data on deprecated 'frame' event from {request.sid}. Use 'process_frame' instead.")
    # Redirect to the new handler if possible, or just log and ignore
    # handle_process_frame(data) # Be cautious about directly calling another handler


@socketio.on('verification_complete')
def handle_verification_complete(data):
    """Handle verification completion notification (from fetched file).

    Args:
        data: Dictionary containing verification result data
    """
    code = data.get('code')
    result = data.get('result') # Expected 'PASS' or 'FAIL'
    duress = data.get('duress_detected', False) # Check for duress flag

    logger.info(f"Received 'verification_complete' event for code {code}. Result: {result}, Duress: {duress}")

    if code and code in verification_codes:
        requester_id = verification_codes[code].get('requester_id')
        if requester_id:
            emit('verification_result', {
                'result': result,
                'code': code,
                'duress_detected': duress # Pass duress info to requester
            }, room=requester_id)
        else:
            logger.warning(f"Requester ID not found for code {code} during verification_complete event.")

        # Find associated session ID to clean up
        verifier_session_id = verification_codes[code].get('verifier_id')
        if verifier_session_id:
            logger.info(f"Cleaning up session {verifier_session_id} based on 'verification_complete' event for code {code}.")
            cleanup_session(verifier_session_id, code=code)
        else:
             # If verifier session ID isn't stored, we might have already cleaned up via disconnect/timeout
             logger.warning(f"Verifier session ID not found for code {code} during verification_complete. Session might already be cleaned up.")
             # Still remove the verification code entry if it exists
             if code in verification_codes:
                  del verification_codes[code]

    else:
        logger.warning(f"Received 'verification_complete' for unknown or already completed code: {code}")


# --- Main Execution ---

if __name__ == '__main__':
    logger.info("Starting Flask-SocketIO server...")
    # Create static directories if they don't exist
    os.makedirs('static/qr_codes', exist_ok=True)

    # Start background task using eventlet's cooperative threading
    eventlet.spawn(cleanup_inactive_sessions)
    logger.info("Inactive session cleanup task started.")

    # Run the app using eventlet WSGI server for SocketIO compatibility
    host = config.HOST
    port = config.PORT
    use_debug = config.BROWSER_DEBUG # Use Flask's debug mode control from config

    logger.info(f"Server starting on http://{host}:{port} (Debug: {use_debug})")
    try:
        socketio.run(app,
                     host=host,
                     port=port,
                     debug=use_debug,
                     use_reloader=use_debug # Use reloader only in debug mode
                     )
    except KeyboardInterrupt:
         logger.info("Server shutting down gracefully.")
    except Exception as e:
         logger.critical(f"Server failed to start or crashed: {e}", exc_info=True)