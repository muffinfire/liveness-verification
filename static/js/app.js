// Modified version of app.js with fixes for debug and partner frames
// This ensures all video frames maintain proper aspect ratio in both portrait and landscape modes

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
let frameTransmissionTimes = [];
let frameTransmissionLatencies = [];
let lastNetworkCheckTime = 0;
let currentNetworkQuality = 'medium'; // Default quality
let stableNetworkQuality = 'medium';
let lastQualityChangeTime = 0;
let isPortrait = false; // Track device orientation

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
    overlayContext = overlay.getContext('2d');
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
    sessionCode = document.getElementById('session-code').textContent;
    
    // Initialize Socket.IO connection
    socket = io();
    
    // Check device orientation on load and when it changes
    checkOrientation();
    window.addEventListener('resize', checkOrientation);
    
    // Set up event listeners
    resetButton.addEventListener('click', resetVerification);
    
    // Start the verification process
    initializeVerification();
});

// Check and update device orientation
function checkOrientation() {
    const prevOrientation = isPortrait;
    isPortrait = window.innerHeight > window.innerWidth;
    
    // If orientation changed, notify the server
    if (prevOrientation !== isPortrait && socket) {
        socket.emit('orientation_change', {
            isPortrait: isPortrait,
            width: window.innerWidth,
            height: window.innerHeight
        });
        console.log(`Orientation changed to ${isPortrait ? 'portrait' : 'landscape'}`);
    }
    
    // Update CSS classes for debug and partner frames if needed
    const processedFrameContainer = document.getElementById('processed-frame-container');
    if (processedFrameContainer) {
        if (isPortrait) {
            processedFrameContainer.classList.add('portrait-mode');
        } else {
            processedFrameContainer.classList.remove('portrait-mode');
        }
    }
}

// Initialize the verification process
function initializeVerification() {
    // Request camera access
    navigator.mediaDevices.getUserMedia({ 
        video: { 
            width: { ideal: 640 },
            height: { ideal: 480 },
            facingMode: 'user'
        }, 
        audio: true 
    })
    .then(stream => {
        webcam.srcObject = stream;
        
        // Set up canvas for overlay
        overlay.width = webcam.videoWidth;
        overlay.height = webcam.videoHeight;
        overlay.style.display = 'block';
        
        // Wait for video to be ready
        webcam.onloadedmetadata = () => {
            console.log(`Video dimensions: ${webcam.videoWidth}x${webcam.videoHeight}`);
            
            // Join the verification session
            socket.emit('join_verification', { 
                code: sessionCode,
                clientInfo: {
                    userAgent: navigator.userAgent,
                    screenWidth: window.screen.width,
                    screenHeight: window.screen.height,
                    isPortrait: isPortrait
                }
            });
            
            // Request debug status
            socket.emit('get_debug_status');
            
            // Start processing frames
            isProcessing = true;
            requestAnimationFrame(captureAndSendFrame);
            
            // Set up audio processing if needed
            setupAudioProcessing(stream);
        };
    })
    .catch(error => {
        console.error('Error accessing camera:', error);
        alert('Camera access is required for verification. Please allow access and try again.');
    });
    
    // Set up Socket.IO event handlers
    setupSocketHandlers();
}

