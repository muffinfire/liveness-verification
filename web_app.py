"""Web application for liveness detection."""

# Import standard Python libraries for various functionalities
import os  # Handles file system operations like creating directories or removing files
import cv2  # OpenCV library for computer vision tasks, such as image encoding/decoding
import base64  # For encoding binary data (like images) to base64 strings and vice versa
import numpy as np  # Provides numerical operations and array manipulation for image data
import logging  # Enables logging of debug, info, and error messages for troubleshooting
import random  # Used to generate random numbers or selections (e.g., for verification codes)
import string  # Provides string utilities, like digits for generating random codes
import qrcode  # Library to generate QR codes for verification URLs
from flask import Flask, render_template, request, jsonify  # Flask components: app creation, template rendering, HTTP requests, and JSON responses
from flask_socketio import SocketIO, emit, join_room, leave_room  # SocketIO for real-time WebSocket communication between server and clients
import threading  # Allows running background tasks, like cleanup or expiration timers
import time  # Provides time-related functions, such as timestamps and delays
from typing import Dict, Any  # Type hints to clarify dictionary structures and improve code readability

# Import custom project modules
from config import Config  # Loads configuration settings (e.g., timeouts, debug mode) from config.py
from liveness_detector import LivenessDetector  # Main class for liveness detection logic (face, blink, speech, etc.)

# Create Flask application instance
app = Flask(__name__,
            static_folder='static',  # Directory where static files (CSS, JS, images) are served from
            template_folder='templates')  # Directory containing HTML templates for rendering
app.config['SECRET_KEY'] = 'liveness-detection-secret'  # Secret key for securing Flask sessions and CSRF protection

# Initialize SocketIO for real-time communication, allowing connections from any origin
socketio = SocketIO(app, cors_allowed_origins="*")  # "*" allows all domains; adjust for production security

# Instantiate configuration object to access settings
config = Config()

# Configure logging based on debug mode from config
logging_level = logging.DEBUG if config.DEBUG else logging.INFO  # DEBUG logs more details, INFO is less verbose
logging.basicConfig(
    level=logging_level,  # Set the logging level to control verbosity
    format=config.LOGGING_FORMAT  # Use the log format defined in config (e.g., timestamp, level, message)
)
logger = logging.getLogger(__name__)  # Create a logger specific to this module (web_app.py)

# Define global dictionaries to manage application state
active_sessions: Dict[str, Dict[str, Any]] = {}  # Tracks active client sessions by session ID; each session has a detector, code, etc.
verification_codes: Dict[str, Dict[str, Any]] = {}  # Stores verification codes with their status, requester ID, and creation time
last_log_time = {}  # Keeps track of the last time a debug log was emitted per session, for rate-limiting

# Define route for the root URL (homepage)
@app.route('/')
def index():
    # Render the landing page template (index.html) when users visit "/"
    return render_template('index.html')

# Route to verify the code and render a page if it's valid
@app.route('/verify/<code>')
def verify(code):
    # Check if the code is exactly 6 digits
    if not code.isdigit() or len(code) != 6:
        # If not, show error with redirect
        return render_template('error.html', message="Invalid code format", redirect_url="/")

    # Check if the code exists and is still in 'pending' state
    if code not in verification_codes or verification_codes[code]['status'] != 'pending':
        # If not valid or already used/expired, show error
        return render_template('error.html', message="Invalid or expired verification code", redirect_url="/")

    # If everything checks out, render the verification page
    return render_template('verify.html', session_code=code)

# Define route to check if a verification code is valid via HTTP GET
@app.route('/check_code/<code>')
def check_code(code):
    # Log the code check attempt for debugging
    logger.debug(f"Check code route called with code: {code}")
    # Check if the code exists in verification_codes and is still pending
    is_valid = code in verification_codes and verification_codes[code]['status'] == 'pending'
    # Return a JSON response indicating whether the code is valid
    return jsonify({'valid': is_valid})

