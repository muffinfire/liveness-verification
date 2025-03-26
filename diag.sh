#!/bin/bash

# Output file
output_file="diag.txt"

# List of files
files=(
    "blink_detector.py"
    "challenge_manager.py"
    "config.py"
    "face_detector.py"
    "liveness_detector.py"
    "main.py"
    "speech_recognizer.py"
    "web_app.py"
    "action_detector.py"
    "static/css/style.css"
    "templates/error.html"
    "templates/index.html"
    "templates/verify.html"
    "static/js/app.js"
    "static/js/landing.js"
)

# Clear the output file
> "$output_file"

# Iterate over the files and append their contents
for file in "${files[@]}"; do
    if [[ -f "$file" ]]; then
        echo -e "\n===== $file =====\n" >> "$output_file"
        cat "$file" >> "$output_file"
        echo -e "\n" >> "$output_file"
    else
        echo -e "\n===== $file (Not Found) =====\n" >> "$output_file"
    fi
done

echo "Diagnostic file generated: $output_file"
