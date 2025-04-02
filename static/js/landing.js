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
            qrDisplay.innerHTML = `<img src="${data.qr_code}" alt="QR Code for ${data.code}">`; // Display QR code image
            
            // Update status to indicate waiting for verification
            verificationStatus.textContent = 'Waiting for verification...';
            verificationStatus.className = 'status-waiting'; // Apply waiting styling
        });
        
        // Handle notification that verification has started
        socket.on('verification_started', (data) => {
            if (data.code === currentCode) { // Check if it matches the current code
                verificationStatus.textContent = 'Verification in progress...';
                verificationStatus.className = 'status-progress'; // Apply in-progress styling
            }
        });
        
        // Handle the final verification result from the server
        socket.on('verification_result', (data) => {
            if (data.code === currentCode) { // Check if it matches the current code
                if (data.duress_detected) {
                    verificationStatus.textContent = 'Duress Detected!\n!!! DO NOT PROCEED !!!'; // Duress warning
                    verificationStatus.className = 'status-duress'; // Apply duress styling
                } else if (data.result === 'PASS') {
                    verificationStatus.textContent = 'Verification PASSED'; // Success message
                    verificationStatus.className = 'status-success'; // Apply success styling
                } else {
                    verificationStatus.textContent = 'Verification FAILED'; // Failure message
                    verificationStatus.className = 'status-failed'; // Apply failure styling
                }
                // Status persists; no auto-reset here
            }
        });
        
        // Handle code-specific errors from the server
        socket.on('code_error', (data) => {
            showVerifyError(data.message); // Display the error message
        });
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