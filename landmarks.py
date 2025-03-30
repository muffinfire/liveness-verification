import cv2
import dlib
import collections
import numpy as np

# Head pose thresholds for landmark-based detection
HEAD_POSE_THRESHOLD_HORIZONTAL = 0.4  # Symmetric deviation from 1.0 for left/right
HEAD_POSE_THRESHOLD_UP = 50           # Pixels for "up" (nose above center)
HEAD_POSE_THRESHOLD_DOWN = 25         # Pixels for "down" (nose below center)
FACE_POSITION_HISTORY_LENGTH = 3      # Number of frames for smoothing

# Optionally set selected landmarks (1-indexed). Set to an empty list or None to display all landmarks.
# For example: selected_landmarks = [37, 46, 31]
selected_landmarks = []  # Set to [] to display all landmarks

# Initialise face detector and landmark predictor
detector = dlib.get_frontal_face_detector()
predictor = dlib.shape_predictor("shape_predictor_68_face_landmarks.dat")

# Initialise a deque to store head measurements for smoothing
face_angles = collections.deque(maxlen=FACE_POSITION_HISTORY_LENGTH)

# Start video capture from the default webcam
cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Convert frame to grayscale for detection
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = detector(gray)

    for face in faces:
        landmarks = predictor(gray, face)

        # Draw landmarks (all or selected)
        if selected_landmarks:
            indices_to_show = [idx - 1 for idx in selected_landmarks if (idx - 1) < landmarks.num_parts]
        else:
            indices_to_show = range(landmarks.num_parts)

        for i in indices_to_show:
            x, y = landmarks.part(i).x, landmarks.part(i).y
            cv2.circle(frame, (x, y), 3, (0, 255, 0), -1)
            cv2.putText(frame, str(i + 1), (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # Onscreen measurement for head pose detection using key landmarks:
        # Nose tip: landmark 31 (index 30), left eye: landmark 37 (index 36), right eye: landmark 46 (index 45)
        if landmarks.num_parts > 45:
            nose = landmarks.part(30)
            left_eye = landmarks.part(36)
            right_eye = landmarks.part(45)

            # Calculate horizontal distances from nose to each eye
            left_dist = abs(nose.x - left_eye.x)
            right_dist = abs(right_eye.x - nose.x)
            horizontal_ratio = right_dist / left_dist if left_dist != 0 else 1.0

            # Calculate vertical offset: difference between nose y and face vertical center
            face_center_y = (face.top() + face.bottom()) / 2
            nose_offset = nose.y - face_center_y

            # Add current measurements to history for smoothing
            face_angles.append((horizontal_ratio, nose_offset))

            # If enough frames are accumulated, compute average values
            if len(face_angles) == FACE_POSITION_HISTORY_LENGTH:
                avg_ratio = sum(a[0] for a in face_angles) / FACE_POSITION_HISTORY_LENGTH
                avg_offset = sum(a[1] for a in face_angles) / FACE_POSITION_HISTORY_LENGTH

                # Define center boundaries based on horizontal threshold
                center_min = 1.0 - HEAD_POSE_THRESHOLD_HORIZONTAL
                center_max = 1.0 + HEAD_POSE_THRESHOLD_HORIZONTAL

                # Determine head pose based on the averaged measurements
                if avg_ratio > center_max:
                    head_pose = "right"
                elif avg_ratio < center_min:
                    head_pose = "left"
                elif avg_offset < -HEAD_POSE_THRESHOLD_UP:
                    head_pose = "up"
                elif avg_offset > HEAD_POSE_THRESHOLD_DOWN:
                    head_pose = "down"
                else:
                    head_pose = "center"

                # Display the head pose and measurements on screen
                cv2.putText(frame, f"Head Pose: {head_pose}", (50, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
                cv2.putText(frame, f"Horiz Ratio: {avg_ratio:.2f}", (50, 90),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
                cv2.putText(frame, f"Nose Offset: {avg_offset:.1f}", (50, 130),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
            else:
                # If smoothing history isn't full yet, display current measurements
                cv2.putText(frame, f"Horiz Ratio: {horizontal_ratio:.2f}", (50, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
                cv2.putText(frame, f"Nose Offset: {nose.y - face_center_y:.1f}", (50, 90),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

    cv2.imshow("Face Landmarks", frame)

    # Press 'q' to quit
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
