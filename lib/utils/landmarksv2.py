import cv2
import dlib
import collections
import numpy as np

# Head pose thresholds
HEAD_POSE_THRESHOLD_HORIZONTAL = 0.4
HEAD_POSE_THRESHOLD_UP = 50
HEAD_POSE_THRESHOLD_DOWN = 25
FACE_POSITION_HISTORY_LENGTH = 3

# EAR blink detection config
BLINK_THRESHOLD = 0.26
MIN_BLINK_FRAMES = 2
MIN_BLINK_INTERVAL = 0.1

# Landmarks to show
selected_landmarks = [37, 46, 31]
show_all_landmarks = True

# Calculate EAR (Eye Aspect Ratio)
def calculate_ear(eye_points):
    A = np.linalg.norm(eye_points[1] - eye_points[5])
    B = np.linalg.norm(eye_points[2] - eye_points[4])
    C = np.linalg.norm(eye_points[0] - eye_points[3])
    return (A + B) / (2.0 * C) if C != 0 else 0 # if C is not 0, return the EAR, otherwise return 0

# Initialise detector and predictor
detector = dlib.get_frontal_face_detector()
predictor = dlib.shape_predictor("bin/shape_predictor_68_face_landmarks.dat") # Load the shape predictor

face_angles = collections.deque(maxlen=FACE_POSITION_HISTORY_LENGTH) # Initialise a deque to store the face angles
blink_frames = 0 # Initialise the blink frames
blink_counter = 0 # Initialise the blink counter
last_blink_time = 0 # Initialise the last blink time

cap = cv2.VideoCapture(2) # Initialise the video capture (0 for webcam, 2 for external camera)
cv2.namedWindow("Face Landmarks") # Create a window for the face landmarks

