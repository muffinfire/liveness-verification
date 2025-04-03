// Global variables
let socket;
let webcam;
let overlay;
let overlayContext;
let processedFrame;
let debugFrame;
let challengeText;
let actionStatus;
let wordStatus;
let blinkStatus;
let timeRemaining;
let resultContainer;
let resultText;
let resetButton;
let sessionCode;
let isProcessing = false;
let verificationAttempts = 0;
let frameTransmissionLatencies = []; // For network quality estimation
let lastNetworkCheckTime = 0;
let currentNetworkQuality = 'medium'; // Default quality
let stableNetworkQuality = 'medium'; // Quality confirmed by server or stable client calculation
let lastQualityChangeTime = 0;
let isPortrait = window.innerHeight > window.innerWidth; // Initial orientation check

// Constants
const MAX_VERIFICATION_ATTEMPTS = 3;
const NETWORK_CHECK_INTERVAL = 5000; // Check network every 5 seconds
const QUALITY_STABILITY_THRESHOLD = 10000; // 10 seconds of stability before upgrade
const qualityOrder = ['very_low', 'low', 'medium', 'high']; // In order of increasing quality

// Initialize the application when the DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Get DOM elements
    webcam = document.getElementById('webcam');
    overlay = document.getElementById('overlay');
    processedFrame = document.getElementById('processed-frame');
    debugFrame = document.getElementById('debug-frame');
    challengeText = document.getElementById('challenge-text');
    actionStatus = document.getElementById('action-status');
    wordStatus = document.getElementById('word-status');
    blinkStatus = document.getElementById('blink-status');
    timeRemaining = document.getElementById('time-remaining');
    resultContainer = document.getElementById('result-container');
    resultText = document.getElementById('result-text');
    resetButton = document.getElementById('reset-button');
    sessionCode = document.getElementById('session-code')?.textContent; // Use optional chaining

    // Ensure required elements exist before proceeding
    if (!webcam || !overlay || !processedFrame || !debugFrame || !sessionCode || !resetButton) {
        console.error("One or more required elements not found in the DOM.");
        // Optionally display an error to the user
        return;
    }

    overlayContext = overlay.getContext('2d');

    // Initialize Socket.IO connection
    socket = io();

    // Check device orientation on load and add listeners
    checkOrientation(); // Initial check
    window.addEventListener('resize', checkOrientation);
    // More reliable orientation detection
    if (window.screen && window.screen.orientation) {
        window.screen.orientation.addEventListener('change', checkOrientation);
    } else {
        // Fallback for older browsers
        window.addEventListener('orientationchange', checkOrientation);
    }


    // Set up event listeners
    resetButton.addEventListener('click', resetVerification);

    // Start the verification process
    initializeVerification();
});

// Check and update device orientation, notify server, update CSS class
function checkOrientation() {
    const previousOrientation = isPortrait;
    isPortrait = window.innerHeight > window.innerWidth;

    // Update body class for global CSS rules if needed (optional)
    // document.body.classList.toggle('portrait-mode', isPortrait);
    // document.body.classList.toggle('landscape-mode', !isPortrait);

    // Update specific container classes for aspect ratio switching
    const videoWrapper = document.querySelector('.video-wrapper');
    const processedContainer = document.getElementById('processed-frame-container');

    if (videoWrapper) videoWrapper.classList.toggle('portrait-mode', isPortrait);
    if (processedContainer) processedContainer.classList.toggle('portrait-mode', isPortrait);


    // Recalculate overlay size after orientation change (slight delay for rendering)
    setTimeout(resizeOverlayCanvas, 100);

    // Notify server if orientation changed
    if (previousOrientation !== isPortrait && socket && socket.connected) {
        socket.emit('orientation_change', {
            isPortrait: isPortrait,
            width: window.innerWidth, // Viewport width
            height: window.innerHeight // Viewport height
        });
        console.log(`Orientation changed to ${isPortrait ? 'portrait' : 'landscape'}`);
    }
}

