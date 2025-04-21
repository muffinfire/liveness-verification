#!/bin/bash

# Exit on error
set -e

# --- Configuration ---
USER="livenessuser"
CONTAINER_NAME="liveness-verification"
CONTAINER_DIR="/opt/liveness-verification"
REMOVE_USER=true      # Set to false to keep the system user
REMOVE_VOLUMES=true   # Set to true to delete unused Docker volumes

echo "Stopping and removing Docker container..."
if sudo docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    sudo docker compose -f "$CONTAINER_DIR/docker-compose.yml" down
else
    echo "Container '$CONTAINER_NAME' not found. Skipping Docker cleanup."
fi

echo "Removing container directory: $CONTAINER_DIR"
if [ -d "$CONTAINER_DIR" ]; then
    sudo rm -rf "$CONTAINER_DIR"
    echo "Directory removed."
else
    echo "Directory not found. Skipping."
fi

if [ "$REMOVE_USER" = true ]; then
    echo "Removing system user '$USER'..."
    if id -u "$USER" &>/dev/null; then
        sudo deluser --remove-home "$USER" || echo "User removal failed or partially skipped."
    else
        echo "User '$USER' does not exist. Skipping."
    fi
else
    echo "Preserving system user '$USER'."
fi

if [ "$REMOVE_VOLUMES" = true ]; then
    echo "Pruning unused Docker volumes (careful!)"
    sudo docker volume prune -f
else
    echo "Skipping Docker volume removal."
fi

echo "✅ Uninstall complete."
