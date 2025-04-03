// Wait for the HTML document to fully load before executing the script
document.addEventListener('DOMContentLoaded', () => {
    // Get references to DOM elements used in the application
    const generateCodeBtn = document.getElementById('generate-code-btn'); // Button to generate a verification code
    const codeDisplay = document.getElementById('code-display'); // Container to show the generated code
    const verificationCode = document.getElementById('verification-code'); // Element to display the code text
    const verificationStatus = document.getElementById('verification-status'); // Displays verification status messages
    const codeInput = document.getElementById('code-input'); // Input field for entering a code
    const submitCodeBtn = document.getElementById('submit-code-btn'); // Button to submit the entered code
    const verifyContainer = document.getElementById('verify-container'); // Container for verification status
    const verifyStatus = document.createElement('div'); // Dynamic element for showing validation status
    const qrDisplay = document.createElement('div'); // Dynamic element to display the QR code
    
    // Set up the verifyStatus element
    verifyStatus.className = 'verify-status'; // Assign a class for styling
    verifyContainer.appendChild(verifyStatus); // Add it to the verify container in the DOM
    qrDisplay.id = 'qr-display'; // Set an ID for the QR code display element
    codeDisplay.appendChild(qrDisplay); // Add QR display under the code display container
    
    let socket; // Socket.IO connection to the server
    let currentCode = null; // Stores the currently generated verification code
    
    // Initialize the Socket.IO connection and set up event listeners
    function initSocket() {
        console.log('Initializing socket connection');
        socket = io(); // Create a new Socket.IO connection to the server
        
        // Handle successful connection to the server
        socket.on('connect', () => {
            console.log('Connected to server');
        });
        
        // Handle disconnection from the server
        socket.on('disconnect', () => {
            console.log('Disconnected from server');
        });
        
        // Handle errors from the server
        socket.on('error', (data) => {
            console.error('Socket error:', data);
            verificationStatus.textContent = `Error: ${data.message}`; // Show error message
            verificationStatus.className = 'status-error'; // Apply error styling
        });
        
        // Handle receipt of a new verification code from the server
        socket.on('verification_code', (data) => {
            console.log('Received verification code:', data.code);
            currentCode = data.code; // Store the received code
            verificationCode.textContent = currentCode; // Display the code
            codeDisplay.classList.remove('hidden'); // Show the code display container
            generateCodeBtn.classList.add('hidden'); // Hide the generate button
            
            // Check if video background is enabled
            if (data.enable_video_background) {
                // Create video background container
                const videoQrContainer = document.createElement('div');
                videoQrContainer.className = 'video-qr-container';
                
                // Create video element for background
                const videoBackground = document.createElement('video');
                videoBackground.autoplay = true;
                videoBackground.playsInline = true;
                videoBackground.muted = true;
                videoBackground.className = 'qr-video-background';
                
                // Create QR overlay element - ensure it's visible initially
                const qrOverlay = document.createElement('div');
                qrOverlay.className = 'qr-overlay';
                qrOverlay.style.opacity = '1'; // Make sure QR code is fully visible initially
                qrOverlay.innerHTML = `<img src="${data.qr_code}" alt="QR Code for ${data.code}">`;
                
                // Add elements to container
                videoQrContainer.appendChild(videoBackground);
                videoQrContainer.appendChild(qrOverlay);
                qrDisplay.innerHTML = ''; // Clear existing content
                qrDisplay.appendChild(videoQrContainer);
                
                // Initialize webcam for video background
                initQrVideoBackground(videoBackground);
            } else {
                // Standard QR code display without video background
                qrDisplay.innerHTML = `<img src="${data.qr_code}" alt="QR Code for ${data.code}">`; // Display QR code image
            }
            
            // Update status to indicate waiting for verification
            verificationStatus.textContent = 'Waiting for verification...';
            verificationStatus.className = 'status-waiting'; // Apply waiting styling
        });
        
        // Handle notification that verification has started
        socket.on('verification_started', (data) => {
            if (data.code === currentCode) { // Check if it matches the current code
                verificationStatus.textContent = 'Verification in progress...';
                verificationStatus.className = 'status-progress'; // Apply in-progress styling
                
                // Handle partner video display if flag is set
                if (data.partner_video) {
                    // Find the QR code container
                    const qrContainer = document.querySelector('.video-qr-container');
                    const qrOverlay = document.querySelector('.qr-overlay');
                    const videoBackground = document.querySelector('.qr-video-background');
                    
                    if (qrContainer && qrOverlay) {
                        // Fade out QR code
                        qrOverlay.style.transition = 'opacity 1.5s ease';
                        qrOverlay.style.opacity = '0.0'; // Almost completely transparent
                        
                        // Remove the waiting message if it exists
                        const waitingText = qrContainer.querySelector('.waiting-for-partner');
                        if (waitingText) {
                            waitingText.remove();
                        }
                    }
                }
            }
        });
        
        // Handle partner video frames coming from the verification page
        socket.on('partner_video_frame', (data) => {
            if (data.code === currentCode) {
                const videoBackground = document.querySelector('.qr-video-background');
                const qrContainer = document.querySelector('.video-qr-container');
                
                if (videoBackground && data.image) {
                    // Create an image element to display the partner's video frame
                    if (!qrContainer.querySelector('.partner-video-frame')) {
                        const partnerVideoFrame = document.createElement('img');
                        partnerVideoFrame.className = 'partner-video-frame';
                        // Apply centering and sizing styles
                        partnerVideoFrame.style.position = 'absolute';
                        partnerVideoFrame.style.top = '50%'; // Center vertically
                        partnerVideoFrame.style.left = '50%'; // Center horizontally
                        partnerVideoFrame.style.transform = 'translate(-50%, -50%)'; // Offset by half its size
                        partnerVideoFrame.style.width = '100%'; // Fill container width
                        partnerVideoFrame.style.height = '100%'; // Fill container height
                        partnerVideoFrame.style.objectFit = 'contain'; // Preserve aspect ratio
                        partnerVideoFrame.style.objectPosition = 'center'; // Center the content
                        partnerVideoFrame.style.zIndex = '1'; // Between video and overlay
                        
                        // Remove flexbox centering from container (not needed with absolute positioning)
                        qrContainer.style.display = ''; // Reset to default
                        qrContainer.style.justifyContent = '';
                        qrContainer.style.alignItems = '';
                        
                        qrContainer.insertBefore(partnerVideoFrame, qrContainer.querySelector('.qr-overlay'));
                    }
                    
                    // Update the image with the new frame
                    const partnerVideoFrame = qrContainer.querySelector('.partner-video-frame');
                    if (partnerVideoFrame) {
                        partnerVideoFrame.src = data.image;
                    }
                    
                }
            }
        });
        
        // Handle the final verification result from the server
        socket.on('verification_result', (data) => {
            if (data.code === currentCode) { // Check if it matches the current code
                // Find the partner video frame if it exists
                const partnerVideoFrame = document.querySelector('.partner-video-frame');
                
                if (data.duress_detected) {
                    verificationStatus.textContent = 'Duress Detected!\n!!! DO NOT PROCEED !!!'; // Duress warning
                    verificationStatus.className = 'status-duress'; // Apply duress styling
                    
                    // Apply orange/duress effect to partner video if it exists
                    if (partnerVideoFrame) {
                        partnerVideoFrame.style.filter = 'sepia(0.3) saturate(1.5) brightness(0.9) hue-rotate(10deg)';
                        partnerVideoFrame.style.border = '3px solid #e67e22';
                    }
                } else if (data.result === 'PASS') {
                    verificationStatus.textContent = 'Verification PASSED'; // Success message
                    verificationStatus.className = 'status-success'; // Apply success styling
                    
                    // Apply green/success effect to partner video if it exists
                    if (partnerVideoFrame) {
                        partnerVideoFrame.style.filter = 'sepia(0.2) saturate(1.5) brightness(1.1) hue-rotate(60deg)';
                        partnerVideoFrame.style.border = '3px solid #2ecc71';
                    }
                } else {
                    verificationStatus.textContent = 'Verification FAILED'; // Failure message
                    verificationStatus.className = 'status-failed'; // Apply failure styling
                    
                    // Apply red/failure effect to partner video if it exists
                    if (partnerVideoFrame) {
                        partnerVideoFrame.style.filter = 'sepia(0.3) saturate(1.5) brightness(0.9) hue-rotate(-20deg)';
                        partnerVideoFrame.style.border = '3px solid #e74c3c';
                    }
                }
                // Status persists; no auto-reset here
            }
        });
        
        // Handle code-specific errors from the server
        socket.on('code_error', (data) => {
            showVerifyError(data.message); // Display the error message
        });
    }
    
    // Function to initialize QR code video background
    // Note: We no longer initialize the user's webcam here
    // The partner's video will be streamed from the verification page
    async function initQrVideoBackground(videoElement) {
        try {
            // Create a placeholder for partner's video
            // The actual video stream will come from the partner during verification
            
            // Add a message indicating waiting for partner
            const waitingText = document.createElement('div');
            waitingText.className = 'waiting-for-partner';
            waitingText.textContent = 'Waiting for partner to connect...';
            videoElement.parentNode.appendChild(waitingText);
            
            // We don't set videoElement.srcObject here anymore
            // Instead, we'll receive the partner's video stream via WebRTC or server relay
            
            // When video starts playing, fade in the QR code overlay
            videoElement.onloadedmetadata = () => {
                videoElement.play().catch(err => console.error('Error playing video:', err));
                
                // Fade in QR code overlay after video starts
                setTimeout(() => {
                    const qrOverlay = videoElement.nextElementSibling;
                    if (qrOverlay) {
                        qrOverlay.style.opacity = '0.8'; // Start with 80% opacity
                        
                        // Gradually reduce opacity to 10-20%
                        setTimeout(() => {
                            qrOverlay.style.opacity = '0.0'; // Final 20% opacity
                        }, 2000); // After 2 seconds
                    }
                }, 500);
            };
        } catch (err) {
            console.error('Error accessing webcam for QR background:', err);
        }
    }
    
    // Add click event listener to the generate code button
    generateCodeBtn.addEventListener('click', () => {
        // console.log('Generate code button clicked');
        if (socket && socket.connected) { // Check if socket is already connected
            socket.emit('generate_code'); // Request a new code from the server
        } else {
            console.error('Socket not connected');
            initSocket(); // Initialize socket if not connected
            setTimeout(() => { // Wait 1 second to ensure connection
                if (socket && socket.connected) {
                    socket.emit('generate_code'); // Request a new code
                } else {
                    console.error('Failed to reconnect socket');
                }
            }, 1000);
        }
    });
    
    // Function to display a verification error message
    function showVerifyError(message) {
        verifyStatus.textContent = message; // Set the error message
        verifyStatus.className = 'verify-status error'; // Apply error styling
        
        // Clear the error message after 3 seconds
        setTimeout(() => {
            verifyStatus.textContent = '';
            verifyStatus.className = 'verify-status'; // Reset to default styling
        }, 3000);
    }
    
    // Function to display a verification success message
    function showVerifySuccess(message) {
        verifyStatus.textContent = message; // Set the success message
        verifyStatus.className = 'verify-status success'; // Apply success styling
        
        // Clear the success message after 1 second
        setTimeout(() => {
            verifyStatus.textContent = '';
            verifyStatus.className = 'verify-status'; // Reset to default styling
        }, 1000);
    }
    
    // Add click event listener to the submit code button
    submitCodeBtn.addEventListener('click', () => {
        const code = codeInput.value.trim(); // Get and clean the entered code
        
        // Validate the code format (6 digits)
        if (code.length !== 6 || !/^\d+$/.test(code)) {
            showVerifyError('Please enter a valid 6-digit code'); // Show error if invalid
            return;
        }
        
        submitCodeBtn.disabled = true; // Disable the button during validation
        submitCodeBtn.textContent = 'Checking...'; // Update button text
        verifyStatus.textContent = 'Validating code...'; // Show validation in progress
        verifyStatus.className = 'verify-status info'; // Apply info styling
        
        // Send a fetch request to check the code validity
        fetch(`/check_code/${code}`)
            .then(response => {
                if (!response.ok) { // Check if the response is not OK
                    throw new Error(`Server error: ${response.status}`);
                }
                return response.json(); // Parse the JSON response
            })
            .then(data => {
                submitCodeBtn.disabled = false; // Re-enable the button
                submitCodeBtn.textContent = 'Verify'; // Restore button text
                
                if (data.valid) { // If the code is valid
                    showVerifySuccess('Code valid! Redirecting...'); // Show success message
                    setTimeout(() => {
                        window.location.href = `/verify/${code}`; // Redirect to verification page
                    }, 1000);
                } else {
                    showVerifyError('Invalid code. Please check and try again.'); // Show error if invalid
                }
            })
            .catch(error => { // Handle fetch errors
                console.error('Error checking code:', error);
                submitCodeBtn.disabled = false; // Re-enable the button
                submitCodeBtn.textContent = 'Verify'; // Restore button text
                showVerifyError('Error checking code. Please try again.'); // Show error message
            });
    });
    
    // Add keypress event listener to the code input for Enter key
    codeInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') { // If Enter key is pressed
            submitCodeBtn.click(); // Simulate a click on the submit button
        }
    });
    
    // Initialize the socket connection when the script runs
    initSocket();
});