document.addEventListener('DOMContentLoaded', () => {
    const generateCodeBtn = document.getElementById('generate-code-btn');
    const codeDisplay = document.getElementById('code-display');
    const verificationCode = document.getElementById('verification-code');
    const verificationStatus = document.getElementById('verification-status');
    const codeInput = document.getElementById('code-input');
    const submitCodeBtn = document.getElementById('submit-code-btn');
    const verifyContainer = document.getElementById('verify-container');
    const verifyStatus = document.createElement('div');
    
    verifyStatus.className = 'verify-status';
    verifyContainer.appendChild(verifyStatus);
    
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
        });
        
        socket.on('verification_code', (data) => {
            console.log('Received verification code:', data.code);
            currentCode = data.code;
            verificationCode.textContent = currentCode;
            codeDisplay.classList.remove('hidden');
            generateCodeBtn.classList.add('hidden');
            
            // Update status
            verificationStatus.textContent = 'Waiting for verification...';
            verificationStatus.className = 'status-waiting';
        });
        
        socket.on('verification_started', (data) => {
            verificationStatus.textContent = 'Verification in progress...';
            verificationStatus.className = 'status-waiting';
        });
        
        socket.on('verification_result', (data) => {
            if (data.result === 'PASS') {
                verificationStatus.textContent = 'Verification PASSED ✅';
                verificationStatus.className = 'status-success';
            } else {
                verificationStatus.textContent = 'Verification FAILED ❌';
                verificationStatus.className = 'status-failed';
            }
            
            // Re-enable generate button after 5 seconds
            setTimeout(() => {
                generateCodeBtn.classList.remove('hidden');
                codeDisplay.classList.add('hidden');
                currentCode = null;
            }, 5000);
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
            // Try to reconnect
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
        
        // Clear after 3 seconds
        setTimeout(() => {
            verifyStatus.textContent = '';
            verifyStatus.className = 'verify-status';
        }, 3000);
    }
    
    // Show verification success
    function showVerifySuccess(message) {
        verifyStatus.textContent = message;
        verifyStatus.className = 'verify-status success';
        
        // Clear after 1 second before redirect
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
        
        // Show loading state
        submitCodeBtn.disabled = true;
        submitCodeBtn.textContent = 'Checking...';
        verifyStatus.textContent = 'Validating code...';
        verifyStatus.className = 'verify-status info';
        
        // Check if code exists via fetch API
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
                    // Redirect to verification page with code
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