# Main loop
while True:
    ret, frame = cap.read() # Read the frame from the video capture
    if not ret: # If the frame is not read, break the loop
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) # Convert the frame to grayscale
    faces = detector(gray) # Detect the faces in the frame

    # Process each face in the frame
    for face in faces:
        landmarks = predictor(gray, face) # Predict the landmarks for the face

        if show_all_landmarks or not selected_landmarks: # If all landmarks are to be shown, or if no landmarks are selected, show all landmarks
            indices_to_show = range(landmarks.num_parts) # Show all landmarks
        else:
            indices_to_show = [idx - 1 for idx in selected_landmarks if (idx - 1) < landmarks.num_parts] # Show only the selected landmarks

        # Draw the landmarks on the frame
        for i in indices_to_show:
            x, y = landmarks.part(i).x, landmarks.part(i).y
            cv2.circle(frame, (x, y), 6, (255, 20, 20), -1)
            cv2.putText(frame, str(i + 1), (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 255), 2)

        # Head pose estimation
        if landmarks.num_parts > 45: # If the number of landmarks is greater than 45, estimate the head pose
            nose = landmarks.part(30) # Get the nose landmark
            left_eye_center = landmarks.part(36) # Get the left eye landmark
            right_eye_center = landmarks.part(45) # Get the right eye landmark

            left_dist = abs(nose.x - left_eye_center.x) # Calculate the distance between the nose and the left eye
            right_dist = abs(right_eye_center.x - nose.x) # Calculate the distance between the nose and the right eye
            horizontal_ratio = right_dist / left_dist if left_dist != 0 else 1.0 # Calculate the horizontal ratio
            face_center_y = (face.top() + face.bottom()) / 2 # Calculate the face center y
            nose_offset = nose.y - face_center_y # Calculate the nose offset

            face_angles.append((horizontal_ratio, nose_offset)) # Append the face angles to the deque

            if len(face_angles) == FACE_POSITION_HISTORY_LENGTH: # If the number of face angles is equal to the history length
                avg_ratio = sum(a[0] for a in face_angles) / FACE_POSITION_HISTORY_LENGTH # Calculate the average horizontal ratio
                avg_offset = sum(a[1] for a in face_angles) / FACE_POSITION_HISTORY_LENGTH # Calculate the average nose offset

                center_min = 1.0 - HEAD_POSE_THRESHOLD_HORIZONTAL # Calculate the minimum horizontal ratio
                center_max = 1.0 + HEAD_POSE_THRESHOLD_HORIZONTAL # Calculate the maximum horizontal ratio

                if avg_ratio > center_max: # If the average horizontal ratio is greater than the maximum horizontal ratio, set the head pose to right
                    head_pose = "RIGHT"
                elif avg_ratio < center_min: # If the average horizontal ratio is less than the minimum horizontal ratio, set the head pose to left
                    head_pose = "LEFT"
                elif avg_offset < -HEAD_POSE_THRESHOLD_UP: # If the average nose offset is less than the minimum nose offset, set the head pose to up
                    head_pose = "UP"
                elif avg_offset > HEAD_POSE_THRESHOLD_DOWN: # If the average nose offset is greater than the maximum nose offset, set the head pose to down
                    head_pose = "DOWN"
                else:
                    head_pose = "CENTER" # If the average horizontal ratio is between the minimum and maximum horizontal ratio, and the average nose offset is between the minimum and maximum nose offset, set the head pose to center
            else:
                head_pose = "..." # If the number of face angles is not equal to the history length, set the head pose to "..."

        # EAR + blink detection (only if eye landmarks available)
        left_eye = np.array([(landmarks.part(i).x, landmarks.part(i).y) for i in range(36, 42)]) # Get the left eye landmarks
        right_eye = np.array([(landmarks.part(i).x, landmarks.part(i).y) for i in range(42, 48)]) # Get the right eye landmarks
        left_ear = calculate_ear(left_eye) # Calculate the left eye aspect ratio
        right_ear = calculate_ear(right_eye) # Calculate the right eye aspect ratio
        avg_ear = (left_ear + right_ear) / 2.0 # Calculate the average eye aspect ratio

        if avg_ear < BLINK_THRESHOLD: # If the average eye aspect ratio is less than the blink threshold, increment the blink frames
            blink_frames += 1
        else:
            if blink_frames >= MIN_BLINK_FRAMES and (cv2.getTickCount() - last_blink_time) / cv2.getTickFrequency() > MIN_BLINK_INTERVAL: # If the blink frames are greater than the minimum blink frames, and the time since the last blink is greater than the minimum blink interval, increment the blink counter, and set the last blink time to the current time
                blink_counter += 1
                last_blink_time = cv2.getTickCount()
            blink_frames = 0

        # Draw mesh around eyes
        # Draw thicker eye contours and show EAR on each eye
        for eye, ear in zip([left_eye, right_eye], [left_ear, right_ear]):
            for i in range(len(eye)):
                pt1 = tuple(eye[i]) # Get the first point
                pt2 = tuple(eye[(i + 1) % len(eye)]) # Get the second point
                cv2.line(frame, pt1, pt2, (255, 220, 200), 2)  # Thicker mesh lines

            # Display EAR value slightly higher above eye
            text_pos = tuple(eye[0] + np.array([0, -25]))  # Offset upward
            cv2.putText(frame, f"{ear:.2f}", text_pos,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 220, 200), 2) # Draw the EAR value slightly higher above the eye

        # Bottom info bar
        overlay = frame.copy()
        bar_y1 = frame.shape[0] - 100
        bar_y2 = frame.shape[0]
        cv2.rectangle(overlay, (0, bar_y1), (frame.shape[1], bar_y2), (0, 0, 0), -1)
        alpha = 0.8
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

        cv2.putText(frame, f"EAR: {avg_ear:.2f}", (100, bar_y1 + 75), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 220, 200), 2) # Blue
        cv2.putText(frame, f"Blinks: {blink_counter}", (500, bar_y1 + 75), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 0, 255), 2) # Purple
        cv2.putText(frame, f"Head Pose: {head_pose}", (875, bar_y1 + 75), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 2) # Red
        # Display detailed head pose metrics for explanation/debug
        if len(face_angles) == FACE_POSITION_HISTORY_LENGTH:
            cv2.putText(frame, f"Horiz Ratio: {avg_ratio:.2f}", (1550, bar_y1 + 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 180, 255), 2) # Orange
            cv2.putText(frame, f"Nose Offset: {avg_offset:.1f}", (1550, bar_y1 + 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 180, 255), 2) # Orange

        mode_text = "All Landmarks" if show_all_landmarks else "Selected Landmarks"
        cv2.putText(frame, f"Mode: {mode_text}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)

    cv2.imshow("Face Landmarks", frame) # Display the frame

    key = cv2.waitKey(1) & 0xFF # Wait for a key press
    if key == ord('q'): # If the key pressed is 'q', break the loop
        break
    elif key == ord(' '):  # space bar toggles landmark mode
        show_all_landmarks = not show_all_landmarks
        print(f"Toggled to: {'All Landmarks' if show_all_landmarks else 'Selected Landmarks'}")


cap.release() # Release the video capture
cv2.destroyAllWindows() # Destroy all windows
