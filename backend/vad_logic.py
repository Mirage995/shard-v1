import math
import struct
import time
import asyncio
import pyaudio
import os
import sys

# Constants extracted from monolithic AudioLoop
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
CHUNK_SIZE = 1024
VAD_THRESHOLD = 800 # Voice Activity Detection threshold
SILENCE_DURATION = 0.5 # Seconds of silence to consider "done speaking"

class VADLogic:
    """
    Isolated module for Voice Activity Detection logic.
    """
    def __init__(self):
        self._is_speaking = False
        self._silence_start_time = None

    def analyze_chunk(self, data):
        """Analyzes an audio chunk for voice activity."""
        count = len(data) // 2
        if count == 0:
            rms = 0
        else:
            shorts = struct.unpack(f"<{count}h", data)
            sum_squares = sum(s**2 for s in shorts)
            rms = int(math.sqrt(sum_squares / count))
        
        speech_detected = rms > VAD_THRESHOLD

        if speech_detected:
            self._silence_start_time = None
            if not self._is_speaking:
                self._is_speaking = True
                # print(f"[VAD] Speech Detected (RMS: {rms}).")
                return "SPEECH_START"
            return "SPEAKING"
        else:
            if self._is_speaking:
                if self._silence_start_time is None:
                    self._silence_start_time = time.time()
                elif time.time() - self._silence_start_time > SILENCE_DURATION:
                    # print(f"[VAD] Silence detected. Resetting speech state.")
                    self._is_speaking = False
                    self._silence_start_time = None
                    return "SILENCE_END"
            return "SILENCE"
    
    def is_speaking(self):
        return self._is_speaking