# Function to clean up a session and its resources when it ends or times out
def cleanup_session(session_id: str, code: str = None):
    """Clean up a session and its associated QR code."""
    # Check if the session exists in active_sessions
    if session_id in active_sessions:
        session_data = active_sessions[session_id]  # Retrieve the session’s data
        # If the session has a detector, stop its speech recognizer to free resources
        if session_data['detector'] is not None:
            session_data['detector'].speech_recognizer.stop()
        # Use provided code or extract it from session data if not provided
        code = code or session_data.get('code')
        # If a code exists and is in verification_codes, clean up associated resources
        if code and code in verification_codes:
            qr_path = f"static/qr_codes/{code}.png"  # Path to the QR code image file
            # Remove the QR code file if it exists on disk
            if os.path.exists(qr_path):
                os.remove(qr_path)
                logger.info(f"Deleted QR code for session {session_id}: {code}")
            # Update the code’s status to 'completed' and remove it from tracking
            verification_codes[code]['status'] = 'completed'
            del verification_codes[code]
        # Remove the session from active_sessions
        del active_sessions[session_id]
        # Log that the cleanup was completed
        logger.info(f"Cleaned up session {session_id} with code {code}")

# SocketIO event handler triggered when a client connects
@socketio.on('connect')
def handle_connect():
    session_id = request.sid  # Get the unique session ID assigned by Flask-SocketIO
    # Log the connection event with the session ID
    logger.info(f"Client connected: {session_id}")

# SocketIO event handler triggered when a client disconnects
@socketio.on('disconnect')
def handle_disconnect():
    session_id = request.sid  # Get the session ID of the disconnecting client
    logger.info(f"Client disconnected: {session_id}")
    # Clean up the session to free resources and remove tracking
    cleanup_session(session_id)

# SocketIO event handler for receiving video frames (older method, using detect_liveness)
@socketio.on('frame')
def handle_frame(data):
    session_id = request.sid  # Get the session ID of the client sending the frame
    # Verify the session exists
    if session_id not in active_sessions:
        logger.warning(f"Received frame from unknown session: {session_id}")
        return  # Exit if session isn’t recognized
    
    # Check if the session has exceeded the maximum allowed attempts (3)
    if active_sessions[session_id].get('attempts', 0) >= 3:
        emit('max_attempts_reached')  # Notify client they’ve hit the limit
        cleanup_session(session_id)  # Clean up the session
        return
    
    # Update the session’s last activity timestamp to track inactivity
    active_sessions[session_id]['last_activity'] = time.time()
    
    try:
        # Extract the base64-encoded image data from the incoming data, skipping the data URI prefix
        image_data = data['image'].split(',')[1]
        # Decode the base64 string into binary data
        image_bytes = base64.b64decode(image_data)
        # Convert binary data into a NumPy array for OpenCV processing
        image_array = np.frombuffer(image_bytes, np.uint8)
        # Decode the array into an image frame using OpenCV
        frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        
        # Get the liveness detector instance for this session
        detector = active_sessions[session_id]['detector']
        # Process the frame for liveness detection (older method)
        display_frame, exit_flag = detector.detect_liveness(frame)
        
        # Extract detection data for challenge status
        head_pose = detector.head_pose  # Current head pose from detector state
        blink_counter = detector.blink_count  # Current blink count from detector state
        last_speech = detector.last_speech or ""  # Current speech, default to empty string if None
        
        # Retrieve the current challenge status with detection data
        challenge_text, action_completed, word_completed, verification_result = \
            detector.challenge_manager.get_challenge_status(head_pose, blink_counter, last_speech)
        
        # Encode the processed display frame back to JPEG format
        _, buffer = cv2.imencode('.jpg', display_frame)
        # Convert the JPEG binary data to a base64 string for transmission
        encoded_frame = base64.b64encode(buffer).decode('utf-8')
        
        # Send the processed frame and challenge status back to the client
        emit('processed_frame', {
            'image': f'data:image/jpeg;base64,{encoded_frame}',  # Base64-encoded image with data URI prefix
            'challenge': challenge_text,  # Current challenge text (e.g., "Turn left and say blue")
            'action_completed': action_completed,  # Whether the action part is done
            'word_completed': word_completed,  # Whether the speech part is done
            'time_remaining': detector.challenge_manager.get_challenge_time_remaining(),  # Time left for challenge
            'verification_result': verification_result,  # Result: 'PASS', 'FAIL', or None
            'exit_flag': exit_flag  # Whether to stop processing (True if challenge is complete)
        })
        
        # If the challenge is complete and has a definitive result
        if exit_flag and verification_result in ['PASS', 'FAIL']:
            # Increment the attempt counter for this session
            active_sessions[session_id]['attempts'] = active_sessions[session_id].get('attempts', 0) + 1
            # If the challenge passed or max attempts reached, clean up the session
            if verification_result == 'PASS' or active_sessions[session_id]['attempts'] >= 3:
                cleanup_session(session_id)
    
    except Exception as e:
        # Log any errors that occur during frame processing
        logger.error(f"Error processing frame: {e}")
        # Notify the client of the error
        emit('error', {'message': str(e)})

