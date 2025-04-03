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
    
    // Create network status display element
    const networkStatusContainer = document.createElement('div');
    networkStatusContainer.id = 'network-status-container';
    networkStatusContainer.style.position = 'absolute';
    networkStatusContainer.style.bottom = '10px';
    networkStatusContainer.style.left = '10px';
    networkStatusContainer.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
    networkStatusContainer.style.color = 'white';
    networkStatusContainer.style.padding = '5px 10px';
    networkStatusContainer.style.borderRadius = '5px';
    networkStatusContainer.style.fontSize = '12px';
    networkStatusContainer.style.zIndex = '1000';
    document.body.appendChild(networkStatusContainer);
    
    // Declare variables used throughout the script
    let socket; // Socket.IO connection to the server
    let isProcessing = false; // Flag to control frame capturing and sending
    let stream = null; // Webcam media stream
    let verificationAttempts = 0; // Counter for verification attempts
    const MAX_VERIFICATION_ATTEMPTS = 3; // Maximum allowed attempts before failing
    let isDebugMode = true; // Whether debug logging is enabled (set by server) - CHANGED: default to true for testing
    let showDebugFrame = false; // Whether to show the debug frame (set by server)
    let frameCount = 0; // Counter for frames sent to the server
    
    // Video optimization variables
    let lastFrameTime = 0; // Timestamp of the last frame sent
    const TARGET_FPS = 10; // Target frames per second for normal operation
    const BLINK_DETECTION_FPS = 20; // Higher FPS during blink detection to ensure accuracy
    const ACTION_DETECTION_FPS = 15; // Medium FPS during action detection
    const FRAME_INTERVAL = 100 / TARGET_FPS; // Milliseconds between frames at target FPS
    const BLINK_FRAME_INTERVAL = 100 / BLINK_DETECTION_FPS; // Milliseconds between frames during blink detection
    const ACTION_FRAME_INTERVAL = 100 / ACTION_DETECTION_FPS; // Milliseconds between frames during action detection
    let currentFrameInterval = FRAME_INTERVAL; // Current interval between frames (can change based on detection mode)
    let videoQuality = 0.3; // JPEG quality (0.0 to 1.0) for normal operation
    let blink_detection_active = true; // Flag to indicate if blink detection is currently active
    let action_detection_active = true; // Flag to indicate if action detection is currently active
    let networkQuality = 'high'; // Estimated network quality: 'high', 'medium', or 'low'
    let adaptiveQualityEnabled = true; // Enable adaptive quality based on network conditions
    let lastNetworkCheckTime = 0; // Last time network quality was checked
    const NETWORK_CHECK_INTERVAL = 5000; // Check network quality every 5 seconds
    let frameTransmissionTimes = []; // Array to store frame transmission times for network quality estimation
    let frameTransmissionLatencies = []; // Array to store frame transmission latencies
    
    // Network logging variables
    let lastNetworkLogTime = 0; // Last time network stats were logged
    const NETWORK_LOG_INTERVAL = 2000; // Log network stats every 2 seconds
    let actualFps = 0; // Actual frames per second being achieved
    let lastFpsUpdateTime = 0; // Last time FPS was calculated
    let framesSinceLastFpsUpdate = 0; // Frames sent since last FPS calculation
    
    // Video resolution settings - UPDATED: added very_low and ultra_low settings
    const RESOLUTION_SETTINGS = {
        high: { width: 640, height: 480, quality: 0.3 },
        medium: { width: 480, height: 360, quality: 0.3 },
        low: { width: 320, height: 240, quality: 0.3 },
        very_low: { width: 240, height: 180, quality: 0.3 },
        ultra_low: { width: 160, height: 120, quality: 0.3 }
    };
    let currentResolution = RESOLUTION_SETTINGS.medium; // Start with medium resolution
    
    // Audio processing variables
    let audioContext = null; 
    let scriptProcessor = null; 
    let audioSource = null;
    const bufferSize = 4096;
    let audioSendCounter = 0; // Counter for audio chunks
    const AUDIO_SEND_INTERVAL = 3; // Only send every Nth audio chunk to reduce bandwidth
    
    // Initialize the Socket.IO connection and set up event listeners
    function initSocket() {
        console.log('Initializing socket connection for verification');
        
        // Configure Socket.IO with optimized settings
        socket = io({
            reconnectionAttempts: 5,
            reconnectionDelay: 1000,
            timeout: 10000,
            transports: ['websocket', 'polling']
        });
        
        // When the socket connects to the server
        socket.on('connect', () => {
            console.log('Connected to server for verification');
            socket.emit('join_verification', { 
                code: sessionCode,
                clientInfo: {
                    userAgent: navigator.userAgent,
                    screenWidth: window.innerWidth,
                    screenHeight: window.innerHeight,
                    networkType: navigator.connection ? navigator.connection.effectiveType : 'unknown'
                }
            });
            socket.emit('get_debug_status'); // Request debug settings from the server
        });
        
        // Handle debug status response from the server
        socket.on('debug_status', (data) => {
            isDebugMode = data.debug || true; // Set debug mode based on server config, default to true for testing
            showDebugFrame = data.showDebugFrame; // Set whether to show debug frame

            console.log(`Debug mode: ${isDebugMode}`);
            
            // Adjust UI visibility based on whether debug frame should be shown
            if (showDebugFrame) {
                console.log(`Show debug frame: ${showDebugFrame}`);
                processedFrameContainer.classList.remove('hidden'); // Show the debug frame container
                debugFrame.classList.remove('hidden'); // Show the debug frame element
                videoContainer.classList.remove('single-video'); // Adjust layout for dual video display
            } else {
                processedFrameContainer.classList.add('hidden'); // Hide the debug frame container
                debugFrame.classList.add('hidden'); // Hide the debug frame element
                videoContainer.classList.add('single-video'); // Adjust layout for single video
            }
            
            // Ensure debug frame is not loaded when not needed
            if (!showDebugFrame) {
                debugFrame.src = ''; // Clear the src to prevent loading broken image
            }
            
            isProcessing = true; // Start processing frames
            console.log('Processing started');
            requestAnimationFrame(captureAndSendFrame); // Begin capturing and sending frames
        });
        
        // Handle processed frame data from the server
        socket.on('processed_frame', (data) => {
            // Calculate frame latency for network quality monitoring
            const now = performance.now();
            if (data.timestamp) {
                const latency = now - data.timestamp;
                
                // Keep only the last 10 latency measurements
                if (frameTransmissionLatencies.length >= 10) {
                    frameTransmissionLatencies.shift();
                }
                frameTransmissionLatencies.push(latency);
            }
            
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
                
                // Check if this challenge involves blink detection or action detection
                blink_detection_active = data.challenge.toLowerCase().includes('blink');
                action_detection_active = data.challenge.toLowerCase().includes('turn') || 
                                         data.challenge.toLowerCase().includes('look');
                
                // Adjust frame rate based on detection mode
                if (blink_detection_active) {
                    currentFrameInterval = BLINK_FRAME_INTERVAL;
                    if (isDebugMode) {
                        console.log('Blink detection active - increasing frame rate to 15 FPS');
                    }
                } else if (action_detection_active) {
                    currentFrameInterval = ACTION_FRAME_INTERVAL;
                    if (isDebugMode) {
                        console.log('Action detection active - setting frame rate to 12 FPS');
                    }
                } else {
                    currentFrameInterval = FRAME_INTERVAL;
                    if (isDebugMode) {
                        console.log('Standard mode - setting frame rate to 10 FPS');
                    }
                }
            } else {
                challengeText.textContent = 'Waiting for challenge...'; // Default message if no challenge
                blink_detection_active = false;
                action_detection_active = false;
                currentFrameInterval = FRAME_INTERVAL;
            }
            
            // Update action, word, and blink completion status indicators
            actionStatus.textContent = data.action_completed ? '✅' : '❌'; // Green check or red X
            wordStatus.textContent = data.word_completed ? '✅' : '❌'; // Green check or red X
            
            // Update blink status if element exists
            const blinkStatus = document.getElementById('blink-status');
            if (blinkStatus) {
                blinkStatus.textContent = data.blink_completed ? '✅' : '❌'; // Green check or red X
            }
            
            // Update remaining time display
            if (data.time_remaining !== undefined) {
                timeRemaining.textContent = Math.max(0, Math.ceil(data.time_remaining)) + 's'; // Show time left, min 0
            }
            
            // Handle verification result when it's not pending
            if (data.verification_result !== 'PENDING') {
                isProcessing = false; // Stop capturing new frames
                
                // Set all status indicators to green checkmarks if verification passed
                if (data.verification_result === 'PASS') {
                    actionStatus.textContent = '✅';
                    wordStatus.textContent = '✅';
                    const blinkStatus = document.getElementById('blink-status');
                    if (blinkStatus) {
                        blinkStatus.textContent = '✅';
                    }
                }
                
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
                    // Use a longer delay (3 seconds) to account for the transition animation
                    setTimeout(() => {
                        isProcessing = true; // Resume processing
                        canvas.style.display = 'none'; // Hide the canvas
                        video.play(); // Resume the video
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
            if (data.quality && data.quality !== networkQuality) {
                networkQuality = data.quality;
                console.log(`Server reported network quality: ${networkQuality}`);
                
                // Adjust video quality based on server-reported network quality
                if (adaptiveQualityEnabled) {
                    currentResolution = RESOLUTION_SETTINGS[networkQuality];
                    videoQuality = currentResolution.quality;
                    
                    console.log(`Adjusted video settings based on server feedback: ${currentResolution.width}x${currentResolution.height}, quality: ${videoQuality}`);
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
            
            // Attempt to reconnect after a delay
            setTimeout(() => {
                if (!socket.connected) {
                    console.log('Attempting to reconnect...');
                    socket.connect();
                }
            }, 3000);
        });
        
        // Handle new challenge text from the server
        socket.on('challenge', (data) => {
            if (data && data.text) {
                challengeText.textContent = data.text; // Update challenge text
                
                // Check if this challenge involves blink detection or action detection
                blink_detection_active = data.text.toLowerCase().includes('blink');
                action_detection_active = data.text.toLowerCase().includes('turn') || 
                                         data.text.toLowerCase().includes('look');
                
                // Adjust frame rate based on detection mode
                if (blink_detection_active) {
                    currentFrameInterval = BLINK_FRAME_INTERVAL;
                    console.log('Blink detection active - increasing frame rate to 15 FPS');
                } else if (action_detection_active) {
                    currentFrameInterval = ACTION_FRAME_INTERVAL;
                    console.log('Action detection active - setting frame rate to 12 FPS');
                } else {
                    currentFrameInterval = FRAME_INTERVAL;
                    console.log('Standard mode - setting frame rate to 10 FPS');
                }
                
                // Send network quality information to server
                socket.emit('client_network_quality', { 
                    quality: networkQuality,
                    latency: calculateAverageLatency()
                });
            }
        });
    }
    
    // Calculate average latency from stored measurements
    function calculateAverageLatency() {
        if (frameTransmissionLatencies.length === 0) return 0;
        
        const sum = frameTransmissionLatencies.reduce((a, b) => a + b, 0);
        return Math.round(sum / frameTransmissionLatencies.length);
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
    
    // Update network quality based on frame transmission times and latencies
    function updateNetworkQuality() {
        if (frameTransmissionTimes.length < 2) return;
        
        // Calculate average transmission time
        let totalTime = 0;
        for (let i = 1; i < frameTransmissionTimes.length; i++) {
            totalTime += frameTransmissionTimes[i] - frameTransmissionTimes[i-1];
        }
        const avgTime = totalTime / (frameTransmissionTimes.length - 1);
        
        // Calculate average latency if available
        const avgLatency = calculateAverageLatency();
        
        // Calculate estimated bandwidth (very rough approximation)
        const avgFrameSize = currentResolution.width * currentResolution.height * 3 * videoQuality; // Rough estimate of frame size in bytes
        const estimatedBandwidth = avgFrameSize / (avgTime / 1000); // Bytes per second
        const estimatedKbps = Math.round(estimatedBandwidth * 8 / 1000); // Convert to Kbps
        
        // Determine network quality based on average transmission time and latency
        // UPDATED: More granular network quality levels with very_low and ultra_low
        let newQuality;
        if (avgTime < 100 && avgLatency < 150) {
            newQuality = 'high';
        } else if (avgTime < 200 && avgLatency < 250) {
            newQuality = 'medium';
        } else if (avgTime < 300 && avgLatency < 350) {
            newQuality = 'low';
        } else if (avgTime < 500 && avgLatency < 500) {
            newQuality = 'very_low';
        } else {
            newQuality = 'ultra_low';
        }
        
        // Always log network stats periodically, regardless of quality changes
        const now = performance.now();
        if (now - lastNetworkLogTime > NETWORK_LOG_INTERVAL) {
            // Calculate actual FPS
            if (now - lastFpsUpdateTime > 1000) { // Update FPS once per second
                actualFps = Math.round((framesSinceLastFpsUpdate * 1000) / (now - lastFpsUpdateTime));
                lastFpsUpdateTime = now;
                framesSinceLastFpsUpdate = 0;
            }
            
            // Update network status display
            updateNetworkStatusDisplay(newQuality, avgTime, avgLatency, estimatedKbps, actualFps);
            
            console.log(`Network stats: quality=${newQuality}, avg_time=${avgTime.toFixed(2)}ms, latency=${avgLatency.toFixed(2)}ms, est_bandwidth=${estimatedKbps}Kbps, actual_fps=${actualFps}`);
            lastNetworkLogTime = now;
        }
        
        // Update quality if changed
        if (newQuality !== networkQuality) {
            networkQuality = newQuality;
            console.log(`Network quality updated to: ${networkQuality} (avg time: ${avgTime.toFixed(2)}ms, avg latency: ${avgLatency.toFixed(2)}ms)`);
            
            // Adjust video quality based on network quality if adaptive quality is enabled
            if (adaptiveQualityEnabled) {
                currentResolution = RESOLUTION_SETTINGS[networkQuality];
                videoQuality = currentResolution.quality;
                
                console.log(`Adjusted video settings: ${currentResolution.width}x${currentResolution.height}, quality: ${videoQuality}`);
                
                // Inform server about client-detected network quality
                if (socket && socket.connected) {
                    socket.emit('client_network_quality', { 
                        quality: networkQuality,
                        latency: avgLatency
                    });
                }
            }
        }
    }
    
    // Update the network status display element
    function updateNetworkStatusDisplay(quality, avgTime, avgLatency, estimatedKbps, actualFps) {
        // Set color based on quality
        let qualityColor;
        switch(quality) {
            case 'high': qualityColor = '#4cd137'; break; // Green
            case 'medium': qualityColor = '#fbc531'; break; // Yellow
            case 'low': qualityColor = '#e84118'; break; // Red
            case 'very_low': qualityColor = '#c23616'; break; // Dark red
            case 'ultra_low': qualityColor = '#8c0000'; break; // Very dark red
            default: qualityColor = '#7f8fa6'; // Gray
        }
        
        // Update the display
        networkStatusContainer.innerHTML = `
            <div style="font-weight: bold; color: ${qualityColor};">Network: ${quality.toUpperCase()}</div>
            <div>Latency: ${avgLatency.toFixed(0)}ms</div>
            <div>Bandwidth: ~${estimatedKbps}Kbps</div>
            <div>FPS: ${actualFps}</div>
            <div>Resolution: ${currentResolution.width}x${currentResolution.height}</div>
            <div>Quality: ${Math.round(videoQuality * 100)}%</div>
        `;
    }
    
    // Create a downscaled version of the video frame
    function createScaledFrame(sourceCanvas, targetWidth, targetHeight) {
        const scaledCanvas = document.createElement('canvas');
        scaledCanvas.width = targetWidth;
        scaledCanvas.height = targetHeight;
        const scaledCtx = scaledCanvas.getContext('2d');
        
        // Draw the source canvas onto the scaled canvas
        scaledCtx.drawImage(sourceCanvas, 0, 0, sourceCanvas.width, sourceCanvas.height, 
                           0, 0, targetWidth, targetHeight);
        
        return scaledCanvas;
    }
    
    // Capture a frame from the webcam and send it to the server
    function captureAndSendFrame() {
        if (!isProcessing) {
            console.log('Processing stopped, not capturing frame');
            return; // Exit if not processing
        }
        
        const now = performance.now();
        const timeSinceLastFrame = now - lastFrameTime;
        
        // Check if enough time has passed since the last frame based on current frame interval
        if (timeSinceLastFrame < currentFrameInterval) {
            // Not enough time has passed, schedule next check
            requestAnimationFrame(captureAndSendFrame);
            return;
        }
        
        // Update last frame time
        lastFrameTime = now;
        
        try {
            // Create an offscreen canvas to capture the video frame
            const offscreenCanvas = document.createElement('canvas');
            offscreenCanvas.width = video.videoWidth;
            offscreenCanvas.height = video.videoHeight;
            const offscreenCtx = offscreenCanvas.getContext('2d');
            offscreenCtx.drawImage(video, 0, 0, offscreenCanvas.width, offscreenCanvas.height); // Draw video frame
            
            // Create a scaled version of the frame based on current resolution settings
            const scaledCanvas = createScaledFrame(
                offscreenCanvas, 
                currentResolution.width, 
                currentResolution.height
            );
            
            // Convert to JPEG with quality based on current settings
            const imageData = scaledCanvas.toDataURL('image/jpeg', videoQuality);
            
            // Log frame sending every 30 frames in debug mode
            if (isDebugMode && frameCount % 30 === 0) {
                console.log(`Sending frame #${frameCount} (${currentResolution.width}x${currentResolution.height}, quality: ${videoQuality})`);
            }
            
            // Send the frame to the server with the session code and timestamp
            socket.emit('process_frame', {
                image: imageData,
                code: sessionCode,
                timestamp: now,
                networkQuality: networkQuality,
                detectionMode: blink_detection_active ? 'blink' : 
                              action_detection_active ? 'action' : 'normal'
            });
            frameCount++; // Increment frame counter
            framesSinceLastFpsUpdate++; // Increment frames for FPS calculation
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
                
                // --- Start Audio Processing ---
                if (stream.getAudioTracks().length > 0) {
                    audioContext = new (window.AudioContext || window.webkitAudioContext)();
                    // Ensure the sample rate matches your PocketSphinx config (e.g., 16000)
                    if (audioContext.sampleRate !== 16000) { 
                        console.warn(`AudioContext sample rate (${audioContext.sampleRate}) doesn't match target (16000). Resampling might be needed or PocketSphinx config adjusted.`);
                    }
                    
                    // log the audio sample rate
                    if (isDebugMode) {
                        console.log(`Audio sample rate: ${audioContext.sampleRate}`); 
                    }
                    audioSource = audioContext.createMediaStreamSource(stream);
                    scriptProcessor = audioContext.createScriptProcessor(bufferSize, 1, 1); // bufferSize, inputChannels=1, outputChannels=1

                    scriptProcessor.onaudioprocess = (audioProcessingEvent) => {
                        if (!isProcessing) return; // Only process if verification is active

                        // Increment audio send counter
                        audioSendCounter = (audioSendCounter + 1) % AUDIO_SEND_INTERVAL;
                        
                        // Only send every Nth audio chunk to reduce bandwidth
                        if (audioSendCounter !== 0) return;

                        const inputBuffer = audioProcessingEvent.inputBuffer;
                        const inputData = inputBuffer.getChannelData(0); // Get audio data from the first channel

                        // Convert Float32Array to Int16Array (PCM format expected by PocketSphinx)
                        const output = new Int16Array(inputData.length);
                        for (let i = 0; i < inputData.length; i++) {
                            output[i] = Math.max(-1, Math.min(1, inputData[i])) * 32767;
                        }
                        
                        // Convert Int16Array buffer to Base64 string to send via Socket.IO
                        const audioBase64 = btoa(String.fromCharCode.apply(null, new Uint8Array(output.buffer)));

                        // Send the audio chunk to the server
                        if (socket && socket.connected) {
                            socket.emit('audio_chunk', { 
                                audio: audioBase64,
                                timestamp: performance.now()
                            });
                        }
                    };

                    audioSource.connect(scriptProcessor);
                    scriptProcessor.connect(audioContext.destination); // Connect to output (necessary even if not playing back)
                    console.log("Audio processing setup complete.");
                } else {
                    console.warn("No audio track found in the stream.");
                }
                // --- End Audio Processing ---

                requestAnimationFrame(captureAndSendFrame); // Start capturing frames
            };
        } catch (err) {
            console.error('Error accessing webcam:', err); // Log webcam access errors
            alert('Error accessing webcam: ' + err.message); // Alert the user
        }
    }

    // Add cleanup for audio resources
    window.addEventListener('beforeunload', () => {
        if (socket && socket.connected) {
            socket.disconnect(); 
        }
        if (stream) {
            stream.getTracks().forEach(track => track.stop()); 
        }
        // --- Stop Audio Processing ---
        if (scriptProcessor) {
            scriptProcessor.disconnect();
        }
        if (audioSource) {
            audioSource.disconnect();
        }
        if (audioContext) {
            audioContext.close();
        }
        // --- End Stop Audio Processing ---
    });
    
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
