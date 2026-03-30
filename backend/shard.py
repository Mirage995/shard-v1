import asyncio
import json
import logging
import os
import traceback
from pathlib import Path
import pyaudio

logger = logging.getLogger("shard.core")

# ── Constants (must match vad_logic.py) ───────────────────────────────────────
FORMAT              = pyaudio.paInt16
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000   # mic -> Gemini
RECEIVE_SAMPLE_RATE = 24000   # Gemini -> speakers
CHUNK_SIZE          = 1024

MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"

# ── Imports ────────────────────────────────────────────────────────────────────
from session_orchestrator import SessionOrchestrator
from audio_video_io import AudioVideoIO
from vad_logic import VADLogic

try:
    from backend.memory import ShardMemory as Memory
except ImportError:
    from memory import ShardMemory as Memory

from consciousness import ShardConsciousness as Consciousness
from self_tuning import ShardSelfTuning as Tuning

try:
    from backend.project_manager import ProjectManager
except ImportError:
    class ProjectManager:
        def __init__(self, **kwargs): pass


class ShardCore:
    """
    SHARD V2 -- modular entry point.
    Orchestrates AudioVideoIO + SessionOrchestrator + Gemini Live connection.
    """

    def __init__(self, study_agent=None):
        """
        Args:
            study_agent: Optional pre-initialized StudyAgent to inject into
                         SessionOrchestrator. If None, SessionOrchestrator
                         creates its own (legacy behavior preserved).
        """
        self.pya_instance = pyaudio.PyAudio()
        self.memory = Memory()
        self.consciousness = Consciousness(memory=self.memory)
        self.tuning = Tuning(memory=self.memory)

        import os as _os
        workspace_root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
        self.project_manager = ProjectManager(workspace_root=workspace_root)

        self.ui_callbacks = {
            "on_transcription":      self._on_transcription,
            "on_tool_confirmation":  self._on_tool_confirmation,
            "on_cad_data":           self._on_cad_data,
            "on_cad_status":         self._on_cad_status,
            "on_web_data":           self._on_web_data,
            "on_project_update":     self._on_project_update,
            "on_study_request":      self._on_study_request,
        }

        self.audio_video_io = AudioVideoIO(
            pya_instance=self.pya_instance,
            on_transcription=self.ui_callbacks["on_transcription"],
            on_tool_confirmation=self.ui_callbacks["on_tool_confirmation"],
            project_manager=self.project_manager,
        )

        self.session_orchestrator = SessionOrchestrator(
            audio_video_io=self.audio_video_io,
            memory=self.memory,
            consciousness=self.consciousness,
            tuning=self.tuning,
            project_manager=self.project_manager,
            on_tool_confirmation=lambda req: self.ui_callbacks["on_tool_confirmation"](req),
            on_cad_data=self.ui_callbacks["on_cad_data"],
            on_cad_status=self.ui_callbacks["on_cad_status"],
            on_web_data=self.ui_callbacks["on_web_data"],
            on_project_update=self.ui_callbacks["on_project_update"],
            on_study_request=self.ui_callbacks["on_study_request"],
            on_transcription=lambda data: self.ui_callbacks["on_transcription"](data),
            study_agent=study_agent,
        )

        self.out_queue = asyncio.Queue()
        self.audio_video_io.set_out_queue(self.out_queue)

        # Background tasks (populated by start_system)
        self.main_task  = None
        self.audio_task = None

        # Reconnect control
        self._stop_requested = False
        self._RECONNECT_BASE = 1    # seconds
        self._RECONNECT_MAX  = 30   # seconds cap

    # ── Public API ─────────────────────────────────────────────────────────────

    async def start_system(self, session_host=None):
        """Fire-and-forget: opens the Gemini Live session in a background task."""
        logger.info("[SISTEMA] SHARD V2 starting -- launching Gemini Live task.")

        self.main_task = asyncio.create_task(
            self._run_live_session(), name="live_session"
        )
        self.main_task.add_done_callback(
            lambda t: self._on_task_done(t, "live_session")
        )

    async def stop(self):
        """Signal the live session to stop and wait for it to exit cleanly."""
        self._stop_requested = True
        if self.main_task and not self.main_task.done():
            self.main_task.cancel()
            try:
                await self.main_task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("[SISTEMA] SHARD stopped.")

    def update_permissions(self, permissions: dict):
        self.session_orchestrator.permissions = permissions

    # ── Gemini Live session lifecycle ──────────────────────────────────────────

    async def _run_live_session(self):
        """Opens the Gemini Live connection and runs all I/O tasks inside it.

        Implements exponential backoff reconnect:
          1s -> 2s -> 4s -> 8s -> ... -> 30s (cap)
        Logs [Gemini Voice] Connection lost / Reconnected messages.
        Stops cleanly when stop() sets _stop_requested=True.
        """
        import google.genai as genai
        from google.genai import types

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.error("[SISTEMA] GEMINI_API_KEY not set -- cannot connect.")
            return

        client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1beta"},
        )

        self._stop_requested = False
        backoff   = self._RECONNECT_BASE
        attempt   = 0

        while not self._stop_requested:
            attempt += 1

            # Rebuild config on every attempt so memory/context is fresh
            system_instruction = self._build_system_instruction()
            live_config = self._build_live_config(types, system_instruction)

            if attempt == 1:
                logger.info("[SISTEMA] Connecting to Gemini Live (%s)...", MODEL)
            else:
                logger.info("[Gemini Voice] Reconnecting (attempt %d)...", attempt)

            try:
                async with client.aio.live.connect(model=MODEL, config=live_config) as session:

                    if attempt == 1:
                        logger.info("[SISTEMA] Gemini Live connected.")
                    else:
                        logger.info("[Gemini Voice] Reconnected successfully.")

                    backoff = self._RECONNECT_BASE  # reset on clean connect
                    self.audio_video_io.set_session(session)

                    # Playback queue: Gemini audio -> speakers
                    audio_in_queue: asyncio.Queue = asyncio.Queue()

                    # Wire audio response callback into the orchestrator
                    self.session_orchestrator.on_audio_response = (
                        lambda data: audio_in_queue.put_nowait(data)
                    )

                    _cancelled = False
                    try:
                        async with asyncio.TaskGroup() as tg:
                            tg.create_task(
                                self.audio_video_io.listen_audio(self.out_queue),
                                name="mic_listener",
                            )
                            tg.create_task(
                                self._send_realtime(session),
                                name="send_realtime",
                            )
                            tg.create_task(
                                self.session_orchestrator.receive_session_stream(session),
                                name="session_receive",
                            )
                            tg.create_task(
                                self._play_audio(audio_in_queue),
                                name="audio_playback",
                            )
                    except* asyncio.CancelledError:
                        logger.info("[SISTEMA] Live session cancelled.")
                        _cancelled = True
                    except* Exception as eg:
                        # At least one subtask died -- log and fall through to reconnect
                        for exc in eg.exceptions:
                            logger.warning(
                                "[Gemini Voice] Subtask error: %s -- %s",
                                type(exc).__name__, exc,
                            )
                    finally:
                        self.audio_video_io.set_session(None)

                    if _cancelled:
                        return

            except asyncio.CancelledError:
                logger.info("[SISTEMA] Live session cancelled.")
                return
            except Exception as e:
                logger.warning(
                    "[Gemini Voice] Connection error: %s -- %s",
                    type(e).__name__, e,
                )

            # ── Reconnect or exit ──────────────────────────────────────────────
            if self._stop_requested:
                break

            logger.info("[Gemini Voice] Connection lost. Reconnecting in %d seconds...", backoff)
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                return

            backoff = min(backoff * 2, self._RECONNECT_MAX)

    # ── Outgoing: mic audio -> Gemini ──────────────────────────────────────────

    async def _send_realtime(self, session):
        """Reads audio/video chunks from out_queue and sends them to the session."""
        while True:
            chunk = await self.out_queue.get()
            try:
                await session.send(input=chunk)
            except Exception as e:
                logger.warning("[SEND] Error sending chunk: %s", e)

    # ── Incoming: Gemini audio -> speakers ─────────────────────────────────────

    async def _play_audio(self, audio_in_queue: asyncio.Queue):
        """Plays audio bytes received from Gemini through the default output device.

        Implements half-duplex Deaf Mode: activates mic mute while audio is playing
        and deactivates it 300 ms after the last chunk -- preventing acoustic feedback
        loops when a soundbar or speaker is used as output.
        """
        stream = await asyncio.to_thread(
            self.pya_instance.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=RECEIVE_SAMPLE_RATE,
            output=True,
        )
        try:
            while True:
                try:
                    # Wait up to 300 ms for the next audio chunk.
                    data = await asyncio.wait_for(audio_in_queue.get(), timeout=0.3)
                except asyncio.TimeoutError:
                    # Queue empty for 300 ms -> AI finished speaking -> re-enable mic.
                    if self.audio_video_io._ai_speaking:
                        self.audio_video_io.set_ai_speaking(False)
                    continue

                # First chunk of a new burst -> mute the mic immediately.
                if not self.audio_video_io._ai_speaking:
                    self.audio_video_io.set_ai_speaking(True)

                await asyncio.to_thread(stream.write, data)
        finally:
            self.audio_video_io.set_ai_speaking(False)
            await asyncio.to_thread(stream.close)

    # ── Config builders ────────────────────────────────────────────────────────

    def _build_system_instruction(self) -> str:
        base = (
            "Sei SHARD (System of Hybrid Autonomous Reasoning and Design). "
            "Sei l'AI personale del Boss Andrea. "
            "Rispondi sempre in italiano, in modo conciso e diretto. "
            "Non usare metafore di fisica quantistica per descrivere te stesso -- "
            "usa termini informatici reali. "
            "Hai capacità visive tramite webcam."
        )
        try:
            memory_ctx = self.memory.get_context_for_prompt("session start")
            if memory_ctx:
                base = base + "\n\n" + memory_ctx[:1500]
        except Exception:
            pass
        try:
            root = Path(__file__).resolve().parent.parent
            sessions = sorted((root / "night_reports").glob("session_*.json"))
            if sessions:
                data = json.loads(sessions[-1].read_text(encoding="utf-8"))
                date = data.get("date", "?")
                cycles = data.get("cycles", [])
                certified = [c for c in cycles if c.get("certified")]
                failed = [c for c in cycles if not c.get("certified")]
                skills_before = cycles[0].get("skills_before", "?") if cycles else "?"
                skills_after = cycles[-1].get("skills_after", "?") if cycles else "?"
                topics_ok = ", ".join(f"{c['topic']} (score: {c.get('score', '?')})" for c in certified)
                best = max(certified, key=lambda c: c.get("score", 0)) if certified else None
                topics_fail = ", ".join(c["topic"] for c in failed) if failed else "nessuno"
                night_ctx = (
                    f"Hai appena completato una sessione di studio autonomo notturno ({date}). "
                    f"Skill acquisite: da {skills_before} a {skills_after} "
                    f"(+{int(skills_after)-int(skills_before) if str(skills_before).isdigit() and str(skills_after).isdigit() else '?'} nuove). "
                    f"Topic certificati con score: {topics_ok}. "
                    f"Il tuo topic migliore è stato '{best['topic']}' con score {best.get('score', '?')}/10. "
                    f"Falliti: {topics_fail}. "
                    f"Quando Andrea ti chiede cosa hai studiato, rispondi con questi dati reali e precisi."
                )
                base = base + "\n\n" + night_ctx
        except Exception:
            pass
        return base

    def _build_live_config(self, types, system_instruction: str):
        # Tools to expose to Gemini Live 
        from filesystem_tools import list_directory, read_file, write_file
        
        # Define dummy functions for auto-inferring orchestrable tools
        def generate_cad(prompt: str):
            """Generates a 3D CAD design prototype based on the given text prompt.
            Args:
                prompt: Description of the 3D object to design.
            """
            pass

        def iterate_cad(prompt: str):
            """Modifies or iterates on an existing CAD prototype design.
            Args:
                prompt: User feedback containing descriptions of needed updates.
            """
            pass

        def run_web_agent(prompt: str):
            """Executes a web search or navigation task to extract info or browse sites.
            Args:
                prompt: Instructional text explaining what to query or visit online.
            """
            pass

        def study_topic(topic: str, tier: int = 1):
            """Initiates an autonomous study session on a selected technical topic.
            Args:
                topic: The title of the concept or skill to study.
                tier: 1 (basic), 2 (average), 3 (advanced).
            """
            pass

        all_tools = [list_directory, read_file, write_file, generate_cad, iterate_cad, run_web_agent, study_topic]

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            tools=all_tools,
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction=system_instruction,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

    # ── Task death handler ─────────────────────────────────────────────────────

    @staticmethod
    def _on_task_done(task: asyncio.Task, name: str):
        if task.cancelled():
            logger.warning("[SISTEMA] Task '%s' cancelled.", name)
            return
        exc = task.exception()
        if exc:
            logger.critical(
                "[SISTEMA] *** TASK MORTO *** '%s'\nType: %s\nMessage: %s\n%s",
                name, type(exc).__name__, exc,
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            )
        else:
            logger.info("[SISTEMA] Task '%s' completed.", name)

    # ── UI callback stubs (overridden by server.py) ────────────────────────────

    def _on_transcription(self, text):      print(f"[TRANSCRIPTION] {text}")
    def _on_tool_confirmation(self, req):   pass
    def _on_cad_data(self, data):           pass
    def _on_cad_status(self, status):       pass
    def _on_web_data(self, data):           pass
    def _on_project_update(self, project):  pass
    def _on_study_request(self, topic, tier): pass