// Function to resize the overlay canvas based on webcam's displayed size
function resizeOverlayCanvas() {
     if (!webcam || !overlay || !overlayContext) return;

    // Get the actual computed dimensions of the webcam element
    const videoStyle = window.getComputedStyle(webcam);
    const videoDisplayWidth = parseFloat(videoStyle.width);
    const videoDisplayHeight = parseFloat(videoStyle.height);

     // Check if dimensions are valid
    if (videoDisplayWidth > 0 && videoDisplayHeight > 0) {
        // Set overlay canvas size to match the DISPLAYED video size
        overlay.width = videoDisplayWidth;
        overlay.height = videoDisplayHeight;
        console.log(`Overlay resized to: ${overlay.width}x${overlay.height}`);
    } else {
        // Fallback or wait if dimensions aren't ready
        console.warn("Webcam dimensions not ready for overlay sizing.");
         // Optionally try again after a short delay
        // setTimeout(resizeOverlayCanvas, 200);
    }
}


// Initialize the verification process
function initializeVerification() {
    // Request camera access
    navigator.mediaDevices.getUserMedia({
        video: {
            // Request ideal resolution, browser will try to match
            width: { ideal: 640 },
            height: { ideal: 480 },
            facingMode: 'user'
        },
        audio: true // Request audio access
    })
    .then(stream => {
        webcam.srcObject = stream;

        // Wait for video metadata to load to get dimensions
        webcam.onloadedmetadata = () => {
            console.log(`Native video dimensions: ${webcam.videoWidth}x${webcam.videoHeight}`);

            // Initial resize of overlay canvas
            resizeOverlayCanvas();

            // Make overlay visible and position it (ensure parent has position: relative)
            overlay.style.display = 'block';
            overlay.style.position = 'absolute';
            overlay.style.top = '0';
            overlay.style.left = '0';

             // Join the verification session
            socket.emit('join_verification', {
                code: sessionCode,
                clientInfo: {
                    userAgent: navigator.userAgent,
                    screenWidth: window.screen.width,
                    screenHeight: window.screen.height,
                    isPortrait: isPortrait, // Send initial orientation
                    // Add any other relevant info
                }
            });

            // Request debug status (optional)
            socket.emit('get_debug_status');

            // Start processing frames
            isProcessing = true;
            requestAnimationFrame(captureAndSendFrame);

            // Set up audio processing
            setupAudioProcessing(stream);
        };

        webcam.onplay = () => {
             // Ensure overlay is resized again once video starts playing
             resizeOverlayCanvas();
        };

    })
    .catch(error => {
        console.error('Error accessing camera/microphone:', error);
        // Display a user-friendly error message
        const errorMsg = 'Camera and microphone access are required for verification. Please allow access and refresh the page.';
        if (resultContainer && resultText) {
            resultText.textContent = errorMsg;
            resultText.className = 'result-text failure';
            resultContainer.classList.remove('hidden');
            resetButton.classList.add('hidden'); // Hide reset button
        } else {
            alert(errorMsg);
        }
    });

    // Set up Socket.IO event handlers
    setupSocketHandlers();
}

