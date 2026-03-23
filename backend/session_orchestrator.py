import asyncio
import uuid
import logging
import traceback
from google.genai import types
import time
import os

logger = logging.getLogger("shard.orchestrator")


class _ContextResetNeeded(Exception):
    """Raised proactively when the session turn count approaches context limits."""

# Import specific agents and managers required for orchestration
from cad_agent import CadAgent
from web_agent import WebAgent
from kasa_agent import KasaAgent
from printer_agent import PrinterAgent
from study_agent import StudyAgent
from project_manager import ProjectManager
from filesystem_tools import list_directory, read_file, write_file as fs_write_file, read_project_file

class SessionOrchestrator:
    """
    Pure orchestrator responsible for processing incoming session responses, 
    handling tool calls, managing permissions/confirmations, and dispatching 
    asynchronous agent tasks. Decoupled from direct audio/video handling.
    """
    def __init__(self, audio_video_io, memory, consciousness, tuning, project_manager, on_tool_confirmation=None, on_cad_data=None, on_cad_status=None, on_web_data=None, on_project_update=None, on_study_request=None, on_audio_response=None, on_transcription=None, study_agent=None):
        self.audio_video_io = audio_video_io
        self.memory = memory
        self.consciousness = consciousness
        self.tuning = tuning
        self.project_manager = project_manager
        self.on_tool_confirmation = on_tool_confirmation
        self.on_cad_data = on_cad_data
        self.on_cad_status = on_cad_status
        self.on_web_data = on_web_data
        self.on_project_update = on_project_update
        self.on_study_request = on_study_request
        self.on_audio_response = on_audio_response  # callable(bytes) — plays Gemini audio
        self.on_transcription = on_transcription    # callable({"sender", "text"}) → chat GUI

        self._pending_confirmations = {}
        self._turn_count = 0
        self._MAX_TURNS = 50   # reconnect proactively before Gemini 1011 overflow
        # Configuration based permissions
        self.permissions = {
            "list_directory": False,
            "read_file": False,
        }

        # Initialize dedicated agents (Decoupled from AudioLoop monolithic structure)
        self.cad_agent = CadAgent(on_thought=self._handle_cad_thought, on_status=self.on_cad_status)
        self.web_agent = WebAgent()
        self.kasa_agent = KasaAgent()
        self.printer_agent = PrinterAgent()
        if study_agent is not None:
            self.study_agent = study_agent
        else:
            self.study_agent = StudyAgent(goal_engine=getattr(consciousness, 'goal_engine', None))

    def _handle_cad_thought(self, thought_text):
        """Callback for CAD agent thoughts, relayed through orchestrator."""
        # This can be relayed or logged as required
        print(f"[Orchestrator] CAD Thought: {thought_text}")

    def resolve_tool_confirmation(self, request_id, confirmed):
        """Resolves pending user confirmation requests."""
        if request_id in self._pending_confirmations:
            future = self._pending_confirmations[request_id]
            if not future.done():
                future.set_result(confirmed)
            self._pending_confirmations.pop(request_id, None)

    async def _handle_transcription(self, response_server_content):
        """Processes input and output transcriptions for logging and state management."""
        # NOTE: This logic is tightly coupled with AudioVideoIO internal state (chat_buffer, _last_transcription)
        # To maintain separation, we must ensure AudioVideoIO handles its own buffering and flushing mechanism.
        # The Orchestrator's role here is primarily to ensure communication flow.
        
        # The previous monolithic structure mixed buffer management with session receipt.
        # In this refactored design, AudioVideoIO manages real-time streaming and transcription callbacks (`on_transcription`),
        # while Orchestrator focuses on tool execution triggered by the model's response structure.
        pass # Transcription handling responsibility remains primarily with AudioVideoIO callbacks

    async def receive_session_stream(self, session):
        """Main orchestration loop for receiving and processing model responses and tool calls."""
        self.audio_video_io.set_session(session)
        logger.info("[Orchestrator] Session stream started.")
        print(f"[Orchestrator DEBUG] Whitelisted tools (no confirmation): {[k for k, v in self.permissions.items() if v is False]}")

        self._turn_count = 0  # reset on each new session
        try:
            while True:
                # Proactive context reset — raised BEFORE the inner try so it
                # bypasses the "continue on error" handler and propagates to the
                # TaskGroup in shard.py, triggering a clean reconnect.
                if self._turn_count >= self._MAX_TURNS:
                    raise _ContextResetNeeded(
                        f"Proactive context reset after {self._turn_count} turns"
                    )

                try:
                    turn = session.receive()
                    async for response in turn:
                        # 1. Audio + text parts — parse model_turn.parts directly
                        # to avoid Gemini 2.5 SDK warnings about non-data/non-text parts.
                        sc = getattr(response, "server_content", None)
                        if sc is not None:
                            mt = getattr(sc, "model_turn", None)
                            if mt is not None:
                                for part in getattr(mt, "parts", []):
                                    # Audio (inline_data)
                                    inline = getattr(part, "inline_data", None)
                                    if inline is not None and self.on_audio_response:
                                        try:
                                            self.on_audio_response(inline.data)
                                        except Exception:
                                            pass
                                    # Text / thought — log only (transcription comes below)
                                    part_text = getattr(part, "text", None)
                                    if part_text:
                                        logger.debug(
                                            "[Orchestrator] Gemini text part: %.120s", part_text
                                        )

                            # 2. Transcriptions → chat GUI
                            if self.on_transcription:
                                out_tr = getattr(sc, "output_transcription", None)
                                if out_tr:
                                    text = getattr(out_tr, "text", None)
                                    if text:
                                        try:
                                            self.on_transcription({"sender": "SHARD", "text": text})
                                        except Exception:
                                            pass
                                in_tr = getattr(sc, "input_transcription", None)
                                if in_tr:
                                    text = getattr(in_tr, "text", None)
                                    if text:
                                        try:
                                            self.on_transcription({"sender": "User", "text": text})
                                        except Exception:
                                            pass

                        # 3. Tool calls
                        if response.tool_call:
                            function_responses = []
                            for fc in response.tool_call.function_calls:
                                await self._process_tool_call(fc, function_responses, session)

                            if function_responses:
                                await session.send_tool_response(
                                    function_responses=function_responses
                                )

                    self._turn_count += 1

                except asyncio.CancelledError:
                    logger.info("[Orchestrator] Session stream cancelled — shutting down cleanly.")
                    raise  # propagate so the task is properly marked cancelled

                except Exception as e:
                    # Connection-level errors mean the WebSocket is already dead.
                    # Re-raise immediately to trigger clean reconnect in shard.py —
                    # retrying on a broken connection only produces an infinite spam loop.
                    err_str = str(e).lower()
                    if any(kw in err_str for kw in ("1011", "1008", "connection closed", "connectionclosed")):
                        logger.warning(
                            "[Orchestrator] Connection-level error (%s) — escalating to reconnect.",
                            type(e).__name__,
                        )
                        raise

                    logger.error(
                        "[Orchestrator] ERROR in session stream — loop iteration failed.\n"
                        "Type   : %s\n"
                        "Message: %s\n"
                        "Traceback:\n%s",
                        type(e).__name__,
                        e,
                        traceback.format_exc(),
                    )
                    # Brief pause before retrying to avoid tight error loops
                    await asyncio.sleep(2)
                    logger.warning("[Orchestrator] Attempting to continue session stream after error...")

        except asyncio.CancelledError:
            pass  # already logged above
        except _ContextResetNeeded as e:
            logger.info(
                "[Orchestrator] %s — triggering clean reconnect.", e
            )
            raise  # propagates to TaskGroup → shard.py reconnect with backoff
        except Exception as e:
            # Unrecoverable error — outer loop cannot continue
            logger.critical(
                "[Orchestrator] FATAL: Session stream terminated by unrecoverable error.\n"
                "Type   : %s\n"
                "Message: %s\n"
                "Traceback:\n%s",
                type(e).__name__,
                e,
                traceback.format_exc(),
            )
            raise
        finally:
            logger.warning("[Orchestrator] Session receive loop has exited.")


    async def _process_tool_call(self, fc, function_responses, session):
        """Handles confirmation flow and dispatches specific tool execution tasks."""
        fc_name = fc.name
        fc_args = fc.args
        
        # Permission and Confirmation Logic
        CONFIRMATION_TIMEOUT = 60.0   # seconds — after this the tool call is auto-denied

        confirmation_required = self.permissions.get(fc_name, True)
        if confirmation_required and self.on_tool_confirmation:
            request_id = str(uuid.uuid4())
            logger.info("[Orchestrator] Requesting confirmation for '%s' (ID: %s)", fc_name, request_id)
            future = asyncio.Future()
            self._pending_confirmations[request_id] = future

            self.on_tool_confirmation({"id": request_id, "tool": fc_name, "args": fc_args})

            try:
                confirmed = await asyncio.wait_for(
                    asyncio.shield(future), timeout=CONFIRMATION_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[Orchestrator] Confirmation timeout (%.0fs) for '%s' (ID: %s) — auto-denying.",
                    CONFIRMATION_TIMEOUT, fc_name, request_id,
                )
                confirmed = False
            finally:
                # Always clean up — prevents the dict from growing indefinitely
                self._pending_confirmations.pop(request_id, None)
                if not future.done():
                    future.cancel()

            if not confirmed:
                logger.info("[Orchestrator] Tool call '%s' denied.", fc_name)
                function_responses.append(types.FunctionResponse(id=fc.id, name=fc_name, response={"result": "User denied."}))
                return

        # --- Task Dispatch (Decoupled execution handlers) ---
        print(f"[Orchestrator] Dispatching tool: '{fc_name}'")
        
        # Asynchronous executions run as separate tasks to maintain orchestration flow
        if fc_name in ["generate_cad", "iterate_cad"]:
            prompt = fc_args.get("prompt", "")
            asyncio.create_task(self._handle_cad_request(prompt, fc.id, session))
            # Non-blocking behavior, response sent upon completion via notification

        elif fc_name == "run_web_agent":
            prompt = fc_args.get("prompt", "")
            asyncio.create_task(self._handle_web_agent_request(prompt, fc.id, session, function_responses))
            # Immediate function response follows within _process_tool_call scope

        elif fc_name == "study_topic":
             topic = fc_args.get("topic", "")
             tier = fc_args.get("tier", 1)
             if self.on_study_request:
                 self.on_study_request(topic, tier)
             function_responses.append(types.FunctionResponse(id=fc.id, name=fc_name, response={"result": f"SHARD.STUDY initiated for '{topic}'."}))

        # Synchronous/Filesystem tools (can be handled directly or wrapped)
        elif fc_name == "list_directory":
            path = fc_args.get("path", ".")
            print(f"[Orchestrator DEBUG] list_directory called with path='{path}'")
            result = list_directory(path, str(self.project_manager.workspace_root))
            print(f"[Orchestrator DEBUG] list_directory result: {result[:200]}...")
            function_responses.append(types.FunctionResponse(id=fc.id, name=fc_name, response={"result": result}))
        
        elif fc_name == "read_file":
            filepath = fc_args.get("filepath", "")
            print(f"[Orchestrator DEBUG] read_file called with filepath='{filepath}'")
            result = read_file(filepath, str(self.project_manager.workspace_root))
            result = await self._summarize_for_voice(result, filepath)
            print(f"[Orchestrator DEBUG] read_file digest (len={len(result)}): {result[:200]}...")
            if self.consciousness:
                self.consciousness.push_event("file_read", {"file": filepath, "chars": len(result)})
            function_responses.append(types.FunctionResponse(id=fc.id, name=fc_name, response={"result": result}))

        elif fc_name == "read_project_file":
            filepath = fc_args.get("filepath", "")
            print(f"[Orchestrator DEBUG] read_project_file called with filepath='{filepath}'")
            try:
                result = read_project_file(filepath)
            except Exception as e:
                result = f"Error: {e}"
            result = await self._summarize_for_voice(result, filepath)
            print(f"[Orchestrator DEBUG] read_project_file digest (len={len(result)}): {result[:200]}...")
            if self.consciousness:
                self.consciousness.push_event("file_read", {"file": filepath, "chars": len(result)})
            function_responses.append(types.FunctionResponse(id=fc.id, name=fc_name, response={"result": result}))

        elif fc_name == "write_file":
            filepath = fc_args.get("filepath", "")
            content = fc_args.get("content", "")
            print(f"[Orchestrator DEBUG] write_file called with filepath='{filepath}'")
            
            from impact_analyzer import pre_check
            full_path = os.path.join(str(self.project_manager.workspace_root), filepath)
            check_result = await pre_check(full_path, content)
            
            if check_result["risk"] == "BLOCK":
                logger.error("[IMPACT] BLOCK %s — %s", filepath, check_result["reason"])
                function_responses.append(types.FunctionResponse(id=fc.id, name=fc_name, response={"result": f"ERROR: write_file blocked. Reason: {check_result['reason']}"}))
            else:
                if check_result["risk"] in ("HIGH", "MEDIUM"):
                    logger.warning("[IMPACT] %s %s — %s", check_result["risk"], filepath, check_result["reason"])
                
                result = fs_write_file(filepath, content, str(self.project_manager.workspace_root))
                print(f"[Orchestrator DEBUG] write_file result: {result[:200]}...")
                function_responses.append(types.FunctionResponse(id=fc.id, name=fc_name, response={"result": result}))

        # Project Management
        elif fc_name == "create_project":
            success, msg = self.project_manager.create_project(fc_args["name"])
            if success:
                self.project_manager.switch_project(fc_args["name"])
                if self.on_project_update: self.on_project_update(fc_args["name"])
            function_responses.append(types.FunctionResponse(id=fc.id, name=fc_name, response={"result": msg}))
        
        elif fc_name == "switch_project":
            success, msg = self.project_manager.switch_project(fc_args["name"])
            if success and self.on_project_update: self.on_project_update(fc_args["name"])
            function_responses.append(types.FunctionResponse(id=fc.id, name=fc_name, response={"result": msg}))

        # Placeholder for other tool handlers (kasa, printer, terminal...)

    # --- File summarization via Flash (keeps Native Audio context small) ---

    _SUMMARIZE_THRESHOLD = 600   # chars — below this, return raw content
    _SUMMARIZE_MAX_INPUT = 8000  # chars — cap input to Flash to avoid abuse

    async def _summarize_for_voice(self, content: str, filepath: str) -> str:
        """If content is long, delegate summarization to Gemini Flash so that
        only a compact digest enters the Native Audio context window."""
        if len(content) <= self._SUMMARIZE_THRESHOLD:
            return content

        try:
            from llm_router import llm_complete
            truncated = content[:self._SUMMARIZE_MAX_INPUT]
            prompt = (
                f"You are an assistant helping a voice AI understand a file. "
                f"Summarize the following file concisely (max 300 words): "
                f"what it does, key functions/classes/sections, important config or state.\n\n"
                f"File: {filepath}\n\n"
                f"Content:\n{truncated}"
            )
            summary = await llm_complete(prompt, max_tokens=512, temperature=0.2)
            logger.info(
                "[Orchestrator] File '%s' summarized for voice: %d → %d chars",
                filepath, len(content), len(summary),
            )
            return f"[Summary of {filepath}]\n{summary}"
        except Exception as e:
            logger.warning("[Orchestrator] Summarization failed (%s) — returning truncated raw.", e)
            return content[:self._SUMMARIZE_THRESHOLD]

    # --- Asynchronous Handlers (extracted from monolithic AudioLoop) ---

    async def _handle_cad_request(self, prompt, fc_id, session):
        # Logic extracted and refined from monolithic handle_cad_request, including auto-project logic
        print(f"[Orchestrator] Executing CAD task for prompt: '{prompt}'")
        if self.on_cad_status: self.on_cad_status("generating")

        # Simplified project context logic for refactor example
        cad_output_dir = str(self.project_manager.get_current_project_path() / "cad")
        cad_data = await self.cad_agent.generate_prototype(prompt, output_dir=cad_output_dir)
        
        if cad_data:
            if self.on_cad_data: self.on_cad_data(cad_data)
            self.project_manager.save_cad_artifact(cad_data.get('file_path', "output.stl"), prompt)
            completion_msg = "System Notification: CAD generation is complete."
            await session.send(input=types.LiveClientMessage(
                client_content=types.LiveClientContent(
                    turns=[types.Content(role="user", parts=[types.Part.from_text(text=completion_msg)])],
                    turn_complete=True
                )
            ))
        else:
            await session.send(input=types.LiveClientMessage(
                client_content=types.LiveClientContent(
                    turns=[types.Content(role="user", parts=[types.Part.from_text(text="System Notification: CAD generation failed.")])],
                    turn_complete=True
                )
            ))

    async def _handle_web_agent_request(self, prompt, fc_id, session, function_responses):
        print(f"[Orchestrator] Executing Web Agent task for prompt: '{prompt}'")
        
        async def update_frontend(image_b64, log_text):
            if self.on_web_data:
                 self.on_web_data({"image": image_b64, "log": log_text})
                 
        # Send immediate acknowledgement back to the model that task is starting (as in original monolith)
        function_responses.append(types.FunctionResponse(
            id=fc_id,
            name="run_web_agent",
            response={"result": "Web Navigation started."}
        ))
        
        result = await self.web_agent.run_task(prompt, update_callback=update_frontend)
        
        # Send final result as a separate system notification
        await session.send(input=types.LiveClientMessage(
            client_content=types.LiveClientContent(
                turns=[types.Content(role="user", parts=[types.Part.from_text(text=f"System Notification: Web Agent has finished.\nResult: {result}")])],
                turn_complete=True
            )
        ))