# SocketIO event handler for resetting a verification session
@socketio.on('reset')
def handle_reset(data):
    session_id = request.sid  # Get the session ID of the client requesting reset
    code = data.get('code')  # Extract the verification code from the data
    
    # Check if the session exists
    if session_id not in active_sessions:
        logger.warning(f"Reset request from unknown session: {session_id}")
        return
    
    try:
        # Get the detector instance and reset its state (e.g., new challenge)
        detector = active_sessions[session_id]['detector']
        detector.reset()
        # Increment the attempt counter
        active_sessions[session_id]['attempts'] = active_sessions[session_id].get('attempts', 0) + 1
        # Log the reset action with the new attempt number
        logger.info(f"Reset detector for session {session_id}, new challenge issued, attempt {active_sessions[session_id]['attempts']}")
        # Confirm the reset to the client
        emit('reset_confirmed')
    except Exception as e:
        # Log any errors during reset
        logger.error(f"Error resetting verification: {e}")
        # Notify the client of the error
        emit('error', {'message': str(e)})

# SocketIO event handler to provide debug status to clients
@socketio.on('get_debug_status')
def handle_get_debug_status():
    # Log the debug status request with current config values
    logger.debug(f"Debug status requested: debug={config.DEBUG}, showDebugFrame={config.SHOW_DEBUG_FRAME}")
    # Send the debug configuration to the client
    emit('debug_status', {
        'debug': config.DEBUG,  # Whether debug mode is enabled
        'showDebugFrame': config.SHOW_DEBUG_FRAME  # Whether to show debug frames with landmarks
    })

# SocketIO event handler to generate a new verification code
@socketio.on('generate_code')
def handle_generate_code():
    session_id = request.sid  # Get the session ID of the requesting client
    logger.info(f"Generate code request from session {session_id}")
    
    # Generate a random 6-digit code using digits 0-9
    code = ''.join(random.choices(string.digits, k=6))
    # Construct the verification URL using the base URL from config
    verification_url = f"{config.BASE_URL}/verify/{code}"
    # Create a QR code object with specified settings
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(verification_url)  # Add the URL to the QR code
    qr.make(fit=True)  # Generate the QR code to fit the data
    # Create a black-and-white QR code image
    qr_img = qr.make_image(fill='black', back_color='white')
    qr_path = f"static/qr_codes/{code}.png"  # Define the file path for the QR code image
    qr_img.save(qr_path)  # Save the QR code image to disk
    
    # Store the verification code details in the global dictionary
    verification_codes[code] = {
        'requester_id': session_id,  # ID of the client requesting the code
        'created_at': time.time(),  # Timestamp of code creation
        'status': 'pending'  # Initial status of the code
    }
    
    # Log that the code and QR code are being sent to the client
    logger.info(f"Emitting verification code {code} with QR code to session {session_id}")
    # Send the code and QR code path to the client
    emit('verification_code', {'code': code, 'qr_code': f"/static/qr_codes/{code}.png"})
    
    # Define a function to expire the code after 10 minutes
    def expire_code():
        time.sleep(600)  # Wait 10 minutes (600 seconds)
        # Check if the code still exists and is pending
        if code in verification_codes and verification_codes[code]['status'] == 'pending':
            qr_path = f"static/qr_codes/{code}.png"
            # Remove the QR code file if it exists
            if os.path.exists(qr_path):
                os.remove(qr_path)
                logger.info(f"Deleted QR code for expired code: {code}")
            # Remove the code from tracking
            del verification_codes[code]
            logger.info(f"Expired verification code {code}")
    
    # Start a background thread to handle code expiration
    expiration_thread = threading.Thread(target=expire_code)
    expiration_thread.daemon = True  # Thread will terminate when main program exits
    expiration_thread.start()  # Start the expiration timer

