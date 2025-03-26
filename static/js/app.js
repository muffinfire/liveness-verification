document.addEventListener('DOMContentLoaded', () => {
    const video = document.getElementById('webcam');
    const canvas = document.getElementById('overlay');
    const ctx = canvas.getContext('2d');
    const debugFrame = document.getElementById('debug-frame');
    const challengeText = document.getElementById('challenge-text');
    const actionStatus = document.getElementById('action-status');
    const wordStatus = document.getElementById('word-status');
    const timeRemaining = document.getElementById('time-remaining');
    const resultContainer = document.getElementById('result-container');
    const resultText = document.getElementById('result-text');
    const resetButton = document.getElementById('reset-button');
    const videoContainer = document.querySelector('.video-container');
    const sessionCode = document.getElementById('session-code').textContent;
    
    let socket;
    let isProcessing = false;
    let stream = null;
    let verificationAttempts = 0;
    const MAX_VERIFICATION_ATTEMPTS = 3;
    let isDebugMode = true; // Set to true to show debug output
    let showDebugFrame = true; // Set to true to show debug frame
    let frameCount = 0;
    
    // Initialize Socket.IO connection
    function initSocket() {
        console.log('Initializing socket connection for verification');
        socket = io();
        
        socket.on('connect', () => {
            if (isDebugMode) console.log('Connected to server for verification');
            socket.emit('join_verification', { code: sessionCode });
            socket.emit('get_debug_status');
            if (isDebugMode) console.log('Sent join_verification and get_debug_status events');
        });
        
        socket.on('debug_status', (data) => {
            isDebugMode = data.debug;
            showDebugFrame = data.showDebugFrame;
            if (isDebugMode) {
                console.log(`Debug mode: ${isDebugMode}, Show debug frame: ${showDebugFrame}`);
            }
            
            isProcessing = true;  // Start processing frames after receiving debug status
            
            // Show/hide debug frame based on settings
            debugFrame.style.display = showDebugFrame ? 'block' : 'none';
        });
        
        socket.on('session_joined', (data) => {
            console.log('Verification session joined:', data);
            isProcessing = true;
        });
        
        socket.on('processed_frame', (data) => {
            if (isDebugMode && frameCount % 30 === 0) {
                console.log('Received processed frame:', {
                    hasImage: !!data.image,
                    hasDebugImage: !!data.debug_image,
                    action_completed: data.action_completed,
                    word_completed: data.word_completed,
                    time_remaining: data.time_remaining
                });
            }
            
            // Send all data to the debug frame instead
            if (data.image && debugFrame) {
                debugFrame.src = data.debug_image || data.image;
                debugFrame.style.display = showDebugFrame ? 'block' : 'none';
            }
            
            // Update challenge text and status
            if (data.challenge) {
                challengeText.textContent = data.challenge;
                challengeText.classList.remove('hidden');
            } else {
                challengeText.textContent = 'Waiting for challenge...';
            }
            
            // Update action status
            actionStatus.textContent = data.action_completed ? '✅' : '❌';
            actionStatus.className = data.action_completed ? 'status-complete' : 'status-incomplete';
            
            // Update word status
            wordStatus.textContent = data.word_completed ? '✅' : '❌';
            wordStatus.className = data.word_completed ? 'status-complete' : 'status-incomplete';
            
            // Update time remaining
            if (data.time_remaining !== undefined) {
                timeRemaining.textContent = Math.max(0, Math.ceil(data.time_remaining)) + 's';
            }
            
            // Handle verification result
            if (data.verification_result !== 'PENDING') {
                isProcessing = false;
                
                if (data.verification_result === 'PASS') {
                    resultText.textContent = 'Verification Successful!';
                    resultText.className = 'result-text success';
                    applyVideoEffect('success');
                    
                    // Redirect to main page after 3 seconds
                    setTimeout(() => {
                        window.location.href = '/';
                    }, 3000);
                } else {
                    resultText.textContent = 'Verification Failed!';
                    resultText.className = 'result-text failure';
                    applyVideoEffect('failure');
                    
                    verificationAttempts++;
                    if (verificationAttempts >= MAX_VERIFICATION_ATTEMPTS) {
                        resultText.textContent = 'Maximum attempts reached. Verification failed.';
                        setTimeout(() => {
                            window.location.href = '/';
                        }, 3000);
                    } else {
                        // Allow another attempt after 3 seconds
                        setTimeout(() => {
                            resultContainer.classList.add('hidden');
                            isProcessing = true;
                            removeVideoEffect();
                        }, 3000);
                    }
                }
                
                resultContainer.classList.remove('hidden');
            }
            
            // Continue processing frames if not paused
            if (isProcessing) {
                requestAnimationFrame(captureAndSendFrame);
            }
            if (isDebugMode) {
                console.log('Debug frame status:', {
                    hasDebugImage: !!data.debug_image,
                    debugFrameElement: !!debugFrame,
                    debugFrameClass: debugFrame.className,
                    showDebugFrame: showDebugFrame
                });
            }
            
            if (isDebugMode) {
                console.log('Processed frame response:', {
                    hasImage: !!data.image,
                    hasDebugImage: !!data.debug_image,
                    challenge: data.challenge
                });
                
                // Let's examine the actual URLs being set
                if (data.image) {
                    console.log('Image URL preview:', data.image.substring(0, 50) + '...');
                }
                if (data.debug_image) {
                    console.log('Debug image URL preview:', data.debug_image.substring(0, 50) + '...');
                }
            }
            
            // Add this to the processed_frame handler, right after the time remaining update
            if (data.time_remaining <= 0 && data.verification_result === 'PENDING') {
                // Time expired but no conclusive result yet - force reset
                if (isDebugMode) console.log('Challenge timed out, resetting');
                socket.emit('reset', { code: sessionCode });
                verificationAttempts++;
                
                if (verificationAttempts >= MAX_VERIFICATION_ATTEMPTS) {
                    resultText.textContent = 'Maximum attempts reached. Verification failed.';
                    resultText.className = 'result-text failure';
                    resultContainer.classList.remove('hidden');
                    isProcessing = false;
                } else {
                    // Tell user what happened
                    challengeText.textContent = `Attempt ${verificationAttempts+1} of ${MAX_VERIFICATION_ATTEMPTS}...`;
                    setTimeout(() => {
                        challengeText.textContent = 'Waiting for new challenge...';
                    }, 2000);
                }
            }
        });
        
        socket.on('error', (data) => {
            console.error('Server error:', data.message);
            alert('Server error: ' + data.message);
        });
        
        socket.on('max_attempts_reached', () => {
            isProcessing = false;
            resultText.textContent = 'Maximum verification attempts reached.';
            resultContainer.classList.remove('hidden');
            applyFailureEffect();
        });
        
        socket.on('disconnect', () => {
            console.log('Disconnected from server');
            isProcessing = false;
        });
        
        socket.on('join_success', (data) => {
            if (isDebugMode) {
                console.log('Successfully joined verification session');
            }
            isProcessing = true;  // Set processing to true after successful join
        });
        
        socket.on('challenge', (data) => {
            if (isDebugMode) {
                console.log('Received challenge:', data);
            }
            
            // Update the challenge text in the UI
            if (data && data.text) {
                challengeText.textContent = data.text;
            }
        });
        
        socket.onAny((event, ...args) => {
            if (isDebugMode) {
                console.log(`Received socket event: ${event}`, args);
            }
            
            // Force processing to start when any event is received after connection
            if (event !== 'connect' && !isProcessing) {
                console.log('Starting frame processing');
                isProcessing = true;
                
                // Add this to ensure the frame capture interval is active
                if (isDebugMode) console.log('Making sure frame capture interval is active');
                
                // This should restart the frame interval if it's not already running
                startFrameCapture();
            }
        });
        
        // Add this event monitoring for processed_frame - don't modify existing code
        socket.onAny((event) => {
            // Only monitor for the processed_frame event to avoid console flooding
            if (event === 'processed_frame' && isDebugMode) {
                console.log('Detected processed_frame event!');
            }
        });
        
        // Add this at the end of your initialize function or after socket = io()
        socket.on('connect', () => {
            if (isDebugMode) {
                console.log('Socket connection state:', {
                    id: socket.id,
                    connected: socket.connected,
                    disconnected: socket.disconnected
                });
            }
        });
    }
    
    // Apply success effect to video
    function applySuccessEffect() {
        videoContainer.classList.add('success-overlay');
        resultText.textContent = 'Verification successful!';
        resultText.className = 'result-text success';
        resultContainer.classList.remove('hidden');
    }
    
    // Apply failure effect to video
    function applyFailureEffect() {
        videoContainer.classList.add('failure-overlay');
        resultText.textContent = 'Verification failed. Please try again.';
        resultText.className = 'result-text failure';
        resultContainer.classList.remove('hidden');
    }
    
    // Remove video effects
    function removeVideoEffect() {
        videoContainer.classList.remove('success-overlay', 'failure-overlay');
        resultContainer.classList.add('hidden');
    }
    
    // Handle verification result
    function handleVerificationResult(result) {
        if (result === 'PASS') {
            resultText.textContent = 'Verification successful!';
            resultText.className = 'result-text success';
        } else if (result === 'FAIL') {
            resultText.textContent = 'Verification failed.';
            resultText.className = 'result-text failure';
        }
    }
    
    // Capture and send frame to server
    function captureAndSendFrame() {
        if (!isProcessing) {
            if (isDebugMode) console.log('Not processing frames - isProcessing is false');
            return;
        }
        
        if (isDebugMode) console.log('Processing frames - capturing and sending frame');
        
        try {
            // Draw video frame to canvas
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            
            // Get image data from canvas
            const imageData = canvas.toDataURL('image/jpeg', 0.8);
            
            if (isDebugMode) console.log(`Sending frame ${frameCount} to server`);
            
            // Send to server
            socket.emit('process_frame', {
                image: imageData,
                code: sessionCode
            });
            
            frameCount++;
            if (isDebugMode && frameCount % 30 === 0) {
                console.log(`Sent ${frameCount} frames`);
            }
        } catch (err) {
            console.error('Error capturing frame:', err);
        }
    }
    
    // Initialize webcam
    async function initWebcam() {
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    width: { ideal: 640 },
                    height: { ideal: 480 },
                    facingMode: 'user'
                },
                audio: true
            });
            video.srcObject = stream;
            console.log('Webcam access granted, waiting for video to load');
            
            video.onloadedmetadata = () => {
                console.log('Video loaded, starting frame capture');
                video.play().catch(err => console.error('Error playing video:', err));
                captureAndSendFrame();
            };
        } catch (err) {
            console.error('Error accessing webcam:', err);
            alert('Error accessing webcam: ' + err.message);
        }
    }
    
    // Handle reset button click
    resetButton.addEventListener('click', () => {
        if (socket && socket.connected) {
            console.log('Sending reset request');
            socket.emit('reset', { code: sessionCode });
            resultContainer.classList.add('hidden');
            isProcessing = true;
            removeVideoEffect();
        }
    });
    
    // Initialize everything
    function init() {
        console.log('Initializing verification page');
        initSocket();
        initWebcam();
    }
    
    // Cleanup on page unload
    window.addEventListener('beforeunload', () => {
        if (socket && socket.connected) {
            socket.disconnect();
        }
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
        }
    });
    
    // Add this helper function that should already exist in your code
    function startFrameCapture() {
        if (isDebugMode) console.log('Starting frame capture interval');
        // Call captureAndSendFrame immediately once
        captureAndSendFrame();
        
        // Then set up interval - use a reasonably fast interval (100ms = 10fps)
        setInterval(captureAndSendFrame, 100);
    }
    
    init();
});