document.addEventListener('DOMContentLoaded', () => {
    const video = document.getElementById('webcam');
    const canvas = document.getElementById('overlay');
    const ctx = canvas.getContext('2d');
    const processedFrame = document.getElementById('processed-frame');
    const debugFrame = document.getElementById('debug-frame');
    const processedFrameContainer = document.getElementById('processed-frame-container');
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
    let isDebugMode = false; // Default to true, updated by server
    
    // Initialize Socket.IO connection
    function initSocket() {
        console.log('Initializing socket connection for verification');
        socket = io();
        
        socket.on('connect', () => {
            console.log('Connected to server for verification');
            socket.emit('join_verification', { code: sessionCode });
            socket.emit('get_debug_status');
            console.log('Sent join_verification and get_debug_status events');
        });
        
        socket.on('debug_status', (data) => {
            console.log('Received debug status:', data.debug);
            isDebugMode = data.debug;
            
            if (!isDebugMode) {
                processedFrameContainer.classList.add('hidden');
                videoContainer.classList.add('single-video');
            } else {
                processedFrameContainer.classList.remove('hidden');
                videoContainer.classList.remove('single-video');
                console.log('Debug mode enabled, showing processed frame container');
            }
        });
        
        socket.on('processed_frame', (data) => {
            console.log('Received processed_frame event with data:', 
                        {hasImage: !!data.image, hasDebugImage: !!data.debug_image, 
                         timeRemaining: data.time_remaining});
            handleProcessedFrame(data);
        });
        
        socket.on('challenge', (data) => {
            console.log('Received challenge:', data.text);
            challengeText.textContent = data.text || 'Waiting for challenge...';
        });
        
        socket.on('verification_started', (data) => {
            console.log('Verification started');
            isProcessing = true;
        });
        
        socket.on('error', (data) => {
            console.error('Server error:', data.message);
            alert('Error: ' + data.message);
        });
        
        socket.on('session_error', (data) => {
            console.error('Session error:', data.message);
            alert(data.message);
            window.location.href = '/';
        });
    }
    
    // Handle server-processed frame data and update UI
    function handleProcessedFrame(data) {
        // Only update frames when we have new data
        if (data.image) {
            processedFrame.src = data.image;
            processedFrame.classList.remove('hidden');
        }
        
        // Only update debug frame if in debug mode and we have debug data
        if (isDebugMode && debugFrame && data.debug_image) {
            debugFrame.src = data.debug_image;
            debugFrame.classList.remove('hidden');
        } else if (!isDebugMode && debugFrame) {
            debugFrame.classList.add('hidden');
        }
        
        // Update timer only when time_remaining is provided
        if (data.time_remaining !== undefined) {
            timeRemaining.textContent = `${Math.round(data.time_remaining)}s`;
        }
        
        if (data.challenge) {
            challengeText.textContent = data.challenge;
        }
        actionStatus.textContent = data.action_completed ? '✅' : '❌';
        wordStatus.textContent = data.word_completed ? '✅' : '❌';
        
        if (data.exit_flag) {
            isProcessing = false;
            verificationAttempts++;
            
            resultContainer.classList.remove('hidden');
            if (data.verification_result === 'PASS') {
                resultText.textContent = 'Verification Successful';
                resultText.className = 'result-text success';
            } else {
                resultText.textContent = verificationAttempts >= MAX_VERIFICATION_ATTEMPTS 
                  ? 'Verification Failed'
                  : 'Verification Failed - Try Again';
                resultText.className = 'result-text failure';
                
                if (verificationAttempts >= MAX_VERIFICATION_ATTEMPTS) {
                    resetButton.classList.add('hidden');
                }
            }
        }
    }
    
    // Capture frames from webcam and send to server - reduce frequency for better performance
    let frameCount = 0;
    function captureAndSendFrame() {
        frameCount++;
        
        // Only send every 2nd or 3rd frame to reduce load
        if (socket && socket.connected && stream && frameCount % 3 === 0) {
            try {
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                
                const imgData = canvas.toDataURL('image/jpeg', 0.6); // Lower quality for better performance
                socket.emit('process_frame', {
                    image: imgData,
                    code: sessionCode
                });
            } catch (err) {
                console.error('Error capturing or sending frame:', err);
            }
        }
        
        requestAnimationFrame(captureAndSendFrame);
    }
    
    // Initialize webcam access
    async function initWebcam() {
        try {
            console.log('Requesting webcam access...');
            stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    width: { ideal: 640 },
                    height: { ideal: 480 },
                    facingMode: 'user'
                },
                audio: false
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
            isProcessing = false;
        }
    });
    
    // Make sure we're properly initializing the UI elements
    function initUI() {
        console.log('Initializing UI elements');
        
        // Make sure we only have the correct video elements
        if (processedFrameContainer) {
            // Remove any extra video elements that might have been created
            while (processedFrameContainer.children.length > 1) {
                processedFrameContainer.removeChild(processedFrameContainer.lastChild);
            }
            
            // Make sure we have the debug frame
            if (!debugFrame && isDebugMode) {
                debugFrame = document.createElement('img');
                debugFrame.classList.add('debug-frame');
                processedFrameContainer.appendChild(debugFrame);
            }
        }
        
        // Initially hide debug frame if not in debug mode
        if (!isDebugMode && debugFrame) {
            debugFrame.classList.add('hidden');
        }
    }
    
    // Initialize everything
    function init() {
        console.log('Initializing verification page');
        initUI();
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
    
    init();
});