# Background function to periodically clean up inactive sessions
def cleanup_inactive_sessions():
    while True:  # Run indefinitely
        current_time = time.time()  # Get the current timestamp
        inactive_sessions = []  # List to store IDs of sessions to clean up
        
        # Check each session for inactivity
        for session_id, session_data in active_sessions.items():
            # If the session has been inactive longer than the timeout
            if current_time - session_data['last_activity'] > config.SESSION_TIMEOUT:
                inactive_sessions.append(session_id)
        
        # Clean up all identified inactive sessions
        for session_id in inactive_sessions:
            cleanup_session(session_id)
        
        time.sleep(10)  # Wait 10 seconds before the next check

# SocketIO event handler for a client joining a verification session
@socketio.on('join_verification')
def handle_join_verification(data):
    session_id = request.sid  # Get the session ID of the joining client
    code = data.get('code')  # Extract the verification code from the data
    
    # Log the join attempt
    logger.info(f"Client {session_id} joining verification session with code: {code}")
    # Validate the code: must exist, be non-empty, and still pending
    if not code or code not in verification_codes or verification_codes[code]['status'] != 'pending':
        # If invalid, notify the client with an error message
        emit('session_error', {'message': 'Invalid or expired verification code'})
        return
    
    # Update the code’s status to indicate verification is in progress
    verification_codes[code]['status'] = 'in-progress'
    # Store the verifier’s session ID
    verification_codes[code]['verifier_id'] = session_id
    
    # Initialize the session data in active_sessions
    active_sessions[session_id] = {
        'code': code,  # Associate the code with this session
        'detector': None,  # Placeholder for the liveness detector
        'last_activity': time.time(),  # Set initial activity timestamp
        'attempts': 0  # Initialize attempt counter
    }
    
    # Create a new liveness detector instance for this session
    detector = LivenessDetector(config)
    active_sessions[session_id]['detector'] = detector  # Store the detector in session data
    
    join_room(code)  # Add the client to a SocketIO room named after the code
    requester_id = verification_codes[code]['requester_id']  # Get the ID of the original requester
    # Notify the requester that verification has started
    emit('verification_started', {'code': code}, room=requester_id)
    
    # Get the initial challenge text from the detector with initial state
    challenge_text, _, _, _ = detector.challenge_manager.get_challenge_status(
        detector.head_pose, detector.blink_count, detector.last_speech or ""
    )
    emit('challenge', {'text': challenge_text})

