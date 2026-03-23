"""Tests for shard.py — ShardCore structure, public API, and constants."""
import sys
import os
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, BACKEND_DIR)


def _make_shard_core():
    """Return a ShardCore instance with all heavy dependencies mocked."""
    mocks = {
        'pyaudio': MagicMock(),
        'memory': MagicMock(),
        'consciousness': MagicMock(),
        'self_tuning': MagicMock(),
        'session_orchestrator': MagicMock(),
        'audio_video_io': MagicMock(),
        'vad_logic': MagicMock(),
        'project_manager': MagicMock(),
    }
    mock_pyaudio_mod = MagicMock()
    mock_pyaudio_mod.PyAudio.return_value = MagicMock()
    mock_pyaudio_mod.paInt16 = 8

    mock_memory_cls = MagicMock(return_value=MagicMock())
    mock_consciousness_cls = MagicMock(return_value=MagicMock())
    mock_tuning_cls = MagicMock(return_value=MagicMock())
    mock_pm_cls = MagicMock(return_value=MagicMock())

    mock_avio = MagicMock()
    mock_avio_cls = MagicMock(return_value=mock_avio)

    mock_so = MagicMock()
    mock_so_cls = MagicMock(return_value=mock_so)

    with patch.dict(sys.modules, {
        'pyaudio': mock_pyaudio_mod,
        'backend.memory': MagicMock(ShardMemory=mock_memory_cls),
        'memory': MagicMock(ShardMemory=mock_memory_cls),
        'consciousness': MagicMock(ShardConsciousness=mock_consciousness_cls),
        'self_tuning': MagicMock(ShardSelfTuning=mock_tuning_cls),
        'backend.project_manager': MagicMock(ProjectManager=mock_pm_cls),
        'project_manager': MagicMock(ProjectManager=mock_pm_cls),
        'audio_video_io': MagicMock(AudioVideoIO=mock_avio_cls),
        'session_orchestrator': MagicMock(SessionOrchestrator=mock_so_cls),
        'vad_logic': MagicMock(VADLogic=MagicMock()),
    }):
        import importlib
        import shard as _shard_mod
        importlib.reload(_shard_mod)
        core = _shard_mod.ShardCore()
    return core, _shard_mod


# ── ShardCore structure ───────────────────────────────────────────────────────

class TestShardCoreImport(unittest.TestCase):

    def test_shardcore_class_importable(self):
        with patch.dict(sys.modules, {
            'pyaudio': MagicMock(paInt16=8, PyAudio=MagicMock()),
            'memory': MagicMock(ShardMemory=MagicMock(return_value=MagicMock())),
            'backend.memory': MagicMock(ShardMemory=MagicMock(return_value=MagicMock())),
            'consciousness': MagicMock(ShardConsciousness=MagicMock(return_value=MagicMock())),
            'self_tuning': MagicMock(ShardSelfTuning=MagicMock(return_value=MagicMock())),
            'project_manager': MagicMock(ProjectManager=MagicMock(return_value=MagicMock())),
            'backend.project_manager': MagicMock(ProjectManager=MagicMock(return_value=MagicMock())),
            'audio_video_io': MagicMock(AudioVideoIO=MagicMock(return_value=MagicMock())),
            'session_orchestrator': MagicMock(SessionOrchestrator=MagicMock(return_value=MagicMock())),
            'vad_logic': MagicMock(VADLogic=MagicMock()),
        }):
            import importlib
            import shard as _s
            importlib.reload(_s)
            self.assertTrue(hasattr(_s, 'ShardCore'))


