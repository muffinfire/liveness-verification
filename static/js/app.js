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
            debugFrame.style.display = showDebugFrame ? 'block' : 'none';
            isProcessing = true;
            console.log('Processing started after debug status received');
            // Start capturing frames immediately
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
                    result: data.verification_result
                });
            }
            
            if (data.debug_image) {
                console.log('Setting debug frame src to debug_image');
                debugFrame.src = data.debug_image;
                debugFrame.classList.remove('hidden');
                debugFrame.style.display = showDebugFrame ? 'block' : 'none';
            } else if (data.image) {
                console.log('Setting debug frame src to image (fallback)');
                debugFrame.src = data.image;
                debugFrame.classList.remove('hidden');
                debugFrame.style.display = showDebugFrame ? 'block' : 'none';
            } else {
                console.log('No image or debug_image received');
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
                isProcessing = false;
                console.log(`Verification result: ${data.verification_result}`);
                if (data.verification_result === 'PASS') {
                    resultText.textContent = 'Verification Successful!';
                    resultText.className = 'result-text success';
                    applyVideoEffect('success');
                    setTimeout(() => window.location.href = '/', 3000);
                } else {
                    resultText.textContent = 'Verification Failed!';
                    resultText.className = 'result-text failure';
                    applyVideoEffect('failure');
                    
                    verificationAttempts++;
                    console.log(`Attempt ${verificationAttempts} of ${MAX_VERIFICATION_ATTEMPTS}`);
                    if (verificationAttempts >= MAX_VERIFICATION_ATTEMPTS) {
                        resultText.textContent = 'Maximum attempts reached. Verification failed.';
                        setTimeout(() => window.location.href = '/', 3000);
                    } else {
                        setTimeout(() => {
                            resultContainer.classList.add('hidden');
                            isProcessing = true;
                            removeVideoEffect();
                            requestAnimationFrame(captureAndSendFrame);
                        }, 3000);
                    }
                }
                resultContainer.classList.remove('hidden');
            } else if (isProcessing) {
                console.log('Requesting next frame');
                requestAnimationFrame(captureAndSendFrame);
            }
            
            if (data.time_remaining <= 0 && data.verification_result === 'PENDING') {
                console.log('Challenge timed out, resetting...');
                socket.emit('reset', { code: sessionCode });
                verificationAttempts++;
                
                if (verificationAttempts >= MAX_VERIFICATION_ATTEMPTS) {
                    resultText.textContent = 'Maximum attempts reached. Verification failed.';
                    resultText.className = 'result-text failure';
                    resultContainer.classList.remove('hidden');
                    isProcessing = false;
                } else {
                    challengeText.textContent = `Attempt ${verificationAttempts+1} of ${MAX_VERIFICATION_ATTEMPTS}...`;
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
            console.log('Max attempts reached');
            isProcessing = false;
            resultText.textContent = 'Maximum verification attempts reached.';
            resultContainer.classList.remove('hidden');
            applyVideoEffect('failure');
        });
        
        socket.on('disconnect', () => {
            console.log('Disconnected from server');
            isProcessing = false;
        });
        
        socket.on('challenge', (data) => {
            if (data && data.text) {
                challengeText.textContent = data.text;
                console.log('New challenge received:', data.text);
            }
        });
    }
    
    function applyVideoEffect(effect) {
        if (effect === 'success') {
            videoContainer.classList.add('success-overlay');
        } else if (effect === 'failure') {
            videoContainer.classList.add('failure-overlay');
        }
    }
    
    function removeVideoEffect() {
        videoContainer.classList.remove('success-overlay', 'failure-overlay');
        resultContainer.classList.add('hidden');
    }
    
    function captureAndSendFrame() {
        if (!isProcessing) {
            console.log('Processing stopped, not capturing frame');
            return;
        }
        
        try {
            console.log('Capturing frame');
            const offscreenCanvas = document.createElement('canvas');
            offscreenCanvas.width = video.videoWidth;
            offscreenCanvas.height = video.videoHeight;
            const offscreenCtx = offscreenCanvas.getContext('2d');
            offscreenCtx.drawImage(video, 0, 0, offscreenCanvas.width, offscreenCanvas.height);
            const imageData = offscreenCanvas.toDataURL('image/jpeg', 0.8);
            console.log('Frame captured, size:', imageData.length);
            
            if (isDebugMode && frameCount % 30 === 0) {
                console.log(`Sending frame #${frameCount}`);
            }
            
            socket.emit('process_frame', {
                image: imageData,
                code: sessionCode
            });
            console.log('Frame sent to server');
            frameCount++;
        } catch (err) {
            console.error('Error capturing frame:', err);
        }
    }
    
    async function initWebcam() {
        try {
            console.log('Requesting webcam access');
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
                console.log('Webcam metadata loaded, starting playback');
                video.play().catch(err => console.error('Error playing video:', err));
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                // Start frame capture once webcam is ready
                console.log('Initial frame capture requested');
                requestAnimationFrame(captureAndSendFrame);
            };
        } catch (err) {
            console.error('Error accessing webcam:', err);
            alert('Error accessing webcam: ' + err.message);
        }
    }
    
    resetButton.addEventListener('click', () => {
        if (socket && socket.connected) {
            console.log('Sending reset request');
            socket.emit('reset', { code: sessionCode });
            resultContainer.classList.add('hidden');
            isProcessing = true;
            removeVideoEffect();
            requestAnimationFrame(captureAndSendFrame);
        }
    });
    
    function init() {
        console.log('Initializing verification page');
        initSocket();
        initWebcam();
    }
    
    window.addEventListener('beforeunload', () => {
        console.log('Cleaning up before unload');
        if (socket && socket.connected) {
            socket.disconnect();
        }
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
        }
    });
    
    init();
});