# SocketIO event handler for processing video frames (newer method, using process_frame)
@socketio.on('process_frame')
def handle_process_frame(data):
    session_id = request.sid  # Get the session ID of the client sending the frame
    code = data.get('code')  # Extract the verification code from the data
    
    current_time = time.time()  # Get the current timestamp
    # Rate-limit debug logging to once per second per session
    if config.DEBUG and (session_id not in last_log_time or current_time - last_log_time.get(session_id, 0) >= 1.0):
        logger.debug(f"Processing frame for session {session_id}, code {code}")
        last_log_time[session_id] = current_time  # Update last log time
    
    # Validate that the session exists and matches the code
    if session_id not in active_sessions or active_sessions[session_id]['code'] != code:
        logger.warning(f"Received frame from unknown or invalid session: {session_id}, code: {code}")
        emit('session_error', {'message': 'Invalid session or code'})
        return
    
    # Check if the session has exceeded max attempts
    if active_sessions[session_id].get('attempts', 0) >= 3:
        emit('max_attempts_reached')  # Notify client of limit reached
        cleanup_session(session_id, code)  # Clean up the session
        return
    
    # Update the session’s last activity timestamp
    active_sessions[session_id]['last_activity'] = time.time()
    
    # Extract and decode the frame
    try:
        image_data = data['image'].split(',')[1]  # Remove data URI prefix
        image_bytes = base64.b64decode(image_data)  # Convert base64 to binary
    except Exception as e:
        logger.error(f"Failed to decode base64 image data: {e}")
        emit('error', {'message': 'Invalid image data'})
        return
    
    # Check if the frame data is empty upfront
    nparr = np.frombuffer(image_bytes, np.uint8)
    if nparr.size == 0:
        logger.debug("Received empty frame buffer; waiting for next frame")
        emit('waiting_for_camera', {'message': 'Camera not ready yet'})
        return
    
    # Decode with limited retries
    frame = None
    max_retries = 10  # Reduced from 50: 1 second total
    retry_delay = 0.1  # 0.1s delay between retries
    for attempt in range(max_retries):
        try:
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)  # Decode into an OpenCV image
            if frame is None:
                logger.debug(f"Failed to decode frame on attempt {attempt + 1}/{max_retries}")
                time.sleep(retry_delay)
                continue
            
            logger.debug(f"Frame decoded successfully: shape={frame.shape}")
            break  # Exit loop if decoding succeeds
        
        except Exception as e:
            logger.error(f"Error decoding frame on attempt {attempt + 1}/{max_retries}: {e}")
            time.sleep(retry_delay)
    
    # If frame is still None after retries, skip processing
    if frame is None:
        logger.warning(f"Failed to decode frame after {max_retries} attempts")
        emit('error', {'message': 'Unable to process frame'})
        return
    
    # Process the frame using the session’s liveness detector
    try:
        detector = active_sessions[session_id]['detector']
        result = detector.process_frame(frame)  # Get detailed processing results
        
        # Extract display and debug frames from the result
        display_frame = result['display_frame']
        debug_frame = result['debug_frame']
        
        # Encode the display frame to base64 if it exists
        if display_frame is not None:
            _, buffer_disp = cv2.imencode('.jpg', display_frame)  # Convert to JPEG
            disp_b64 = base64.b64encode(buffer_disp).decode('utf-8')  # Encode to base64 string
            logger.debug("Display frame encoded")
        else:
            disp_b64 = None  # No display frame available
            logger.debug("Display frame is None")
        
        # Encode the debug frame to base64 if it exists
        debug_b64 = None
        if debug_frame is not None:
            _, buffer_dbg = cv2.imencode('.jpg', debug_frame)  # Convert to JPEG
            debug_b64 = base64.b64encode(buffer_dbg).decode('utf-8')  # Encode to base64 string
            logger.debug("Debug frame encoded")
        else:
            logger.debug("Debug frame is None")
        
        # Prepare the data packet to send back to the client
        emit_data = {
            'image': f"data:image/jpeg;base64,{disp_b64}" if disp_b64 else None,  # Display frame or None
            'debug_image': f"data:image/jpeg;base64,{debug_b64}" if debug_b64 else None,  # Debug frame or None
            'challenge': result['challenge_text'],  # Current challenge instruction
            'action_completed': result['action_completed'],  # Action status (True/False)
            'word_completed': result['word_completed'],  # Speech status (True/False)
            'time_remaining': result['time_remaining'],  # Time left for challenge
            'verification_result': result['verification_result'],  # 'PENDING', 'PASS', or 'FAIL'
            'exit_flag': result['exit_flag'],  # Whether to stop processing
            'duress_detected': result['duress_detected']  # Whether duress was detected
        }
        # Log the data being emitted for debugging
        logger.debug(f"Emitting processed_frame: has_image={bool(disp_b64)}, has_debug={bool(debug_b64)}")
        emit('processed_frame', emit_data)  # Send the data to the client
        
        # Handle the outcome if the challenge is complete
        if result['exit_flag']:
            # Increment the attempt counter
            active_sessions[session_id]['attempts'] = active_sessions[session_id].get('attempts', 0) + 1
            logger.debug(f"Attempt {active_sessions[session_id]['attempts']} for session {session_id}")
            requester_id = verification_codes[code]['requester_id']  # Get the requester’s ID
            
            # If duress is detected, notify requester and clean up
            if result['duress_detected']:
                emit('verification_result', {
                    'result': 'FAIL',
                    'code': code,
                    'duress_detected': True
                }, room=requester_id)
                cleanup_session(session_id, code)
            # If verification passes, notify requester and clean up
            elif result['verification_result'] == 'PASS':
                emit('verification_result', {
                    'result': 'PASS',
                    'code': code,
                    'duress_detected': False
                }, room=requester_id)
                cleanup_session(session_id, code)
            # If verification fails or times out
            elif result['verification_result'] == 'FAIL' or result['time_remaining'] <= 0:
                # If max attempts reached, notify requester and clean up
                if active_sessions[session_id]['attempts'] >= 3:
                    emit('verification_result', {
                        'result': 'FAIL',
                        'code': code,
                        'duress_detected': False
                    }, room=requester_id)
                    cleanup_session(session_id, code)
                else:
                    # Reset the detector for another attempt and send new challenge
                    detector.reset()
                    logger.info(f"Reset detector after failure/timeout for session {session_id}, attempt {active_sessions[session_id]['attempts']}")
                    challenge_text, _, _, _ = detector.challenge_manager.get_challenge_status(
                        detector.head_pose, detector.blink_count, detector.last_speech or ""
                    )
                    emit('challenge', {'text': challenge_text})
    
    except Exception as e:
        # Log any errors during frame processing
        logger.error(f"Error processing frame: {e}")
        # Notify the client of the error
        emit('error', {'message': str(e)})