// Set up Socket.IO event handlers
function setupSocketHandlers() {
    socket.on('connect', () => console.log('Connected to server'));
    socket.on('disconnect', () => {
        console.log('Disconnected from server');
        isProcessing = false;
        alert('Disconnected from server. Please refresh the page to reconnect.');
    });

    socket.on('challenge', (data) => {
        if (challengeText) challengeText.textContent = data.text;
        resetStatusIndicators();
    });

    socket.on('debug_status', (data) => {
        // Show/hide debug frame container based on server config
        const debugContainer = document.getElementById('processed-frame-container'); // Assuming debug is inside this
        if (debugContainer) {
             debugContainer.classList.toggle('hidden', !(data.debug && data.showDebugFrame));
        }
    });

    socket.on('processed_frame', (data) => {
        if (!isProcessing && data.verification_result === 'PENDING') {
             // Avoid processing frames if we are already showing a final result
             console.log("Ignoring frame, verification already concluded.");
             return;
        }

        // Update challenge status if provided
        if (data.challenge && challengeText) {
            challengeText.textContent = data.challenge;
        }

        // Update status indicators
        if (actionStatus) actionStatus.innerHTML = data.action_completed ? '✅' : '❌';
        if (wordStatus) wordStatus.innerHTML = data.word_completed ? '✅' : '❌';
        if (blinkStatus) blinkStatus.innerHTML = data.blink_completed ? '✅' : '❌';
        if (timeRemaining) timeRemaining.textContent = `${Math.ceil(data.time_remaining)}s`;

        // Calculate latency for network quality estimation
        if (data.timestamp) {
            const latency = performance.now() - data.timestamp;
            if (!isNaN(latency)){ // Ensure latency is a number
                 frameTransmissionLatencies.push(latency);
                 if (frameTransmissionLatencies.length > 10) {
                      frameTransmissionLatencies.shift(); // Keep last 10 values
                 }
            }
        }

        // Update processed frame image
        if (data.image && processedFrame) {
            processedFrame.src = data.image;
        } else if (processedFrame) {
             // Optionally clear or show a placeholder if no image received
             // processedFrame.src = 'placeholder.jpg';
        }

        // Update debug frame image
        if (data.debug_image && debugFrame) {
            debugFrame.src = data.debug_image;
        } else if (debugFrame) {
             // Optionally clear or hide
             // debugFrame.src = '';
        }

        // Handle verification result
        if (data.exit_flag && data.verification_result !== 'PENDING') {
            isProcessing = false; // Stop processing further frames

            let message = '';
            let resultClass = '';
            let effectClass = '';

            if (data.verification_result === 'PASS') {
                message = 'Verification Successful!';
                resultClass = 'success';
                effectClass = 'success';
            } else { // FAIL or DURESS treated as failure for display
                 if (data.duress_detected) {
                      message = 'Duress Detected! Verification Failed.';
                      resultClass = 'duress'; // Specific class for duress text styling
                      effectClass = 'duress'; // Specific class for video effect
                 } else {
                      message = 'Verification Failed!';
                      resultClass = 'failure';
                      effectClass = 'failure';
                 }
                 verificationAttempts++; // Count failed attempts
                 console.log(`Verification attempt ${verificationAttempts} failed.`);
            }

            if (resultText) resultText.textContent = message;
            if (resultText) resultText.className = `result-text ${resultClass}`;
            if (resultContainer) resultContainer.classList.remove('hidden');
            applyVideoEffect(effectClass); // Apply visual effect

            // Reset network stats
            frameTransmissionLatencies = [];
            lastNetworkCheckTime = 0;

            // Check for max attempts
             if (verificationAttempts >= MAX_VERIFICATION_ATTEMPTS && data.verification_result !== 'PASS') {
                 if (resultText) resultText.textContent += ` Maximum attempts (${MAX_VERIFICATION_ATTEMPTS}) reached.`;
                 // Optionally redirect after a delay
                 // setTimeout(() => window.location.href = '/', 5000);
             } else if (data.verification_result !== 'PASS') {
                  // Allow reset if attempts remain
                  if(resetButton) resetButton.classList.remove('hidden');
             } else {
                 // Hide reset button on success
                 if (resetButton) resetButton.classList.add('hidden');
                 // Optionally redirect on success after delay
                  // setTimeout(() => window.location.href = '/success_page', 3000);
             }


        } else if (isProcessing) {
            // Continue processing: Estimate network quality periodically
            const now = performance.now();
            if (now - lastNetworkCheckTime > NETWORK_CHECK_INTERVAL) {
                updateNetworkQuality();
                lastNetworkCheckTime = now;
            }
            // Request next frame
            requestAnimationFrame(captureAndSendFrame);
        }
    });

    socket.on('network_quality', (data) => {
        // Handle network quality suggestions from the server (e.g., force downgrade)
        if (data.quality && data.quality !== stableNetworkQuality) {
            const serverQualityIndex = qualityOrder.indexOf(data.quality);
            const clientQualityIndex = qualityOrder.indexOf(stableNetworkQuality);

            // Server can force a downgrade immediately
            if (serverQualityIndex < clientQualityIndex) {
                console.log(`Server forced network quality downgrade to: ${data.quality}`);
                stableNetworkQuality = data.quality;
                currentNetworkQuality = data.quality; // Apply immediately
                lastQualityChangeTime = performance.now();
                applyQualitySettings(data.quality); // Optional: apply client-side settings
            } else {
                // Server might suggest an upgrade, but client decides based on stability
                console.log(`Server suggested quality: ${data.quality}. Client maintaining: ${stableNetworkQuality}`);
            }
        }
    });

    socket.on('session_error', (data) => {
         console.error('Session error:', data.message);
         isProcessing = false;
         if (resultText) resultText.textContent = `Error: ${data.message}. Please try again or generate a new code.`;
         if (resultText) resultText.className = 'result-text failure';
         if (resultContainer) resultContainer.classList.remove('hidden');
         if (resetButton) resetButton.classList.add('hidden');
    });


    socket.on('error', (data) => {
        console.error('Server error:', data.message);
        alert('An unexpected error occurred: ' + data.message);
        isProcessing = false;
    });

    socket.on('max_attempts_reached', () => {
        console.log("Max attempts reached signal from server.");
        isProcessing = false;
        if (resultText) resultText.textContent = `Maximum verification attempts (${MAX_VERIFICATION_ATTEMPTS}) reached. Verification failed.`;
        if (resultText) resultText.className = 'result-text failure';
        if (resultContainer) resultContainer.classList.remove('hidden');
        if (resetButton) resetButton.classList.add('hidden');
        applyVideoEffect('failure');
        // Optionally redirect after a delay
        // setTimeout(() => window.location.href = '/', 5000);
    });

    socket.on('reset_confirmed', () => {
        console.log('Reset confirmed by server');
        resetStatusIndicators();
        if (challengeText) challengeText.textContent = "Waiting for new challenge...";
        if (resultContainer) resultContainer.classList.add('hidden'); // Hide previous result
        if (resetButton) resetButton.classList.add('hidden'); // Hide reset button until next failure
        removeVideoEffect(); // Remove visual effect
        isProcessing = true; // Re-enable processing
        requestAnimationFrame(captureAndSendFrame); // Start capturing again
    });

    // Note: Partner video frame updates are handled by landing.js
}