class TestShardCorePublicMethods(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.core, cls.mod = _make_shard_core()

    def test_has_start_system(self):
        self.assertTrue(hasattr(self.core, 'start_system'))

    def test_has_stop(self):
        self.assertTrue(hasattr(self.core, 'stop'))

    def test_has_update_permissions(self):
        self.assertTrue(hasattr(self.core, 'update_permissions'))

    def test_update_permissions_is_callable(self):
        self.assertTrue(callable(self.core.update_permissions))

    def test_start_system_is_coroutine(self):
        import asyncio
        self.assertTrue(asyncio.iscoroutinefunction(self.core.start_system))

    def test_stop_is_coroutine(self):
        import asyncio
        self.assertTrue(asyncio.iscoroutinefunction(self.core.stop))


class TestShardCoreAttributes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.core, cls.mod = _make_shard_core()

    def test_has_memory(self):
        self.assertTrue(hasattr(self.core, 'memory'))

    def test_has_consciousness(self):
        self.assertTrue(hasattr(self.core, 'consciousness'))

    def test_has_session_orchestrator(self):
        self.assertTrue(hasattr(self.core, 'session_orchestrator'))

    def test_has_audio_video_io(self):
        self.assertTrue(hasattr(self.core, 'audio_video_io'))

    def test_has_ui_callbacks_dict(self):
        self.assertTrue(hasattr(self.core, 'ui_callbacks'))
        self.assertIsInstance(self.core.ui_callbacks, dict)

    def test_ui_callbacks_has_expected_keys(self):
        expected = {
            'on_transcription', 'on_tool_confirmation', 'on_cad_data',
            'on_cad_status', 'on_web_data', 'on_project_update', 'on_study_request',
        }
        self.assertTrue(expected.issubset(set(self.core.ui_callbacks.keys())))

    def test_stop_requested_initially_false(self):
        self.assertFalse(self.core._stop_requested)

    def test_reconnect_base_is_positive(self):
        self.assertGreater(self.core._RECONNECT_BASE, 0)

    def test_reconnect_max_greater_than_base(self):
        self.assertGreater(self.core._RECONNECT_MAX, self.core._RECONNECT_BASE)


class TestShardCoreConstants(unittest.TestCase):

    def test_model_is_gemini(self):
        with patch.dict(sys.modules, {
            'pyaudio': MagicMock(paInt16=8, PyAudio=MagicMock()),
            'memory': MagicMock(ShardMemory=MagicMock(return_value=MagicMock())),
            'backend.memory': MagicMock(ShardMemory=MagicMock(return_value=MagicMock())),
            'consciousness': MagicMock(ShardConsciousness=MagicMock(return_value=MagicMock())),
            'self_tuning': MagicMock(ShardSelfTuning=MagicMock(return_value=MagicMock())),
            'project_manager': MagicMock(ProjectManager=MagicMock(return_value=MagicMock())),
            'backend.project_manager': MagicMock(ProjectManager=MagicMock(return_value=MagicMock())),
            'audio_video_io': MagicMock(AudioVideoIO=MagicMock(return_value=MagicMock())),
            'session_orchestrator': MagicMock(SessionOrchestrator=MagicMock(return_value=MagicMock())),
            'vad_logic': MagicMock(VADLogic=MagicMock()),
        }):
            import importlib
            import shard as _s
            importlib.reload(_s)
            self.assertIn('gemini', _s.MODEL.lower())

    def test_audio_constants_are_positive(self):
        with patch.dict(sys.modules, {
            'pyaudio': MagicMock(paInt16=8, PyAudio=MagicMock()),
            'memory': MagicMock(ShardMemory=MagicMock(return_value=MagicMock())),
            'backend.memory': MagicMock(ShardMemory=MagicMock(return_value=MagicMock())),
            'consciousness': MagicMock(ShardConsciousness=MagicMock(return_value=MagicMock())),
            'self_tuning': MagicMock(ShardSelfTuning=MagicMock(return_value=MagicMock())),
            'project_manager': MagicMock(ProjectManager=MagicMock(return_value=MagicMock())),
            'backend.project_manager': MagicMock(ProjectManager=MagicMock(return_value=MagicMock())),
            'audio_video_io': MagicMock(AudioVideoIO=MagicMock(return_value=MagicMock())),
            'session_orchestrator': MagicMock(SessionOrchestrator=MagicMock(return_value=MagicMock())),
            'vad_logic': MagicMock(VADLogic=MagicMock()),
        }):
            import importlib
            import shard as _s
            importlib.reload(_s)
            self.assertGreater(_s.SEND_SAMPLE_RATE, 0)
            self.assertGreater(_s.RECEIVE_SAMPLE_RATE, 0)
            self.assertGreater(_s.CHUNK_SIZE, 0)
            self.assertEqual(_s.CHANNELS, 1)


if __name__ == '__main__':
    unittest.main()