// Set up Socket.IO event handlers
function setupSocketHandlers() {
    // Handle connection event
    socket.on('connect', () => {
        console.log('Connected to server');
    });
    
    // Handle challenge event
    socket.on('challenge', (data) => {
        challengeText.textContent = data.text;
        resetStatusIndicators();
    });
    
    // Handle debug status event
    socket.on('debug_status', (data) => {
        if (data.debug && data.showDebugFrame) {
            document.getElementById('processed-frame-container').classList.remove('hidden');
            debugFrame.classList.remove('hidden');
        }
    });
    
    // Handle processed frame event
    socket.on('processed_frame', (data) => {
        // Update challenge status
        if (data.challenge) {
            challengeText.textContent = data.challenge;
        }
        
        // Update status indicators
        actionStatus.innerHTML = data.action_completed ? '✅' : '❌';
        wordStatus.innerHTML = data.word_completed ? '✅' : '❌';
        blinkStatus.innerHTML = data.blink_completed ? '✅' : '❌';
        timeRemaining.textContent = `${Math.ceil(data.time_remaining)}s`;
        
        // Calculate latency
        if (data.timestamp) {
            const latency = performance.now() - data.timestamp;
            if (frameTransmissionLatencies.length >= 10) {
                frameTransmissionLatencies.shift();
            }
            frameTransmissionLatencies.push(latency);
        }
        
        // Update processed frame if available
        if (data.image) {
            processedFrame.src = data.image;
        }
        
        // Update debug frame if available
        if (data.debug_image) {
            debugFrame.src = data.debug_image;
        }
        
        // Handle verification result
        if (data.exit_flag && data.verification_result !== 'PENDING') {
            isProcessing = false; // Stop processing
            
            if (data.verification_result === 'PASS') {
                resultText.textContent = 'Verification Successful!';
                resultText.className = 'result-text success';
                applyVideoEffect('success');
            } else if (data.verification_result === 'FAIL') {
                if (data.duress_detected) {
                    resultText.textContent = 'Duress Detected! Verification Failed.';
                    resultText.className = 'result-text duress';
                    applyVideoEffect('duress');
                } else {
                    resultText.textContent = 'Verification Failed!';
                    resultText.className = 'result-text failure';
                    applyVideoEffect('failure');
                }
            }
            
            resultContainer.classList.remove('hidden');
            
            // Reset stats
            frameTransmissionLatencies = [];
            frameTransmissionTimes = [];
            
            // Add delay before redirect on success
            if (data.verification_result === 'PASS') {
                setTimeout(() => {
                    removeVideoEffect(); // Remove visual effect
                    
                    // Update challenge text to indicate transition
                    challengeText.textContent = 'Preparing new challenge...';
                    
                    // Add additional delay before starting the next challenge to compensate for animation time
                    setTimeout(() => {
                        requestAnimationFrame(captureAndSendFrame); // Start capturing frames again
                    }, 2000); // Additional 2 second delay before starting next challenge
                }, 1000); // Initial 1 second delay
            }
        } else if (isProcessing) {
            // Calculate frame transmission time for network quality estimation
            const now = performance.now();
            if (frameTransmissionTimes.length > 0) {
                const lastTransmissionTime = frameTransmissionTimes[frameTransmissionTimes.length - 1];
                const transmissionTime = now - lastTransmissionTime;
                
                // Keep only the last 10 transmission times
                if (frameTransmissionTimes.length >= 10) {
                    frameTransmissionTimes.shift();
                }
                frameTransmissionTimes.push(now);
                
                // Check network quality periodically
                if (now - lastNetworkCheckTime > NETWORK_CHECK_INTERVAL) {
                    updateNetworkQuality();
                    lastNetworkCheckTime = now;
                }
            } else {
                frameTransmissionTimes.push(now);
            }
            
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

                frameTransmissionLatencies = []; // Reset latency stats
                frameTransmissionTimes = [];

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
    
    // Handle network quality update from server
    socket.on('network_quality', (data) => {
        if (data.quality && data.quality !== stableNetworkQuality) {
            const serverQualityIndex = qualityOrder.indexOf(data.quality);
            const clientQualityIndex = qualityOrder.indexOf(stableNetworkQuality);

            if (serverQualityIndex < clientQualityIndex) {
                stableNetworkQuality = data.quality;
                lastQualityChangeTime = performance.now();
                applyQualitySettings(data.quality);
                console.log(`Server forced downgrade to: ${data.quality}`);
            } else {
                console.log(`Ignoring server upgrade recommendation (${data.quality}), awaiting client-side stability.`);
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
        isProcessing = false; // Stop processing
        alert('Disconnected from server. Please refresh the page to reconnect.');
    });
    
    // Handle reset confirmation from server
    socket.on('reset_confirmed', () => {
        console.log('Reset confirmed by server');
        resetStatusIndicators();
    });
    
    // Handle partner video frame
    socket.on('partner_video_frame', (data) => {
        // If we have a partner video element, update it
        const partnerVideo = document.getElementById('partner-video');
        if (partnerVideo && data.image) {
            partnerVideo.src = data.image;
            
            // Update partner video container with orientation class if needed
            const partnerContainer = partnerVideo.parentElement;
            if (partnerContainer) {
                if (data.isPortrait) {
                    partnerContainer.classList.add('portrait-mode');
                } else {
                    partnerContainer.classList.remove('portrait-mode');
                }
            }
        }
    });
}

// Capture and send a frame to the server
function captureAndSendFrame() {
    if (!isProcessing || !webcam.videoWidth) return;
    
    try {
        // Draw the current frame to the canvas
        overlayContext.drawImage(webcam, 0, 0, overlay.width, overlay.height);
        
        // Get the frame data as a data URL
        const frameData = overlay.toDataURL('image/jpeg', 0.7);
        
        // Send the frame to the server
        socket.emit('process_frame', {
            image: frameData,
            code: sessionCode,
            timestamp: performance.now(),
            networkQuality: currentNetworkQuality,
            isPortrait: isPortrait,
            detectionMode: 'normal'
        });
    } catch (error) {
        console.error('Error capturing frame:', error);
    }
}

// Set up audio processing
function setupAudioProcessing(stream) {
    // Create audio context
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    
    // Connect the processor
    source.connect(processor);
    processor.connect(audioContext.destination);
    
    // Process audio data
    processor.onaudioprocess = (e) => {
        if (!isProcessing) return;
        
        // Get audio data
        const inputData = e.inputBuffer.getChannelData(0);
        
        // Convert to 16-bit PCM
        const pcmData = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
            pcmData[i] = Math.max(-1, Math.min(1, inputData[i])) * 0x7FFF;
        }
        
        // Send audio chunk to server
        socket.emit('audio_chunk', {
            audio: arrayBufferToBase64(pcmData.buffer)
        });
    };
}

// Convert ArrayBuffer to Base64
function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return window.btoa(binary);
}

// Reset status indicators
function resetStatusIndicators() {
    actionStatus.innerHTML = '❌';
    wordStatus.innerHTML = '❌';
    blinkStatus.innerHTML = '❌';
}

// Reset verification
function resetVerification() {
    socket.emit('reset', { code: sessionCode });
    resultContainer.classList.add('hidden');
    isProcessing = true;
    removeVideoEffect();
    requestAnimationFrame(captureAndSendFrame);
}

// Update network quality based on latency
function updateNetworkQuality() {
    if (frameTransmissionLatencies.length === 0) return;
    
    // Calculate average latency
    const avgLatency = frameTransmissionLatencies.reduce((a, b) => a + b, 0) / frameTransmissionLatencies.length;
    
    // Determine quality level based on latency
    let newQuality;
    if (avgLatency > 500) {
        newQuality = 'very_low';
    } else if (avgLatency > 300) {
        newQuality = 'low';
    } else if (avgLatency > 150) {
        newQuality = 'medium';
    } else {
        newQuality = 'high';
    }
    
    // Only upgrade quality if it's been stable for a while
    const now = performance.now();
    const timeSinceLastChange = now - lastQualityChangeTime;
    
    if (qualityOrder.indexOf(newQuality) > qualityOrder.indexOf(currentNetworkQuality)) {
        // Upgrading quality requires stability
        if (timeSinceLastChange > QUALITY_STABILITY_THRESHOLD) {
            currentNetworkQuality = newQuality;
            lastQualityChangeTime = now;
            console.log(`Network quality upgraded to: ${newQuality} (Latency: ${avgLatency.toFixed(0)}ms)`);
        }
    } else if (qualityOrder.indexOf(newQuality) < qualityOrder.indexOf(currentNetworkQuality)) {
        // Downgrading quality happens immediately
        currentNetworkQuality = newQuality;
        lastQualityChangeTime = now;
        console.log(`Network quality downgraded to: ${newQuality} (Latency: ${avgLatency.toFixed(0)}ms)`);
    }
    
    // Send network quality to server
    socket.emit('client_network_quality', {
        quality: currentNetworkQuality,
        latency: avgLatency
    });
}

// Apply quality settings
function applyQualitySettings(quality) {
    // Apply quality settings based on level
    switch (quality) {
        case 'very_low':
            // Very low quality settings
            break;
        case 'low':
            // Low quality settings
            break;
        case 'medium':
            // Medium quality settings
            break;
        case 'high':
            // High quality settings
            break;
    }
}

// Apply video effect based on verification result
function applyVideoEffect(effect) {
    const container = document.querySelector('.video-container');
    if (!container) return;
    
    // Remove any existing effects
    removeVideoEffect();
    
    // Apply the new effect
    switch (effect) {
        case 'success':
            container.classList.add('success-overlay');
            break;
        case 'failure':
            container.classList.add('failure-overlay');
            break;
        case 'duress':
            container.classList.add('duress-overlay');
            break;
    }
}

// Remove video effect
function removeVideoEffect() {
    const container = document.querySelector('.video-container');
    if (!container) return;
    
    container.classList.remove('success-overlay', 'failure-overlay', 'duress-overlay');
}

// Create a scaled frame for sending to the server
function createScaledFrame(sourceCanvas, quality, isPortrait) {
    // Create a new canvas for the scaled frame
    const scaledCanvas = document.createElement('canvas');
    const ctx = scaledCanvas.getContext('2d');
    
    // Set dimensions based on quality and orientation
    let width, height;
    if (isPortrait) {
        // In portrait mode, swap width and height to maintain aspect ratio (3:4)
        switch (quality) {
            case 'very_low':
                width = 180; height = 240;
                break;
            case 'low':
                width = 240; height = 320;
                break;
            case 'medium':
                width = 360; height = 480;
                break;
            case 'high':
            default:
                width = 480; height = 640;
                break;
        }
    } else {
        // In landscape mode, use original 4:3 aspect ratio
        switch (quality) {
            case 'very_low':
                width = 240; height = 180;
                break;
            case 'low':
                width = 320; height = 240;
                break;
            case 'medium':
                width = 480; height = 360;
                break;
            case 'high':
            default:
                width = 640; height = 480;
                break;
        }
    }
    
    // Set canvas dimensions
    scaledCanvas.width = width;
    scaledCanvas.height = height;
    
    // Draw the source canvas onto the scaled canvas
    ctx.drawImage(sourceCanvas, 0, 0, width, height);
    
    return scaledCanvas.toDataURL('image/jpeg', 0.7);
}