// Capture frame, draw to overlay, send to server
function captureAndSendFrame() {
    // Stop if not processing, or webcam/overlay not ready
    if (!isProcessing || !webcam || !webcam.videoWidth || !overlay || !overlayContext) {
        // If processing should be active but elements aren't ready, maybe retry shortly
        if (isProcessing) {
             console.warn("captureAndSendFrame called but elements not ready. Retrying shortly.");
             setTimeout(() => requestAnimationFrame(captureAndSendFrame), 100); // Retry after 100ms
        }
        return;
    }

    try {
        // Ensure overlay matches webcam display size before drawing
        if (overlay.width !== webcam.clientWidth || overlay.height !== webcam.clientHeight) {
             resizeOverlayCanvas();
             // Wait a frame for resize to apply before drawing
             requestAnimationFrame(captureAndSendFrame);
             return;
        }

        // Draw the current webcam frame onto the overlay canvas
        // This canvas content is what gets sent
        overlayContext.drawImage(webcam, 0, 0, overlay.width, overlay.height);

        // Get frame data with dynamic quality based on network estimation
        const jpegQuality = getJpegQualityForNetwork(currentNetworkQuality);
        const frameData = overlay.toDataURL('image/jpeg', jpegQuality);

        // Send frame data along with metadata
        socket.emit('process_frame', {
            image: frameData,
            code: sessionCode,
            timestamp: performance.now(), // Timestamp for latency calculation
            networkQuality: currentNetworkQuality, // Inform server of client's perceived quality
            isPortrait: isPortrait, // Send current orientation
            // detectionMode: 'normal' // Example: Add if needed
        });

    } catch (error) {
        console.error('Error capturing/sending frame:', error);
        // Optionally try to recover or stop processing
        // isProcessing = false;
        // alert("An error occurred while capturing video.");
    }
}

// Determine JPEG quality based on network estimation
function getJpegQualityForNetwork(quality) {
     // Map quality string to a numerical JPEG quality value (0.0 to 1.0)
     // Adjust these values based on testing for performance/visuals
    switch (quality) {
        case 'high': return 0.8; // Higher quality
        case 'medium': return 0.65; // Default/Medium quality
        case 'low': return 0.5; // Lower quality
        case 'very_low': return 0.35; // Very low quality
        default: return 0.65; // Fallback to medium
    }
}

// Set up audio processing (if needed)
function setupAudioProcessing(stream) {
    try {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioContext.createMediaStreamSource(stream);
        // Use a smaller buffer size for potentially lower latency, adjust if needed
        const processor = audioContext.createScriptProcessor(2048, 1, 1);

        source.connect(processor);
        processor.connect(audioContext.destination); // Connect to destination to avoid issues

        processor.onaudioprocess = (e) => {
            if (!isProcessing) return;

            const inputData = e.inputBuffer.getChannelData(0);

            // Basic silence detection (optional) - adjust threshold
            let sum = 0;
            for (let i = 0; i < inputData.length; i++) {
                 sum += Math.abs(inputData[i]);
            }
            const avg = sum / inputData.length;
            if (avg < 0.005) { // If average amplitude is very low, don't send
                 // console.log("Audio below threshold, skipping send.");
                 return;
            }


            // Convert to 16-bit PCM
            const buffer = new ArrayBuffer(inputData.length * 2);
            const view = new DataView(buffer);
            for (let i = 0; i < inputData.length; i++) {
                const s = Math.max(-1, Math.min(1, inputData[i]));
                view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
            }

            // Send audio chunk to server (consider base64 encoding if needed by server)
            socket.emit('audio_chunk', {
                 code: sessionCode, // Include session code
                 audio: buffer // Send ArrayBuffer directly if socket.io handles binary
                 // audio: arrayBufferToBase64(buffer) // Or send base64
            });
        };
         console.log("Audio processing setup complete.");

    } catch (error) {
        console.error("Failed to setup audio processing:", error);
        // Inform user or disable audio features if essential
        // alert("Could not initialize audio processing.");
    }
}

