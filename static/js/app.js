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
    const processedFrameContainer = document.getElementById('processed-frame-container');
    const sessionCode = document.getElementById('session-code').textContent;
    
    let socket;
    let isProcessing = false;
    let stream = null;
    let verificationAttempts = 0;
    const MAX_VERIFICATION_ATTEMPTS = 3;
    let isDebugMode = true;
    let showDebugFrame = true;
    let frameCount = 0;
    
    video.muted = true;
    video.volume = 0;

    function initSocket() {
        console.log('Initializing socket connection for verification');
        socket = io();
        
        socket.on('connect', () => {
            console.log('Connected to server for verification');
            socket.emit('join_verification', { code: sessionCode });
            socket.emit('get_debug_status');
        });
        
        socket.on('debug_status', (data) => {
            isDebugMode = data.debug;
            showDebugFrame = data.showDebugFrame;
            console.log(`Debug mode: ${isDebugMode}, Show debug frame: ${showDebugFrame}`);
            
            // Set visibility based on server config
            if (showDebugFrame) {
                processedFrameContainer.classList.remove('hidden');
                debugFrame.classList.remove('hidden');
                videoContainer.classList.remove('single-video');
            } else {
                processedFrameContainer.classList.add('hidden');
                debugFrame.classList.add('hidden');
                videoContainer.classList.add('single-video');
            }
            
            isProcessing = true;
            console.log('Processing started after debug status received');
            requestAnimationFrame(captureAndSendFrame);
        });
        
        socket.on('processed_frame', (data) => {
            if (isDebugMode && frameCount % 30 === 0) {
                console.log('Received processed_frame:', {
                    hasImage: !!data.image,
                    hasDebugImage: !!data.debug_image,
                    challenge: data.challenge,
                    action: data.action_completed,
                    word: data.word_completed,
                    time: data.time_remaining,
                    result: data.verification_result,
                    duress: data.duress_detected
                });
            }
            
            // Handle debug frame visibility
            if (showDebugFrame && data.debug_image) {
                debugFrame.src = data.debug_image;
                processedFrameContainer.classList.add('visible');
                videoContainer.classList.add('double-video');
            } else if (data.image) {
                debugFrame.src = data.image; // Fallback for non-debug mode
                if (!showDebugFrame) {
                    processedFrameContainer.classList.remove('visible');
                    videoContainer.classList.remove('double-video');
                }
            }
        
            if (data.challenge) {
                challengeText.textContent = data.challenge;
            } else {
                challengeText.textContent = 'Waiting for challenge...';
            }
            
            actionStatus.textContent = data.action_completed ? '✅' : '❌';
            wordStatus.textContent = data.word_completed ? '✅' : '❌';
            
            if (data.time_remaining !== undefined) {
                timeRemaining.textContent = Math.max(0, Math.ceil(data.time_remaining)) + 's';
            }
            
            if (data.verification_result !== 'PENDING') {
                isProcessing = false; // Stop processing new frames
                
                // Freeze the video by pausing and capturing the last frame
                video.pause();
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                canvas.style.display = 'block'; // Show canvas over video
                
                // Overlay result text
                let resultMessage, textColor;
                if (data.duress_detected) {
                    resultMessage = 'Duress Detected!';
                    textColor = '#ff0000';
                    applyVideoEffect('duress');
                } else if (data.verification_result === 'PASS') {
                    resultMessage = 'Verification Successful!';
                    textColor = '#4cd137';
                    applyVideoEffect('success');
                } else {
                    resultMessage = 'Verification Failed!';
                    textColor = '#e8603e';
                    applyVideoEffect('failure');
                }
                
                ctx.fillStyle = 'rgba(0, 0, 0, 0.7)'; // Semi-transparent background
                ctx.fillRect(0, canvas.height / 2 - 40, canvas.width, 80);
                ctx.fillStyle = textColor;
                ctx.font = 'bold 30px Arial';
                ctx.textAlign = 'center';
                ctx.fillText(resultMessage, canvas.width / 2, canvas.height / 2 + 10);
                
                resultText.textContent = resultMessage;
                resultText.className = `result-text ${data.duress_detected ? 'duress' : data.verification_result === 'PASS' ? 'success' : 'failure'}`;
                resultContainer.classList.remove('hidden');
                
                verificationAttempts++;
                console.log(`Attempt ${verificationAttempts} of ${MAX_VERIFICATION_ATTEMPTS}`);
                
                if (data.verification_result === 'PASS' || data.duress_detected || verificationAttempts >= MAX_VERIFICATION_ATTEMPTS) {
                    setTimeout(() => window.location.href = '/', 5000);
                } else {
                    setTimeout(() => {
                        isProcessing = true;
                        canvas.style.display = 'none';
                        video.play();
                        removeVideoEffect();
                        requestAnimationFrame(captureAndSendFrame);
                    }, 3000);
                }
            } else if (isProcessing) {
                requestAnimationFrame(captureAndSendFrame);
            }
            
            if (data.time_remaining <= 0 && data.verification_result === 'PENDING') {
                socket.emit('reset', { code: sessionCode });
                verificationAttempts++;
                
                if (verificationAttempts >= MAX_VERIFICATION_ATTEMPTS) {
                    resultText.textContent = 'Maximum attempts reached. Verification failed.';
                    resultText.className = 'result-text failure';
                    resultContainer.classList.remove('hidden');
                    isProcessing = false;
                    applyVideoEffect('failure');
                    setTimeout(() => window.location.href = '/', 5000);
                } else {
                    challengeText.textContent = `Attempt ${verificationAttempts + 1} of ${MAX_VERIFICATION_ATTEMPTS}...`;
                    setTimeout(() => {
                        challengeText.textContent = 'Waiting for new challenge...';
                        isProcessing = true;
                        requestAnimationFrame(captureAndSendFrame);
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
            applyVideoEffect('failure');
            setTimeout(() => window.location.href = '/', 5000);
        });
        
        socket.on('disconnect', () => {
            console.log('Disconnected from server');
            isProcessing = false;
        });
        
        socket.on('challenge', (data) => {
            if (data && data.text) {
                challengeText.textContent = data.text;
            }
        });
    }
    
    function applyVideoEffect(effect) {
        if (effect === 'success') {
            videoContainer.classList.add('success-overlay');
        } else if (effect === 'failure') {
            videoContainer.classList.add('failure-overlay');
        } else if (effect === 'duress') {
            videoContainer.classList.add('duress-overlay');
        }
    }
    
    function removeVideoEffect() {
        videoContainer.classList.remove('success-overlay', 'failure-overlay', 'duress-overlay');
    }
    
    function captureAndSendFrame() {
        if (!isProcessing) {
            console.log('Processing stopped, not capturing frame');
            return;
        }
        
        try {
            const offscreenCanvas = document.createElement('canvas');
            offscreenCanvas.width = video.videoWidth;
            offscreenCanvas.height = video.videoHeight;
            const offscreenCtx = offscreenCanvas.getContext('2d');
            offscreenCtx.drawImage(video, 0, 0, offscreenCanvas.width, offscreenCanvas.height);
            const imageData = offscreenCanvas.toDataURL('image/jpeg', 0.8);
            
            if (isDebugMode && frameCount % 30 === 0) {
                console.log(`Sending frame #${frameCount}`);
            }
            
            socket.emit('process_frame', {
                image: imageData,
                code: sessionCode
            });
            frameCount++;
        } catch (err) {
            console.error('Error capturing frame:', err);
        }
    }
    
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
            video.onloadedmetadata = () => {
                video.play().catch(err => console.error('Error playing video:', err));
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                requestAnimationFrame(captureAndSendFrame);
            };
        } catch (err) {
            console.error('Error accessing webcam:', err);
            alert('Error accessing webcam: ' + err.message);
        }
    }
    
    resetButton.addEventListener('click', () => {
        if (socket && socket.connected) {
            socket.emit('reset', { code: sessionCode });
            isProcessing = true;
            removeVideoEffect();
            requestAnimationFrame(captureAndSendFrame);
        }
    });
    
    function init() {
        initSocket();
        initWebcam();
    }
    
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