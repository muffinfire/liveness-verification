// Wait for the HTML document to fully load before running the script
document.addEventListener('DOMContentLoaded', () => {
    // Get references to DOM elements used in the application
    const video = document.getElementById('webcam'); // The live webcam feed element
    const canvas = document.getElementById('overlay'); // Canvas for overlaying text or effects
    const ctx = canvas.getContext('2d'); // 2D drawing context for the canvas
    const debugFrame = document.getElementById('debug-frame'); // Element to display processed debug frames
    const challengeText = document.getElementById('challenge-text'); // Displays the current challenge (e.g., "Turn left")
    const actionStatus = document.getElementById('action-status'); // Shows if the action part of the challenge is complete
    const wordStatus = document.getElementById('word-status'); // Shows if the spoken word part is complete
    const timeRemaining = document.getElementById('time-remaining'); // Displays remaining time for the challenge
    const resultContainer = document.getElementById('result-container'); // Container for showing verification results
    const resultText = document.getElementById('result-text'); // Text element for result messages
    const resetButton = document.getElementById('reset-button'); // Button to manually reset the verification
    const videoContainer = document.querySelector('.video-container'); // Container for video and debug frame
    const processedFrameContainer = document.getElementById('processed-frame-container'); // Container for debug frame
    const sessionCode = document.getElementById('session-code').textContent; // Verification code from the HTML
    
    // Declare variables used throughout the script
    let socket; // Socket.IO connection to the server
    let isProcessing = false; // Flag to control frame capturing and sending
    let stream = null; // Webcam media stream
    let verificationAttempts = 0; // Counter for verification attempts
    const MAX_VERIFICATION_ATTEMPTS = 3; // Maximum allowed attempts before failing
    let isDebugMode = true; // Whether debug logging is enabled (set by server)
    let showDebugFrame = true; // Whether to show the debug frame (set by server)
    let frameCount = 0; // Counter for frames sent to the server
    
    // Mute the video to avoid audio feedback
    video.muted = true;
    video.volume = 0;

    // Initialize the Socket.IO connection and set up event listeners
    function initSocket() {
        console.log('Initializing socket connection for verification');
        socket = io(); // Create a new Socket.IO connection to the server
        
        // When the socket connects to the server
        socket.on('connect', () => {
            console.log('Connected to server for verification');
            socket.emit('join_verification', { code: sessionCode }); // Join the verification session with the code
            socket.emit('get_debug_status'); // Request debug settings from the server
        });
        
        // Handle debug status response from the server
        socket.on('debug_status', (data) => {
            isDebugMode = data.debug; // Set debug mode based on server config
            showDebugFrame = data.showDebugFrame; // Set whether to show debug frame
            console.log(`Debug mode: ${isDebugMode}, Show debug frame: ${showDebugFrame}`);
            
            // Adjust UI visibility based on whether debug frame should be shown
            if (showDebugFrame) {
                processedFrameContainer.classList.remove('hidden'); // Show the debug frame container
                debugFrame.classList.remove('hidden'); // Show the debug frame element
                videoContainer.classList.remove('single-video'); // Adjust layout for dual video display
            } else {
                processedFrameContainer.classList.add('hidden'); // Hide the debug frame container
                debugFrame.classList.add('hidden'); // Hide the debug frame element
                videoContainer.classList.add('single-video'); // Adjust layout for single video
            }
            
            isProcessing = true; // Start processing frames
            console.log('Processing started after debug status received');
            requestAnimationFrame(captureAndSendFrame); // Begin capturing and sending frames
        });
        
        // Handle processed frame data from the server
        socket.on('processed_frame', (data) => {
            // Log frame data every 30 frames if in debug mode
            if (isDebugMode && frameCount % 30 === 0) {
                console.log('Received processed_frame:', {
                    hasImage: !!data.image, // Whether a regular image was received
                    hasDebugImage: !!data.debug_image, // Whether a debug image was received
                    challenge: data.challenge, // Current challenge text
                    action: data.action_completed, // Action completion status
                    word: data.word_completed, // Word completion status
                    time: data.time_remaining, // Remaining time for the challenge
                    result: data.verification_result, // Verification result (PASS, FAIL, PENDING)
                    duress: data.duress_detected // Whether duress was detected
                });
            }
            
            // Update the debug frame or fallback to regular image
            if (showDebugFrame && data.debug_image) {
                debugFrame.src = data.debug_image; // Set debug frame source to the processed debug image
                processedFrameContainer.classList.add('visible'); // Make debug container visible
                videoContainer.classList.add('double-video'); // Adjust layout for two videos
            } else if (data.image) {
                debugFrame.src = data.image; // Use regular image as fallback if no debug image
                if (!showDebugFrame) {
                    processedFrameContainer.classList.remove('visible'); // Hide debug container if not in debug mode
                    videoContainer.classList.remove('double-video'); // Adjust layout for single video
                }
            }
        
            // Update challenge text on the UI
            if (data.challenge) {
                challengeText.textContent = data.challenge; // Display the current challenge
            } else {
                challengeText.textContent = 'Waiting for challenge...'; // Default message if no challenge
            }
            
            // Update action and word completion status indicators
            actionStatus.textContent = data.action_completed ? '✅' : '❌'; // Green check or red X
            wordStatus.textContent = data.word_completed ? '✅' : '❌'; // Green check or red X
            
            // Update remaining time display
            if (data.time_remaining !== undefined) {
                timeRemaining.textContent = Math.max(0, Math.ceil(data.time_remaining)) + 's'; // Show time left, min 0
            }
            
            // Handle verification result when it's not pending
            if (data.verification_result !== 'PENDING') {
                isProcessing = false; // Stop capturing new frames
                
                // Freeze the video and overlay the result
                video.pause(); // Pause the live video feed
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height); // Draw the last frame on the canvas
                canvas.style.display = 'block'; // Show the canvas over the video
                
                // Determine the result message and color
                let resultMessage, textColor;
                if (data.duress_detected) {
                    resultMessage = 'Duress Detected!'; // Message for duress detection
                    textColor = '#ff0000'; // Red color
                    applyVideoEffect('duress'); // Apply duress visual effect
                } else if (data.verification_result === 'PASS') {
                    resultMessage = 'Verification Successful!'; // Success message
                    textColor = '#4cd137'; // Green color
                    applyVideoEffect('success'); // Apply success visual effect
                } else {
                    resultMessage = 'Verification Failed!'; // Failure message
                    textColor = '#e8603e'; // Orange-red color
                    applyVideoEffect('failure'); // Apply failure visual effect
                }
                
                // Draw a semi-transparent background for the result text
                ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
                ctx.fillRect(0, canvas.height / 2 - 40, canvas.width, 80);
                // Draw the result text on the canvas
                ctx.fillStyle = textColor;
                ctx.font = 'bold 30px Arial';
                ctx.textAlign = 'center';
                ctx.fillText(resultMessage, canvas.width / 2, canvas.height / 2 + 10);
                
                // Update the result container in the UI
                resultText.textContent = resultMessage;
                resultText.className = `result-text ${data.duress_detected ? 'duress' : data.verification_result === 'PASS' ? 'success' : 'failure'}`;
                resultContainer.classList.remove('hidden'); // Show the result container
                
                verificationAttempts++; // Increment the attempt counter
                console.log(`Attempt ${verificationAttempts} of ${MAX_VERIFICATION_ATTEMPTS}`);
                
                // Handle final outcomes or reset for next attempt
                if (data.verification_result === 'PASS' || data.duress_detected || verificationAttempts >= MAX_VERIFICATION_ATTEMPTS) {
                    setTimeout(() => window.location.href = '/', 3000); // Redirect to home after 3 seconds
                } else {
                    setTimeout(() => {
                        isProcessing = true; // Resume processing
                        canvas.style.display = 'none'; // Hide the canvas
                        video.play(); // Resume the video
                        removeVideoEffect(); // Remove visual effect
                        requestAnimationFrame(captureAndSendFrame); // Start capturing frames again
                    }, 1000); // Wait 1 second before resuming
                }
            } else if (isProcessing) {
                requestAnimationFrame(captureAndSendFrame); // Continue capturing if still processing
            }
            
            // Handle timeout when time runs out but result is still pending
            if (data.time_remaining <= 0 && data.verification_result === 'PENDING') {
                socket.emit('reset', { code: sessionCode }); // Request a reset from the server
                verificationAttempts++; // Increment attempt counter
                
                if (verificationAttempts >= MAX_VERIFICATION_ATTEMPTS) {
                    // If max attempts reached, show failure and redirect
                    resultText.textContent = 'Maximum attempts reached. Verification failed.';
                    resultText.className = 'result-text failure';
                    resultContainer.classList.remove('hidden');
                    isProcessing = false;
                    applyVideoEffect('failure');
                    setTimeout(() => window.location.href = '/', 3000); // Redirect after 3 seconds
                } else {
                    // Show attempt number and wait for new challenge
                    challengeText.textContent = `Attempt ${verificationAttempts + 1} of ${MAX_VERIFICATION_ATTEMPTS}...`;
                    setTimeout(() => {
                        challengeText.textContent = 'Waiting for new challenge...';
                        isProcessing = true;
                        requestAnimationFrame(captureAndSendFrame); // Resume frame capture
                    }, 2000); // Wait 2 seconds before resuming
                }
            }
        });
        
        // Handle server errors
        socket.on('error', (data) => {
            console.error('Server error:', data.message);
            alert('Server error: ' + data.message); // Alert the user
        });
        
        // Handle max attempts reached event from server
        socket.on('max_attempts_reached', () => {
            isProcessing = false; // Stop processing
            resultText.textContent = 'Maximum verification attempts reached.';
            resultContainer.classList.remove('hidden');
            applyVideoEffect('failure');
            setTimeout(() => window.location.href = '/', 5000); // Redirect after 5 seconds
        });
        
        // Handle disconnection from the server
        socket.on('disconnect', () => {
            console.log('Disconnected from server');
            isProcessing = false; // Stop processing on disconnect
        });
        
        // Handle new challenge text from the server
        socket.on('challenge', (data) => {
            if (data && data.text) {
                challengeText.textContent = data.text; // Update challenge text
            }
        });
    }
    
    // Apply visual effects to the video container based on verification result
    function applyVideoEffect(effect) {
        if (effect === 'success') {
            videoContainer.classList.add('success-overlay'); // Green overlay for success
        } else if (effect === 'failure') {
            videoContainer.classList.add('failure-overlay'); // Red overlay for failure
        } else if (effect === 'duress') {
            videoContainer.classList.add('duress-overlay'); // Special overlay for duress
        }
    }
    
    // Remove all visual effects from the video container
    function removeVideoEffect() {
        videoContainer.classList.remove('success-overlay', 'failure-overlay', 'duress-overlay');
    }
    
    // Capture a frame from the webcam and send it to the server
    function captureAndSendFrame() {
        if (!isProcessing) {
            console.log('Processing stopped, not capturing frame');
            return; // Exit if not processing
        }
        
        try {
            // Create an offscreen canvas to capture the video frame
            const offscreenCanvas = document.createElement('canvas');
            offscreenCanvas.width = video.videoWidth;
            offscreenCanvas.height = video.videoHeight;
            const offscreenCtx = offscreenCanvas.getContext('2d');
            offscreenCtx.drawImage(video, 0, 0, offscreenCanvas.width, offscreenCanvas.height); // Draw video frame
            const imageData = offscreenCanvas.toDataURL('image/jpeg', 0.8); // Convert to JPEG with 80% quality
            
            // Log frame sending every 30 frames in debug mode
            if (isDebugMode && frameCount % 30 === 0) {
                console.log(`Sending frame #${frameCount}`);
            }
            
            // Send the frame to the server with the session code
            socket.emit('process_frame', {
                image: imageData,
                code: sessionCode
            });
            frameCount++; // Increment frame counter
        } catch (err) {
            console.error('Error capturing frame:', err); // Log any errors
        }
    }
    
    // Initialize the webcam and start the video feed
    async function initWebcam() {
        try {
            // Request access to the user's webcam and microphone
            stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    width: { ideal: 640 }, // Ideal video width
                    height: { ideal: 480 }, // Ideal video height
                    facingMode: 'user' // Use the front-facing camera
                },
                audio: true // Enable audio for speech detection
            });
            video.srcObject = stream; // Set the video source to the webcam stream
            video.onloadedmetadata = () => { // When video metadata is loaded
                video.play().catch(err => console.error('Error playing video:', err)); // Start playing the video
                canvas.width = video.videoWidth; // Set canvas size to match video
                canvas.height = video.videoHeight;
                requestAnimationFrame(captureAndSendFrame); // Start capturing frames
            };
        } catch (err) {
            console.error('Error accessing webcam:', err); // Log webcam access errors
            alert('Error accessing webcam: ' + err.message); // Alert the user
        }
    }
    
    // Add click event listener to the reset button
    resetButton.addEventListener('click', () => {
        if (socket && socket.connected) { // Check if socket is connected
            socket.emit('reset', { code: sessionCode }); // Request a reset from the server
            isProcessing = true; // Resume processing
            removeVideoEffect(); // Clear any visual effects
            requestAnimationFrame(captureAndSendFrame); // Start capturing frames again
        }
    });
    
    // Initialize the application
    function init() {
        initSocket(); // Set up the socket connection
        initWebcam(); // Start the webcam
    }
    
    // Clean up resources when the page is unloaded
    window.addEventListener('beforeunload', () => {
        if (socket && socket.connected) {
            socket.disconnect(); // Disconnect from the server
        }
        if (stream) {
            stream.getTracks().forEach(track => track.stop()); // Stop all webcam tracks
        }
    });
    
    init(); // Run the initialization function
});