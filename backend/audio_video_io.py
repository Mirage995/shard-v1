import asyncio
import base64
import time
import os
import pyaudio
import PIL.Image
import mss
import struct
import math

from vad_logic import VADLogic, FORMAT, CHANNELS, SEND_SAMPLE_RATE, CHUNK_SIZE

class AudioVideoIO:
    """
    Handles all Audio/Video I/O, streaming to Gemini, and real-time buffering.
    Integrates VAD logic to manage vision frame transmission heuristics.
    """
    def __init__(self, pya_instance, on_transcription=None, on_tool_confirmation=None, project_manager=None):
        self.pya = pya_instance
        self.on_transcription = on_transcription
        self.project_manager = project_manager
        
        self.vad_logic = VADLogic()
        self.audio_stream = None
        self.out_queue = None
        self.session = None
        self.paused = False
        # Deaf Mode: True while SHARD is playing audio -- mic chunks are read but
        # not forwarded to Gemini, preventing acoustic feedback loops.
        self._ai_speaking: bool = False

        self.chat_buffer = {"sender": None, "text": ""}
        self._last_input_transcription = ""
        self._last_output_transcription = ""
        self._last_vision_frame_time = 0.0
        self._latest_image_payload = None
        self._is_speaking = False # Managed by VADLogic now

    def set_ai_speaking(self, speaking: bool):
        """Called by _play_audio to activate/deactivate Deaf Mode."""
        if self._ai_speaking != speaking:
            self._ai_speaking = speaking
            print(f"[AudioVideoIO] Deaf Mode: {'ON -- mic muted' if speaking else 'OFF -- mic active'}")

    def set_session(self, session):
        self.session = session

    def set_out_queue(self, out_queue):
        self.out_queue = out_queue

    def _flush_buffer_inline(self, memory, consciousness, tuning):
        """Flush chat buffer to backends (log, memory, consciousness, tuning)."""
        if self.chat_buffer["sender"] and self.chat_buffer["text"].strip():
            if self.project_manager:
                self.project_manager.log_chat(self.chat_buffer["sender"], self.chat_buffer["text"])
            memory.remember_conversation(self.chat_buffer["sender"], self.chat_buffer["text"])
            consciousness.process_interaction(self.chat_buffer["sender"], self.chat_buffer["text"])
            if self.chat_buffer["sender"] == "User":
                tuning.analyze_interaction(self.chat_buffer["text"], "")
        self.chat_buffer = {"sender": None, "text": ""}
        self._last_input_transcription = ""
        self._last_output_transcription = ""

    def clear_audio_queue(self, audio_in_queue):
        """Clears the queue of pending audio chunks to stop playback immediately."""
        try:
            count = 0
            while not audio_in_queue.empty():
                audio_in_queue.get_nowait()
                count += 1
            if count > 0:
                print(f"[AudioVideoIO] Cleared {count} chunks from playback queue due to interruption.")
        except Exception as e:
            print(f"[AudioVideoIO] Failed to clear audio queue: {e}")

    async def send_frame(self, frame_data):
        """Updates the latest frame payload and sends periodically or on VAD trigger."""
        if isinstance(frame_data, bytes):
            b64_data = base64.b64encode(frame_data).decode('utf-8')
        else:
            b64_data = frame_data 

        self._latest_image_payload = {"mime_type": "image/jpeg", "data": b64_data}
        
        now = time.time()
        # Throttle continuous vision send rate
        if now - self._last_vision_frame_time > 1.5: 
            if self.out_queue and self.session:
                # print(f"[AudioVideoIO] Sending continuous vision frame.")
                await self.out_queue.put(self._latest_image_payload)
                self._last_vision_frame_time = now

    async def listen_audio(self, out_queue):
        """Listens to microphone and streams audio chunks to the output queue, applying VAD heuristics."""
        # Device resolution logic truncated for brevity but assumed similar to original
        resolved_input_device_index = None # Using default for refactor clarity

        try:
            self.audio_stream = await asyncio.to_thread(
                self.pya.open,
                format=FORMAT,
                channels=CHANNELS,
                rate=SEND_SAMPLE_RATE,
                input=True,
                input_device_index=resolved_input_device_index,
                frames_per_buffer=CHUNK_SIZE,
            )
        except OSError as e:
            print(f"[AudioVideoIO] [ERR] Failed to open audio input stream: {e}")
            return

        while True:
            if self.paused:
                await asyncio.sleep(0.1)
                continue

            try:
                data = await asyncio.to_thread(self.audio_stream.read, CHUNK_SIZE, exception_on_overflow=False)

                # Deaf Mode: always drain the hardware buffer to prevent overflow,
                # but discard the chunk while SHARD is speaking (half-duplex gate).
                if self._ai_speaking:
                    continue

                await out_queue.put({"data": data, "mime_type": "audio/pcm"})

                # VAD integration
                vad_state = self.vad_logic.analyze_chunk(data)
                if vad_state == "SPEECH_START":
                    # Send a high-priority vision frame upon speech start
                    if self._latest_image_payload and self.out_queue:
                        await self.out_queue.put(self._latest_image_payload)
                        print(f"[AudioVideoIO] [VAD Trigger] Sent vision frame.")
                        
            except Exception as e:
                print(f"Error reading audio stream: {e}")
                await asyncio.sleep(0.1)
