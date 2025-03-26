document.addEventListener('DOMContentLoaded', () => {
    const generateCodeBtn = document.getElementById('generate-code-btn');
    const codeDisplay = document.getElementById('code-display');
    const verificationCode = document.getElementById('verification-code');
    const verificationStatus = document.getElementById('verification-status');
    const codeInput = document.getElementById('code-input');
    const submitCodeBtn = document.getElementById('submit-code-btn');
    const verifyContainer = document.getElementById('verify-container');
    const verifyStatus = document.createElement('div');
    const qrDisplay = document.createElement('div'); // Add QR code display
    
    verifyStatus.className = 'verify-status';
    verifyContainer.appendChild(verifyStatus);
    qrDisplay.id = 'qr-display';
    codeDisplay.appendChild(qrDisplay); // Add QR display under code
    
    let socket;
    let currentCode = null;
    
    // Initialize Socket.IO connection
    function initSocket() {
        console.log('Initializing socket connection');
        socket = io();
        
        socket.on('connect', () => {
            console.log('Connected to server');
        });
        
        socket.on('disconnect', () => {
            console.log('Disconnected from server');
        });
        
        socket.on('error', (data) => {
            console.error('Socket error:', data);
            verificationStatus.textContent = `Error: ${data.message}`;
            verificationStatus.className = 'status-error';
        });
        
        socket.on('verification_code', (data) => {
            console.log('Received verification code:', data.code);
            currentCode = data.code;
            verificationCode.textContent = currentCode;
            codeDisplay.classList.remove('hidden');
            generateCodeBtn.classList.add('hidden');
            qrDisplay.innerHTML = `<img src="${data.qr_code}" alt="QR Code for ${data.code}">`;
            
            // Update status
            verificationStatus.textContent = 'Waiting for verification...';
            verificationStatus.className = 'status-waiting';
        });
        
        socket.on('verification_started', (data) => {
            if (data.code === currentCode) {
                verificationStatus.textContent = 'Verification in progress...';
                verificationStatus.className = 'status-progress';
            }
        });
        
        socket.on('verification_result', (data) => {
            if (data.code === currentCode) {
                if (data.duress_detected) {
                    verificationStatus.textContent = 'Duress Detected!\n!!! DO NOT PROCEED !!!';
                    verificationStatus.className = 'status-duress';
                } else if (data.result === 'PASS') {
                    verificationStatus.textContent = 'Verification PASSED';
                    verificationStatus.className = 'status-success';
                } else {
                    verificationStatus.textContent = 'Verification FAILED';
                    verificationStatus.className = 'status-failed';
                }
                // Status persists; no auto-reset here
            }
        });
        
        socket.on('code_error', (data) => {
            showVerifyError(data.message);
        });
    }
    
    // Generate verification code
    generateCodeBtn.addEventListener('click', () => {
        console.log('Generate code button clicked');
        if (socket && socket.connected) {
            socket.emit('generate_code');
        } else {
            console.error('Socket not connected');
            initSocket();
            setTimeout(() => {
                if (socket && socket.connected) {
                    socket.emit('generate_code');
                } else {
                    console.error('Failed to reconnect socket');
                }
            }, 1000);
        }
    });
    
    // Show verification error
    function showVerifyError(message) {
        verifyStatus.textContent = message;
        verifyStatus.className = 'verify-status error';
        
        setTimeout(() => {
            verifyStatus.textContent = '';
            verifyStatus.className = 'verify-status';
        }, 3000);
    }
    
    // Show verification success
    function showVerifySuccess(message) {
        verifyStatus.textContent = message;
        verifyStatus.className = 'verify-status success';
        
        setTimeout(() => {
            verifyStatus.textContent = '';
            verifyStatus.className = 'verify-status';
        }, 1000);
    }
    
    // Submit verification code
    submitCodeBtn.addEventListener('click', () => {
        const code = codeInput.value.trim();
        
        if (code.length !== 6 || !/^\d+$/.test(code)) {
            showVerifyError('Please enter a valid 6-digit code');
            return;
        }
        
        submitCodeBtn.disabled = true;
        submitCodeBtn.textContent = 'Checking...';
        verifyStatus.textContent = 'Validating code...';
        verifyStatus.className = 'verify-status info';
        
        fetch(`/check_code/${code}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Server error: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                submitCodeBtn.disabled = false;
                submitCodeBtn.textContent = 'Verify';
                
                if (data.valid) {
                    showVerifySuccess('Code valid! Redirecting...');
                    setTimeout(() => {
                        window.location.href = `/verify/${code}`;
                    }, 1000);
                } else {
                    showVerifyError('Invalid code. Please check and try again.');
                }
            })
            .catch(error => {
                console.error('Error checking code:', error);
                submitCodeBtn.disabled = false;
                submitCodeBtn.textContent = 'Verify';
                showVerifyError('Error checking code. Please try again.');
            });
    });
    
    // Handle Enter key in code input
    codeInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            submitCodeBtn.click();
        }
    });
    
    // Initialize
    initSocket();
});