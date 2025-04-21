#!/bin/bash

# Exit immediately if a command fails
set -e

# --- Configuration Variables ---
BRANCH="Prod"                             # Git branch to clone
USER="livenessuser"                       # System user for running the app
REPO_URL="https://github.com/muffinfire/liveness-verification.git"
CONTAINER_DIR="/opt/liveness-verification"
CONTAINER_NAME="liveness-verification"    # Matches docker-compose.yml

# --- 1. Create system user if it doesn't exist ---
if ! id -u "$USER" &>/dev/null; then
    echo "Creating system user '$USER'..."
    sudo adduser --system --no-create-home --group "$USER"
else
    echo "User '$USER' already exists."
fi

# --- 2. Create container folder and fix permissions ---
echo "Creating container directory at $CONTAINER_DIR..."
if [ -d "$CONTAINER_DIR" ]; then
    echo "Removing old repository..."
    sudo rm -rf "$CONTAINER_DIR"
fi
sudo mkdir -p "$CONTAINER_DIR"
sudo chown "$USER":"$USER" "$CONTAINER_DIR"
sudo chmod 755 "$CONTAINER_DIR"

# --- 3. Clone the repo with the specified branch ---
echo "Cloning repository from GitHub ($BRANCH branch)..."
sudo -u "$USER" git clone -b "$BRANCH" "$REPO_URL" "$CONTAINER_DIR" || {
    echo "Git clone failed or branch '$BRANCH' not found. Falling back to main and checking out $BRANCH..."
    sudo -u "$USER" git clone "$REPO_URL" "$CONTAINER_DIR"
    cd "$CONTAINER_DIR" || { echo "Failed to change directory to $CONTAINER_DIR"; exit 1; }
    sudo -u "$USER" git checkout "$BRANCH" || {
        echo "Failed to checkout $BRANCH branch. Verify the branch name."
        exit 1
    }
}

# --- 4. Build and run the container ---
cd "$CONTAINER_DIR" || { echo "Failed to change directory to $CONTAINER_DIR"; exit 1; }
echo "Building and running Docker container..."

# Check if docker-compose.yml exists
if [ ! -f "docker-compose.yml" ]; then
    echo "Error: docker-compose.yml not found in $CONTAINER_DIR"
    exit 1
fi

# Ensure QR codes directory exists and has correct permissions
sudo -u "$USER" mkdir -p "$CONTAINER_DIR/static/qr_codes"
sudo -u "$USER" chmod 755 "$CONTAINER_DIR/static/qr_codes"

# Build and run with Docker Compose
echo "Starting Docker container with $BRANCH branch..."
sudo docker compose up -d --build
if [ $? -ne 0 ]; then
    echo "Docker Compose failed"
    exit 1
fi

echo "Deployment complete! The $BRANCH branch is running at http://<server-ip>:8001."
echo "Check logs with: sudo docker logs $CONTAINER_NAME"