# SocketIO event handler for when verification is explicitly completed
@socketio.on('verification_complete')
def handle_verification_complete(data):
    code = data.get('code')  # Get the verification code from the data
    result = data.get('result')  # Get the result ('PASS' or 'FAIL')
    
    # Check if the code exists in verification_codes
    if code and code in verification_codes:
        requester_id = verification_codes[code]['requester_id']  # Get the requester’s ID
        # Notify the requester of the verification result
        emit('verification_result', {
            'result': result,
            'code': code
        }, room=requester_id)
        # Clean up all sessions associated with this code
        for session_id, session_data in list(active_sessions.items()):
            if session_data.get('code') == code:
                cleanup_session(session_id, code)
        # Log the completion of the verification
        logger.info(f"Verification {code} completed with result: {result}")

# Main execution block, runs if the script is executed directly
if __name__ == '__main__':
    # Create the QR code directory if it doesn’t exist
    os.makedirs('static/qr_codes', exist_ok=True)
    # Start a background thread to clean up inactive sessions
    cleanup_thread = threading.Thread(target=cleanup_inactive_sessions)
    cleanup_thread.daemon = True  # Thread will stop when the main program exits
    cleanup_thread.start()  # Begin the cleanup loop
    
    # Launch the Flask-SocketIO server with configured settings
    socketio.run(
        app,  # Flask application instance
        host=config.HOST,  # Host address (e.g., '0.0.0.0' to listen on all interfaces)
        port=config.PORT,  # Port number (e.g., 8080) from config
        debug=config.DEBUG,  # Enable debug mode if True in config
        certfile=config.CERTFILE,  # Path to SSL certificate file for HTTPS
        keyfile=config.KEYFILE  # Path to SSL private key file for HTTPS
    )