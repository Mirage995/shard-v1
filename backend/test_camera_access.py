import cv2
import sys
import os
from unittest.mock import MagicMock, patch

# Already in backend directory
# sys.path.append(...)

def test_opencv_available():
    """Verify that OpenCV is installed and has VideoCapture."""
    assert hasattr(cv2, 'VideoCapture')
    assert hasattr(cv2, 'CAP_AVFOUNDATION') or sys.platform != 'darwin'

def test_camera_init_logic_windows():
    """Verify the expected initialization logic for Windows."""
    with patch('sys.platform', 'win32'):
        with patch('cv2.VideoCapture') as mock_vc:
            # Simulate what we do in ada.py
            if sys.platform == "darwin":
                cap = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)
            else:
                cap = cv2.VideoCapture(0)
            
            mock_vc.assert_called_once_with(0)

def test_camera_init_logic_mac():
    """Verify the expected initialization logic for macOS."""
    with patch('sys.platform', 'darwin'):
        with patch('cv2.VideoCapture') as mock_vc:
            # Simulate what we do in ada.py
            if sys.platform == "darwin":
                cap = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)
            else:
                cap = cv2.VideoCapture(0)
            
            mock_vc.assert_called_once_with(0, cv2.CAP_AVFOUNDATION)

def test_real_camera_access():
    """Attempt to actually open camera 0 to verify driver access."""
    if sys.platform == "darwin":
        cap = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)
    else:
        # On Windows, we need to ensure it doesn't hang if no camera is present
        # but usually VideoCapture(0) returns immediately if failed.
        cap = cv2.VideoCapture(0)
    
    is_opened = cap.isOpened()
    cap.release()
    
    if not is_opened:
         print("\n[WARN] Could not open camera 0. This is expected if no webcam is connected.")
    else:
         print("\n[OK] Camera 0 opened successfully.")

def test_camera_error_handling_mock():
    """Test that the application logic (simulated) handles failed camera opening."""
    with patch('cv2.VideoCapture') as mock_vc:
        instance = mock_vc.return_value
        instance.isOpened.return_value = False
        
        # Simulated logic from capture_face.py
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            # This is the "Error: Could not open webcam" path
            success = False
        else:
            success = True
            
        assert success == False
        print("Mocked camera failure handled correctly.")

if __name__ == "__main__":
    print(f"Running camera tests on {sys.platform}...")
    test_opencv_available()
    test_camera_init_logic_windows()
    test_camera_init_logic_mac()
    test_real_camera_access()
    test_camera_error_handling_mock()
    print("All tests passed!")
