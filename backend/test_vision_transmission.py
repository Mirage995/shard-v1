import asyncio
import base64
import time
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock dependencies
sys.modules['pyaudio'] = MagicMock()
sys.modules['cv2'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['PIL.Image'] = MagicMock()
sys.modules['mss'] = MagicMock()
sys.modules['google'] = MagicMock()
sys.modules['google.genai'] = MagicMock()
sys.modules['cad_agent'] = MagicMock()
sys.modules['web_agent'] = MagicMock()
sys.modules['kasa_agent'] = MagicMock()
sys.modules['printer_agent'] = MagicMock()
sys.modules['project_manager'] = MagicMock()

# Avoid actual imports that might fail
with patch('google.genai.Client'), patch('google.genai.types.LiveConnectConfig'):
    from shard import AudioLoop

class TestVisionTransmission(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Initialize AudioLoop with minimal config
        self.loop = AudioLoop(video_mode="camera")
        self.loop.out_queue = asyncio.Queue()
        self.loop.session = MagicMock()
        # Mock session.send to be an async function
        self.loop.session.send = MagicMock(side_effect=lambda **kwargs: asyncio.sleep(0))
        self.loop._last_vision_frame_time = 0.0

    async def test_send_frame_throttling(self):
        """Verify that send_frame throttles frames correctly."""
        frame_data = b"fake_jpeg_data"
        
        # 1. First frame should go through
        await self.loop.send_frame(frame_data)
        self.assertEqual(self.loop.out_queue.qsize(), 1)
        item = await self.loop.out_queue.get()
        self.assertEqual(item["mime_type"], "image/jpeg")
        self.assertEqual(base64.b64decode(item["data"]), frame_data)
        
        # 2. Immediate second frame should be throttled (not put in queue)
        await self.loop.send_frame(frame_data)
        self.assertEqual(self.loop.out_queue.qsize(), 0)
        
        # 3. Wait for 1.6s (throttle is 1.5s)
        with patch('time.time', return_value=time.time() + 2.0):
            await self.loop.send_frame(frame_data)
            self.assertEqual(self.loop.out_queue.qsize(), 1)

    async def test_vad_frame_capture(self):
        """Verify that latest frame is stored for VAD usage."""
        frame_data = b"vad_frame"
        await self.loop.send_frame(frame_data)
        
        self.assertIsNotNone(self.loop._latest_image_payload)
        self.assertEqual(self.loop._latest_image_payload["mime_type"], "image/jpeg")
        self.assertEqual(base64.b64decode(self.loop._latest_image_payload["data"]), frame_data)

if __name__ == "__main__":
    unittest.main()