// Convert ArrayBuffer to Base64 (if sending base64)
function arrayBufferToBase64(buffer) {
    let binary = '';
    const bytes = new Uint8Array(buffer);
    const len = bytes.byteLength;
    for (let i = 0; i < len; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return window.btoa(binary);
}


// Reset status indicators (checkmark/cross)
function resetStatusIndicators() {
    if (actionStatus) actionStatus.innerHTML = '❌';
    if (wordStatus) wordStatus.innerHTML = '❌';
    if (blinkStatus) blinkStatus.innerHTML = '❌';
}

// Handle reset button click
function resetVerification() {
    console.log("Reset verification requested by user.");
    if (verificationAttempts >= MAX_VERIFICATION_ATTEMPTS) {
        alert(`Maximum verification attempts (${MAX_VERIFICATION_ATTEMPTS}) reached.`);
        return;
    }
    if (socket && socket.connected) {
        socket.emit('reset', { code: sessionCode });
        // UI updates will be handled by 'reset_confirmed' event
    } else {
        alert("Not connected to server. Cannot reset.");
    }
}

// Update network quality based on calculated latency
function updateNetworkQuality() {
    if (frameTransmissionLatencies.length < 5) return; // Need a few samples

    const avgLatency = frameTransmissionLatencies.reduce((a, b) => a + b, 0) / frameTransmissionLatencies.length;

    let newQuality;
    // Adjust latency thresholds based on testing
    if (avgLatency > 600) newQuality = 'very_low';
    else if (avgLatency > 400) newQuality = 'low';
    else if (avgLatency > 200) newQuality = 'medium';
    else newQuality = 'high';

    const now = performance.now();
    const timeSinceLastChange = now - lastQualityChangeTime;
    const currentQualityIndex = qualityOrder.indexOf(currentNetworkQuality);
    const newQualityIndex = qualityOrder.indexOf(newQuality);

    let qualityChanged = false;

    if (newQualityIndex > currentQualityIndex) {
        // Upgrade requires stability
        if (timeSinceLastChange > QUALITY_STABILITY_THRESHOLD) {
            currentNetworkQuality = newQuality;
            qualityChanged = true;
        }
    } else if (newQualityIndex < currentQualityIndex) {
        // Downgrade happens immediately
        currentNetworkQuality = newQuality;
        qualityChanged = true;
    }

    if (qualityChanged) {
        lastQualityChangeTime = now;
        stableNetworkQuality = currentNetworkQuality; // Update stable quality as well
        console.log(`Network quality changed to: ${currentNetworkQuality} (Avg Latency: ${avgLatency.toFixed(0)}ms)`);
        applyQualitySettings(currentNetworkQuality); // Apply client-side changes if any

        // Inform the server about the client's calculated quality
        socket.emit('client_network_quality', {
            code: sessionCode,
            quality: currentNetworkQuality,
            latency: avgLatency
        });
    }
}

// Apply client-side settings based on quality (optional)
function applyQualitySettings(quality) {
    console.log(`Applying settings for quality: ${quality}`);
    // Example: Could adjust frame rate capture, but usually handled by requestAnimationFrame
    // Example: Could change getUserMedia constraints (requires renegotiation)
}

// Apply/Remove visual effect overlay based on verification result
function applyVideoEffect(effect) {
    const container = document.querySelector('.video-section'); // Apply to the main container
    if (!container) return;
    removeVideoEffect(); // Clear previous effects first
    container.classList.add(`${effect}-overlay`);
}

function removeVideoEffect() {
    const container = document.querySelector('.video-section');
    if (!container) return;
    container.classList.remove('success-overlay', 'failure-overlay', 'duress-overlay');
}