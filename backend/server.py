import sys
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("shard.server")

# Il trucco definitivo per l'inferno dei path di Node/Electron
# Calcoliamo i path assoluti in modo dinamico
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))  # cartella shard_v1/backend/
ROOT_DIR = os.path.dirname(BACKEND_DIR)                   # cartella shard_v1/

# Iniettiamo entrambi i path nel radar di Python
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import asyncio

# Fix for asyncio subprocess support on Windows
# MUST BE SET BEFORE OTHER IMPORTS
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import socketio
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import threading
import json
from datetime import datetime
from pathlib import Path



import shard
from authenticator import FaceAuthenticator
from kasa_agent import KasaAgent
from study_agent import StudyAgent
from goal_storage import GoalStorage
from goal_engine import GoalEngine
from swe_agent import SWEAgent
from shard_semaphore import (
    SHARD_SESSION_LOCK,
    acquire_file_lock, release_file_lock, is_file_locked, get_lock_reason,
)

# Deferred initialization — populated in startup_event() to avoid double
# instantiation (global scope runs at import time, before FastAPI startup).
storage: "GoalStorage" = None
goal_engine: "GoalEngine" = None
study_agent: "StudyAgent" = None

# Create a Socket.IO server
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app_socketio = socketio.ASGIApp(sio, app)

import signal

# --- SHUTDOWN HANDLER ---
def signal_handler(sig, frame):
    print(f"\n[SERVER] Caught signal {sig}. Exiting gracefully...")
    # Clean up audio loop
    if audio_loop:
        try:
            print("[SERVER] Stopping Audio Loop...")
            audio_loop.stop() 
        except:
            pass
    # Force kill
    print("[SERVER] Force exiting...")
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Global state
audio_loop = None
loop_task = None
audio_fe_task = None   # background worker that drains the frontend audio queue
authenticator = None
_shard_core = None     # active ShardCore instance (replaces audio_loop for new system)

# ── Session Authentication ─────────────────────────────────────────────────────
# Tracks Socket.IO session IDs that have passed authentication.
# Populated in connect() when face-auth passes or is disabled (auto-auth).
# Cleaned in disconnect().
_authenticated_sids: set[str] = set()
_session_lock_held: bool = False   # True while start_audio holds SHARD_SESSION_LOCK

def _is_authenticated(sid: str) -> bool:
    return sid in _authenticated_sids

async def _require_auth(sid: str, event: str) -> bool:
    """Guard for sensitive Socket.IO events.

    Returns True if the caller is authenticated.
    Emits an error event to the caller and returns False otherwise.
    """
    if not _is_authenticated(sid):
        logger.warning(
            "[AUTH] Unauthorized access: event='%s' sid=%s — rejecting.", event, sid
        )
        await sio.emit(
            "error",
            {"msg": f"Unauthorized: authentication required for '{event}'"},
            to=sid,
        )
        return False
    return True

# ── Settings Schema Validation ────────────────────────────────────────────────
# Whitelist of top-level keys and their expected types.
_ALLOWED_SETTINGS_KEYS: frozenset[str] = frozenset({
    "tool_permissions", "face_auth_enabled", "camera_flipped", "printers",
})
_KNOWN_TOOL_PERMISSIONS: frozenset[str] = frozenset({
    "generate_cad", "iterate_cad", "run_web_agent", "study_topic",
    "list_directory", "read_file", "write_file",
    "create_project", "switch_project",
    "control_kasa", "print_file",
})

def _validate_settings_payload(data: dict) -> tuple[bool, str]:
    """Validate an update_settings / update_tool_permissions payload.

    Returns (True, "") if valid, (False, reason) if rejected.
    """
    if not isinstance(data, dict):
        return False, "Payload must be a JSON object."
    for key in data:
        if key not in _ALLOWED_SETTINGS_KEYS:
            return False, f"Unknown settings key: '{key}' — rejected."
    if "tool_permissions" in data:
        perms = data["tool_permissions"]
        if not isinstance(perms, dict):
            return False, "'tool_permissions' must be a JSON object."
        for k, v in perms.items():
            if k not in _KNOWN_TOOL_PERMISSIONS:
                return False, f"Unknown tool permission: '{k}'."
            if not isinstance(v, bool):
                return False, f"Permission value for '{k}' must be boolean, got {type(v).__name__}."
    for bool_key in ("face_auth_enabled", "camera_flipped"):
        if bool_key in data and not isinstance(data[bool_key], bool):
            return False, f"'{bool_key}' must be boolean."
    return True, ""
SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "face_auth_enabled": False, # Default OFF as requested
    "tool_permissions": {
        "generate_cad": True,
        "run_web_agent": True,
        "write_file": True,
        "list_directory": False,
        "read_file": False,
        "create_project": True,
        "switch_project": True,
        "list_projects": True
    },
    "printers": [], # List of {host, port, name, type}
    "kasa_devices": [], # List of {ip, alias, model}
    "camera_flipped": False # Invert cursor horizontal direction
}

SETTINGS = DEFAULT_SETTINGS.copy()

def load_settings():
    global SETTINGS
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
                # Merge with defaults to ensure new keys exist
                # Deep merge for tool_permissions would be better but shallow merge of top keys + tool_permissions check is okay for now
                for k, v in loaded.items():
                    if k == "tool_permissions" and isinstance(v, dict):
                         SETTINGS["tool_permissions"].update(v)
                    else:
                        SETTINGS[k] = v
            print(f"Loaded settings: {SETTINGS}")
        except Exception as e:
            print(f"Error loading settings: {e}")

def save_settings():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(SETTINGS, f, indent=4)
        print("Settings saved.")
    except Exception as e:
        print(f"Error saving settings: {e}")

# Load on startup
load_settings()

authenticator = None
kasa_agent = KasaAgent(known_devices=SETTINGS.get("kasa_devices"))
# tool_permissions is now SETTINGS["tool_permissions"]

@app.on_event("startup")
async def startup_event():
    global storage, goal_engine, study_agent
    import sys
    print(f"[SERVER DEBUG] Startup Event Triggered")
    print(f"[SERVER DEBUG] Python Version: {sys.version}")
    try:
        loop = asyncio.get_running_loop()
        print(f"[SERVER DEBUG] Running Loop: {type(loop)}")
        policy = asyncio.get_event_loop_policy()
        print(f"[SERVER DEBUG] Current Policy: {type(policy)}")
    except Exception as e:
        print(f"[SERVER DEBUG] Error checking loop: {e}")

    # ── Lazy init: one instantiation, exactly here, after FastAPI is live ──
    print("[SERVER] Startup: Initializing GoalStorage, GoalEngine, StudyAgent...")
    storage = GoalStorage()
    goal_engine = GoalEngine(storage)
    study_agent = StudyAgent(goal_engine=goal_engine)
    print("[SERVER] Startup: Agents ready.")

    print("[SERVER] Startup: Initializing Kasa Agent...")
    await kasa_agent.initialize()

@app.get("/status")
async def status():
    return {"status": "running", "service": "SHARD Backend"}

class SWERequest(BaseModel):
    repo_name: str
    base_commit: str
    issue_text: str

@app.post("/api/run-swe-task")
async def run_swe_task(payload: SWERequest):
    agent = SWEAgent()
    result = await agent.run_task(
        repo_name=payload.repo_name,
        base_commit=payload.base_commit,
        issue_text=payload.issue_text
    )
    return {
        "status": "success",
        "result": result
    }

@app.get("/api/knowledge/query")
async def query_knowledge(topic: str, n: int = 3):
    """Query NightRunner's ChromaDB knowledge base (Debug/Inspection)."""
    from knowledge_bridge import query_knowledge_base
    result = query_knowledge_base(topic, n_results=n)
    return {"topic": topic, "result": result}


@app.get("/api/cognition_state")
async def cognition_state():
    """CognitionCore pulse — the living state of SHARD's Senso Interno.

    Returns:
        executive:      Layer 0+1 snapshot (ground truth + summary)
        mood:           SHARD's current cognitive mood derived from metrics
        active_tensions: which emergence vectors are pushing right now
        shadow_audit:   last 5 emergence audit entries (HITS and MISSES)
        emergence_stats: session-level emergence metrics
        identity:       Layer 2 — capability gaps and certification rate
        top_gaps:       top 3 critical capability gaps
    """
    core = getattr(study_agent, "cognition_core", None)

    if core is None:
        return {
            "status": "unavailable",
            "reason": "CognitionCore not initialized — study_agent may still be starting",
        }

    # ── Layer 0+1: Executive ────────────────────────────────────────────────
    exec_data = core.executive()
    anchor    = exec_data["anchor"]
    summary   = exec_data["summary"]

    # ── Layer 2: Identity ───────────────────────────────────────────────────
    identity = core.query_identity()

    # ── Mood derivation ──────────────────────────────────────────────────────
    # Mood is a human-readable signal for the dashboard, derived from Layer 0+2.
    # It summarizes SHARD's cognitive posture in one word.
    cert_rate    = anchor.get("certification_rate", 0.0)
    avg_score    = anchor.get("avg_score", 0.0)
    gap_severity = identity.get("gap_severity", "none") if "error" not in identity else "none"

    if cert_rate >= 0.65 and avg_score >= 7.0:
        mood = "Confident"
        mood_reason = f"cert_rate={cert_rate:.0%}, avg_score={avg_score}"
    elif gap_severity == "critical" or cert_rate < 0.25:
        mood = "Struggling"
        mood_reason = f"gap_severity={gap_severity}, cert_rate={cert_rate:.0%}"
    elif gap_severity == "medium" and cert_rate < 0.45:
        mood = "Skeptical"
        mood_reason = f"Identity weak in critical categories (gap_severity={gap_severity})"
    elif avg_score >= 5.0:
        mood = "Focused"
        mood_reason = f"cert_rate={cert_rate:.0%}, avg_score={avg_score}"
    else:
        mood = "Frustrated"
        mood_reason = f"Low avg_score={avg_score}, cert_rate={cert_rate:.0%}"

    # ── Active tensions (which emergence vectors are firing right now) ───────
    # We detect tensions from the last relational_context computed — or compute fresh
    # from identity + experience on the last studied topic.
    active_tensions = []
    last_topic = anchor.get("last_topic", "")
    if last_topic and last_topic != "—":
        try:
            exp  = core.query_experience(last_topic)
            know = core.query_knowledge(last_topic)
            from cognition.cognition_core import _detect_tensions
            raw_tensions = _detect_tensions(identity if "error" not in identity else {}, exp, know, anchor)
            active_tensions = [t[:120] for t in raw_tensions[:3]]  # max 3, truncated for UI
        except Exception:
            pass

    # ── Shadow Audit: last 5 emergence events ───────────────────────────────
    log = core.get_emergence_log(last_n=5)
    shadow_audit = [
        {
            "timestamp": e.get("timestamp", "")[:19],
            "topic":     e.get("topic", ""),
            "action":    e.get("action", ""),
            "result":    e.get("result", ""),
            "cause":     e.get("cause", ""),
        }
        for e in log
    ]

    # ── Emergence stats ──────────────────────────────────────────────────────
    stats = core.get_emergence_stats()
    emergence_stats = {
        "opportunities":   stats.get("opportunities", 0),
        "hits":            stats.get("hits", 0),
        "misses":          stats.get("misses", 0),
        "emergence_rate":  stats.get("emergence_rate", 0.0),
        "miss_causes":     stats.get("miss_causes", {}),
    }

    # ── Top 3 capability gaps ────────────────────────────────────────────────
    top_gaps = []
    if "error" not in identity:
        top_gaps = identity.get("critical_gaps", [])[:3]

    return {
        "status": "ok",
        "mood":   mood,
        "mood_reason": mood_reason,
        "executive": {
            "summary":            summary,
            "certification_rate": anchor.get("certification_rate", 0.0),
            "total_experiments":  anchor.get("total_experiments", 0),
            "avg_score":          anchor.get("avg_score", 0.0),
            "last_topic":         anchor.get("last_topic", "—"),
            "last_pass":          anchor.get("last_pass", False),
            "last_date":          anchor.get("last_date", "—"),
        },
        "active_tensions": active_tensions,
        "active_vectors":  _describe_active_vectors(active_tensions),
        "shadow_audit":    shadow_audit,
        "emergence_stats": emergence_stats,
        "identity": {
            "gap_severity":    identity.get("gap_severity", "none") if "error" not in identity else "n/a",
            "gap_rate":        identity.get("gap_rate", 0.0)        if "error" not in identity else 0.0,
            "frontier_topics": identity.get("frontier_topics", [])  if "error" not in identity else [],
        },
        "top_gaps": top_gaps,
    }


def _describe_active_vectors(tensions: list) -> list:
    """Map active tension strings to their vector labels for the UI."""
    labels = []
    for t in tensions:
        if "Vettore 1" in t or "sandbox" in t.lower():
            labels.append("V1: Intuizione del Fallimento (Experience→Synthesis)")
        elif "Vettore 2" in t or "Identit" in t:
            labels.append("V2: Scettico Informato (Identity→Critique)")
        elif "Vettore 3" in t or "complessit" in t.lower():
            labels.append("V3: Strategia Predittiva (Knowledge→Strategy)")
        elif "Near-miss" in t:
            labels.append("Near-miss: piccolo aggiustamento può sbloccare")
        elif "gap" in t.lower():
            labels.append("Performance gap: topic sistematicamente difficile")
    return labels


# --- Goal Engine Endpoints ------------------------------------------------
@app.get("/goals")
async def list_goals():
    """Return all known goals."""
    return [g.dict() for g in goal_engine.list_goals()]

@app.post("/goals")
async def create_goal(payload: dict):
    """Create a new goal. Expects title, optional description, priority,
    goal_type and prerequisites list."""
    title = payload.get("title")
    if not title:
        return {"error": "title required"}
    g = goal_engine.create_goal(
        title=title,
        description=payload.get("description", ""),
        priority=float(payload.get("priority", 0.0)),
        goal_type=payload.get("goal_type", "general"),
        prerequisites=payload.get("prerequisites", []),
    )
    return g.dict()

@sio.event
async def list_goals_io(sid):
    await sio.emit("goals_list", {"goals": [g.dict() for g in goal_engine.list_goals()]}, room=sid)

@sio.event
async def create_goal_io(sid, data):
    g = goal_engine.create_goal(
        title=data.get("title"),
        description=data.get("description", ""),
        priority=data.get("priority", 0.0),
        goal_type=data.get("goal_type", "general"),
        prerequisites=data.get("prerequisites", []),
    )
    await sio.emit("goal_created", {"goal": g.dict()}, room=sid)

@sio.event
async def activate_goal(sid, data):
    goal_id = data.get("id")
    g = goal_engine.set_active_goal(goal_id)
    if g:
        await sio.emit("goal_activated", {"goal": g.dict()}, room=sid)

heartbeat_started = False

@sio.event
async def connect(sid, environ):
    global heartbeat_started, authenticator
    print(f"[SERVER] Client connected: {sid}")
    await sio.emit('status', {'msg': 'Connected to SHARD Backend'}, room=sid)

    # --- Authentication Logic ---
    # Callbacks need access to sid via closure
    async def on_auth_status(is_auth: bool):
        logger.info("[AUTH] Status change for sid=%s: authenticated=%s", sid, is_auth)
        if is_auth:
            _authenticated_sids.add(sid)
        else:
            _authenticated_sids.discard(sid)
        await sio.emit('auth_status', {'authenticated': is_auth}, to=sid)

    async def on_auth_frame(frame_b64):
        await sio.emit('auth_frame', {'image': frame_b64}, to=sid)

    # Reinitialize authenticator with updated callbacks
    if authenticator is None:
        authenticator = FaceAuthenticator(
            reference_image_path="reference.jpg",
            on_status_change=on_auth_status,
            on_frame=on_auth_frame
        )

    # Authenticate or bypass
    if authenticator.authenticated:
        _authenticated_sids.add(sid)
        await sio.emit('auth_status', {'authenticated': True}, to=sid)
    else:
        if SETTINGS.get("face_auth_enabled", False):
            await sio.emit('auth_status', {'authenticated': False}, to=sid)
            asyncio.create_task(authenticator.start_authentication_loop())
        else:
            logger.info("[AUTH] Face auth disabled — auto-authenticating sid=%s.", sid)
            _authenticated_sids.add(sid)
            await sio.emit('auth_status', {'authenticated': True}, to=sid)

    # --- Evolution Heartbeat + Voice Queue Poller ---
    if not heartbeat_started:
        print("[SERVER] Avvio del motore evolutivo di SHARD...")
        asyncio.create_task(shard_evolution_heartbeat())
        asyncio.create_task(_voice_queue_poller())
        heartbeat_started = True

    # --- Consciousness Auto-Start ---
    async def accendi_coscienza_quando_pronto():
        STARTUP_TIMEOUT = 30  # secondi
        elapsed = 0
        while True:
            if elapsed >= STARTUP_TIMEOUT:
                logger.error(
                    "[SERVER] TIMEOUT STARTUP: SHARD non ha inizializzato 'consciousness' "
                    "entro %d secondi. Il sistema è bloccato — verifica i log di ShardCore.",
                    STARTUP_TIMEOUT,
                )
                return
            # Support both legacy audio_loop and new shard_core
            core = _shard_core if _shard_core is not None else audio_loop
            if core is not None and hasattr(core, 'consciousness'):
                break
            await asyncio.sleep(1)
            elapsed += 1
        logger.info("[SERVER] Sistema neurale pronto! Accensione monologo interiore di SHARD...")
        asyncio.create_task(core.consciousness.inner_monologue_loop())
        logger.info("[SHARD] Consciousness loop avviato in background")

    asyncio.create_task(accendi_coscienza_quando_pronto())


@sio.event
async def disconnect(sid):
    global _session_lock_held
    _authenticated_sids.discard(sid)
    logger.info("[SERVER] Client disconnected: sid=%s (authenticated_sids remaining: %d)", sid, len(_authenticated_sids))
    # If the client disconnected without calling stop_audio, release the stale lock.
    if _session_lock_held:
        try:
            SHARD_SESSION_LOCK.release()
            release_file_lock()
            _session_lock_held = False
            logger.info("[SESSION LOCK] Released by disconnect (stale audio lock cleaned up).")
        except Exception as _lock_err:
            logger.warning("[SESSION LOCK] Failed to release on disconnect: %s", _lock_err)

@sio.event
async def start_audio(session_host, data=None):
    global audio_loop, loop_task, audio_fe_task, _shard_core
    
    # Optional: Block if not authenticated
    # Only block if auth is ENABLED and not authenticated
    if SETTINGS.get("face_auth_enabled", False):
        if authenticator and not authenticator.authenticated:
            print("Blocked start_audio: Not authenticated.")
            await sio.emit('error', {'msg': 'Authentication Required'})
            return

    print("Starting Audio Loop...")
    
    device_index = None
    device_name = None
    if data:
        if 'device_index' in data:
            device_index = data['device_index']
        if 'device_name' in data:
            device_name = data['device_name']
            
    print(f"Using input device: Name='{device_name}', Index={device_index}")
    
    if audio_loop:
        if loop_task and (loop_task.done() or loop_task.cancelled()):
             print("Audio loop task appeared finished/cancelled. Clearing and restarting...")
             audio_loop = None
             loop_task = None
        else:
             print("Audio loop already running. Re-connecting client to session.")
             await sio.emit('status', {'msg': 'SHARD Already Running'})
             return


    # ── SESSION LOCK ────────────────────────────────────────────────────────────
    # Prevent audio session from starting while NightRunner is active.
    global _session_lock_held
    try:
        await asyncio.wait_for(SHARD_SESSION_LOCK.acquire(), timeout=0.1)
        _session_lock_held = True
        acquire_file_lock("audio_session")
        logger.info("[SESSION LOCK] Acquired by audio session.")
    except asyncio.TimeoutError:
        reason = get_lock_reason()
        logger.warning("[SESSION LOCK] Blocked — held by: %s", reason or "unknown")
        await sio.emit('error', {'msg': f'[LOCK] Cannot start: autonomous session is active ({reason or "unknown"}).'})
        return

    # --- Bounded queue for audio → frontend ---
    # CHUNK_SIZE=1024 @ 16kHz ≈ 15 chunks/sec. maxsize=30 ≈ 2 seconds of buffer.
    # Chunks beyond the limit are dropped silently: frontend visualization is
    # best-effort and must never block or slow down audio capture.
    _audio_fe_queue: asyncio.Queue = asyncio.Queue(maxsize=30)

    async def _audio_frontend_worker():
        """Single coroutine that serialises all audio→frontend emissions.
        Replaces the per-chunk create_task pattern that caused unbounded task growth."""
        try:
            while True:
                chunk = await _audio_fe_queue.get()
                try:
                    await sio.emit('audio_data', {'data': chunk})
                finally:
                    _audio_fe_queue.task_done()
        except asyncio.CancelledError:
            logger.info("[AudioFrontend] Worker shutting down — draining queue.")
            while not _audio_fe_queue.empty():
                try:
                    _audio_fe_queue.get_nowait()
                    _audio_fe_queue.task_done()
                except asyncio.QueueEmpty:
                    break

    audio_fe_task = asyncio.create_task(
        _audio_frontend_worker(), name="audio_frontend_worker"
    )
    audio_fe_task.add_done_callback(
        lambda t: logger.error(
            "[AudioFrontend] Worker died unexpectedly: %s", t.exception()
        ) if not t.cancelled() and t.exception() else None
    )

    def on_audio_data(data_bytes):
        """Sync callback invoked per audio chunk. Enqueues for the worker — never blocks."""
        try:
            _audio_fe_queue.put_nowait(list(data_bytes))
        except asyncio.QueueFull:
            pass  # drop — frontend is behind, audio capture must not wait

    # Callback to send CAL data to frontend
    def on_cad_data(data):
        info = f"{len(data.get('vertices', []))} vertices" if 'vertices' in data else f"{len(data.get('data', ''))} bytes (STL)"
        print(f"Sending CAD data to frontend: {info}")
        asyncio.create_task(sio.emit('cad_data', data))

    # Callback to send Browser data to frontend
    def on_web_data(data):
        print(f"Sending Browser data to frontend: {len(data.get('log', ''))} chars logs")
        asyncio.create_task(sio.emit('browser_frame', data))
        
    # Callback to send Transcription data to frontend
    def on_transcription(data, *args, **kwargs):
        # data = {"sender": "User"|"SHARD", "text": "..."}
        asyncio.create_task(sio.emit('transcription', data))
        # Emit mood update to frontend for reactor color
        if audio_loop and hasattr(audio_loop, 'consciousness'):
            state = audio_loop.consciousness.state
            asyncio.create_task(sio.emit('mood_update', {
                'mood': state['mood'],
                'energy': state['energy'],
                'curiosity': state['curiosity'],
                'focus': state['focus'],
                'satisfaction': state['satisfaction']
            }))

    # Callback to send Confirmation Request to frontend
    def on_tool_confirmation(data):
        # data = {"id": "uuid", "tool": "tool_name", "args": {...}}
        print(f"Requesting confirmation for tool: {data.get('tool')}")
        asyncio.create_task(sio.emit('tool_confirmation_request', data))

    # Callback to send CAD status to frontend
    def on_cad_status(status):
        # status can be: 
        # - a string like "generating" (from SHARD.py handle_cad_request)
        # - a dict with {status, attempt, max_attempts, error} (from CadAgent)
        if isinstance(status, dict):
            print(f"Sending CAD Status: {status.get('status')} (attempt {status.get('attempt')}/{status.get('max_attempts')})")
            asyncio.create_task(sio.emit('cad_status', status))
        else:
            # Legacy: simple string
            print(f"Sending CAD Status: {status}")
            asyncio.create_task(sio.emit('cad_status', {'status': status}))

    # Callback to send CAD thoughts to frontend (streaming)
    def on_cad_thought(thought_text):
        asyncio.create_task(sio.emit('cad_thought', {'text': thought_text}))

    # Callback to send Project Update to frontend
    def on_project_update(project_name):
        print(f"Sending Project Update: {project_name}")
        asyncio.create_task(sio.emit('project_update', {'project': project_name}))

    # Callback to send Device Update to frontend
    def on_device_update(devices):
        # devices is a list of dicts
        print(f"Sending Kasa Device Update: {len(devices)} devices")
        asyncio.create_task(sio.emit('kasa_devices', devices))

    # Callback to send Error to frontend
    def on_error(msg):
        print(f"Sending Error to frontend: {msg}")
        asyncio.create_task(sio.emit('error', {'msg': msg}))

    def on_study_request(topic, tier):
        async def _on_progress(phase, topic, score, msg, pct):
            await sio.emit('study_progress', {
                'phase': phase, 'topic': topic, 'score': score,
                'message': msg, 'percentage': pct
            })
        async def _on_certify(t, score, data):
            await sio.emit('study_complete', {
                'topic': t, 'score': score, 'data': data
            })
        asyncio.create_task(study_agent.study_topic(
            topic, tier=tier,
            on_progress=_on_progress,
            on_certify=_on_certify
        ))

    # Initialize SHARD (refactored to ShardCore)
    # Pass the existing study_agent so SessionOrchestrator doesn't create a second one.
    try:
        shard_core = shard.ShardCore(study_agent=study_agent)

        # Map UI callbacks to socket emissions
        shard_core.ui_callbacks["on_transcription"] = lambda text: asyncio.create_task(sio.emit('transcription', text))
        shard_core.ui_callbacks["on_cad_data"] = lambda data: asyncio.create_task(sio.emit('cad_data', data))
        shard_core.ui_callbacks["on_cad_status"] = lambda status: asyncio.create_task(sio.emit('cad_status', status))
        shard_core.ui_callbacks["on_cad_thought"] = lambda thought_text: asyncio.create_task(sio.emit('cad_thought', {'text': thought_text}))
        shard_core.ui_callbacks["on_project_update"] = lambda project_name: asyncio.create_task(sio.emit('project_update', {'project': project_name}))
        shard_core.ui_callbacks["on_device_update"] = lambda devices: asyncio.create_task(sio.emit('kasa_devices', devices))
        shard_core.ui_callbacks["on_error"] = lambda msg: asyncio.create_task(sio.emit('error', {'msg': msg}))
        shard_core.ui_callbacks["on_study_request"] = on_study_request
        shard_core.ui_callbacks["on_tool_confirmation"] = on_tool_confirmation

        # Apply current permissions if supported
        if hasattr(shard_core, "update_permissions"):
            shard_core.update_permissions(SETTINGS["tool_permissions"])

        # Expose shard_core globally so video_frame handler can reach it
        _shard_core = shard_core
        audio_loop = shard_core.audio_video_io

        # Wire consciousness to benchmark_loop e llm_router
        try:
            import benchmark_loop as _bl
            import llm_router as _lr
            if hasattr(audio_loop, 'consciousness'):
                _bl.set_consciousness(audio_loop.consciousness)
                _lr.set_consciousness(audio_loop.consciousness)
        except Exception:
            pass

        # Start system
        print("Starting ShardCore system…")
        await shard_core.start_system(session_host)

        print("Emitting 'SHARD Started'")
        await sio.emit('status', {'msg': 'SHARD Started'})

        # Load saved printers if ShardCore exposes printer_agent
        saved_printers = SETTINGS.get("printers", [])
        if saved_printers and getattr(shard_core, "printer_agent", None):
            print(f"[SERVER] Loading {len(saved_printers)} saved printers...")
            for p in saved_printers:
                shard_core.printer_agent.add_printer_manually(
                    name=p.get("name", p["host"]),
                    host=p["host"],
                    port=p.get("port", 80),
                    printer_type=p.get("type", "moonraker"),
                    camera_url=p.get("camera_url")
                )

        # Start Printer Monitor (adapted to shard_core if needed)
        asyncio.create_task(monitor_printers_loop())

    except Exception as e:
        print(f"CRITICAL ERROR STARTING SHARD: {e}")
        import traceback
        traceback.print_exc()
        await sio.emit('error', {'msg': f"Failed to start: {str(e)}"})
        audio_loop = None # Ensure we can try again


async def monitor_printers_loop():
    """Background task to query printer status periodically."""
    print("[SERVER] Starting Printer Monitor Loop")
    while audio_loop and hasattr(audio_loop, 'printer_agent') and audio_loop.printer_agent:
        try:
            agent = audio_loop.printer_agent
            if not agent.printers:
                await asyncio.sleep(5)
                continue
                
            tasks = []
            for host, printer in agent.printers.items():
                if printer.printer_type.value != "unknown":
                    tasks.append(agent.get_print_status(host))
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in results:
                    if isinstance(res, Exception):
                        pass # Ignore errors for now
                    elif res:
                        # res is PrintStatus object
                        await sio.emit('print_status_update', res.to_dict())
                        
        except asyncio.CancelledError:
            print("[SERVER] Printer Monitor Cancelled")
            break
        except Exception as e:
            print(f"[SERVER] Monitor Loop Error: {e}")
            
        await asyncio.sleep(2) # Update every 2 seconds for responsiveness

@sio.event
async def stop_audio(sid):
    global audio_loop, audio_fe_task, _session_lock_held, _shard_core
    if audio_loop:
        audio_loop.stop()
        logger.info("[SERVER] Audio loop stopped.")
        audio_loop = None
    if _shard_core:
        await _shard_core.stop()
        _shard_core = None
        logger.info("[SERVER] ShardCore stopped.")
    # ── Release session lock ─────────────────────────────────────────────────
    if _session_lock_held:
        SHARD_SESSION_LOCK.release()
        release_file_lock()
        _session_lock_held = False
        logger.info("[SESSION LOCK] Released by stop_audio.")
    if audio_fe_task and not audio_fe_task.done():
        audio_fe_task.cancel()
        try:
            await audio_fe_task
        except asyncio.CancelledError:
            pass
        audio_fe_task = None
        logger.info("[AudioFrontend] Worker cancelled and cleaned up.")
    await sio.emit('status', {'msg': 'SHARD Stopped'})

@sio.event
async def pause_audio(sid):
    global audio_loop
    if audio_loop:
        audio_loop.set_paused(True)
        print("Pausing Audio")
        await sio.emit('status', {'msg': 'Audio Paused'})

@sio.event
async def resume_audio(sid):
    global audio_loop
    if audio_loop:
        audio_loop.set_paused(False)
        print("Resuming Audio")
        await sio.emit('status', {'msg': 'Audio Resumed'})

@sio.event
async def confirm_tool(sid, data):
    if not await _require_auth(sid, "confirm_tool"): return
    # data: { "id": "...", "confirmed": True/False }
    request_id = data.get('id')
    confirmed = data.get('confirmed', False)
    
    print(f"[SERVER DEBUG] Received confirmation response for {request_id}: {confirmed}")
    
    if _shard_core and hasattr(_shard_core, 'session_orchestrator'):
        _shard_core.session_orchestrator.resolve_tool_confirmation(request_id, confirmed)
    else:
        print("Orchestrator not active, cannot resolve confirmation.")

@sio.event
async def shutdown(sid, data=None):
    """Gracefully shutdown the server when the application closes."""
    if not await _require_auth(sid, "shutdown"): return
    global audio_loop, loop_task, authenticator
    
    print("[SERVER] ========================================")
    print("[SERVER] SHUTDOWN SIGNAL RECEIVED FROM FRONTEND")
    print("[SERVER] ========================================")
    
    # Stop audio loop
    if audio_loop:
        print("[SERVER] Stopping Audio Loop...")
        audio_loop.stop()
        audio_loop = None
    
    # Cancel the loop task if running
    if loop_task and not loop_task.done():
        print("[SERVER] Cancelling loop task...")
        loop_task.cancel()
        loop_task = None
    
    # Stop authenticator if running
    if authenticator:
        print("[SERVER] Stopping Authenticator...")
        authenticator.stop()
    
    print("[SERVER] Graceful shutdown complete. Terminating process...")
    
    # Force exit immediately - os._exit bypasses cleanup but ensures termination
    os._exit(0)



@sio.event
async def user_input(sid, data):
    text = data.get('text')
    print(f"[SERVER DEBUG] User input received: '{text}'")

    capability_queries = [
        "what can you do",
        "capabilities",
        "cosa sai fare",
        "dimmi le tue capacità",
    ]
    normalized = (text or "").lower()
    if any(q in normalized for q in capability_queries):
        response = study_agent.self_model.describe()
        await sio.emit('transcription', {'text': response, 'sender': 'SHARD'})
        return
    
    # --- BACKDOOR PER LO STUDIO MANUALE ---
    if text and text.lower().startswith("/study "):
        topic_to_study = text[7:].strip()
        print(f"[SERVER] Backdoor attivata! Avvio studio forzato su: {topic_to_study}")
        await start_study(sid, {"topic": topic_to_study, "tier": 1})
        return
    # --------------------------------------

    # --- INIZIO BLOCCO MOOD ---
    if text and text.startswith('/mood '):
        mood = text.split(' ', 1)[1].strip()
        await sio.emit('mood_update', {'mood': mood, 'energy': 0.8, 'curiosity': 0.5, 'focus': 0.7, 'satisfaction': 0.6})
        await sio.emit('transcription', {'text': f'System Notification: Mood set to {mood}', 'sender': 'System'})
        return
    # --- FINE BLOCCO MOOD ---
    
    if not audio_loop or not audio_loop.session:
        print("[SERVER DEBUG] Gemini not active. Routing to Groq fallback.")
        if text:
            await groq_fallback(text)
        return

    if text:
        print(f"[SERVER DEBUG] Sending message to model: '{text}'")
        
        # Log User Input to Project History
        if audio_loop and audio_loop.project_manager:
            audio_loop.project_manager.log_chat("User", text)

    # --INIZIO AUTOMAZIONE COSCIENZA ---
        if audio_loop and hasattr(audio_loop, 'consciousness'):
            audio_loop.consciousness.process_interaction("User", text)
            state = audio_loop.consciousness.state
            await sio.emit('mood_update', {
                'mood': state['mood'],
                'energy': state['energy'],
                'curiosity': state['curiosity'],
                'focus': state['focus'],
                'satisfaction': state['satisfaction']
            })
    # --FINE AUTOMAZIONE COSCIENZA ---
            
        # Use the same 'send' method that worked for audio, as 'send_realtime_input' and 'send_client_content' seem unstable in this env
        # INJECT VIDEO FRAME IF AVAILABLE (VAD-style logic for Text Input)
        # Gemini disponibile → usa Gemini
        if audio_loop.session:
            try:
                if audio_loop._latest_image_payload:
                    try:
                        await audio_loop.session.send(input=audio_loop._latest_image_payload, end_of_turn=False)
                    except Exception as e:
                        print(f"[SERVER DEBUG] Failed to send piggyback frame: {e}")

                _NIGHT_KEYWORDS = [
                    "studiato", "studia", "imparato", "stanotte", "notte", "night",
                    "report", "ciclo", "skill", "recap", "esperiment", "what did you study",
                    "cosa hai fatto", "sessione", "dark matter", "cnn", "perceptron",
                ]
                _normalized = text.lower()
                if any(kw in _normalized for kw in _NIGHT_KEYWORDS):
                    night_ctx = _load_last_night_report()
                    if night_ctx:
                        text = f"[CONTESTO SESSIONE NOTTURNA: {night_ctx}]\n\n{text}"

                await audio_loop.session.send(input=text, end_of_turn=True)
                print(f"[SERVER DEBUG] Message sent to Gemini successfully.")

            except Exception as e:
                print(f"[SERVER DEBUG] Gemini error: {e}. Falling back to Groq...")
                await groq_fallback(text)

        # Gemini non disponibile → fallback Groq
        else:
            print("[SERVER DEBUG] Gemini unavailable. Using Groq fallback.")
            await groq_fallback(text)

def _load_last_night_report() -> str:
    """Load the most recent night session JSON as a compact context string."""
    try:
        reports_dir = Path(ROOT_DIR) / "night_reports"
        sessions = sorted(reports_dir.glob("session_*.json"))
        if not sessions:
            return ""
        last = sessions[-1]
        data = json.loads(last.read_text(encoding="utf-8"))
        date = data.get("date", "unknown")
        cycles = data.get("cycles", [])
        certified = [c for c in cycles if c.get("certified")]
        failed = [c for c in cycles if not c.get("certified")]
        skills_before = cycles[0].get("skills_before", "?") if cycles else "?"
        skills_after = cycles[-1].get("skills_after", "?") if cycles else "?"
        topics_ok = ", ".join(f"{c['topic']} (score: {c.get('score', '?')})" for c in certified)
        best = max(certified, key=lambda c: c.get("score", 0)) if certified else None
        topics_fail = ", ".join(c["topic"] for c in failed) if failed else "nessuno"
        best_str = f" Topic migliore: '{best['topic']}' score {best.get('score','?')}/10." if best else ""
        return (
            f"[NIGHT REPORT {date}] "
            f"Cicli completati: {len(certified)}/{len(cycles)}. "
            f"Skill: {skills_before} → {skills_after} (+{int(skills_after) - int(skills_before) if str(skills_before).isdigit() and str(skills_after).isdigit() else '?'})."
            f"{best_str} "
            f"Topic certificati con score: {topics_ok}. "
            f"Falliti: {topics_fail}."
        )
    except Exception:
        return ""


async def groq_fallback(text: str):
    try:
        from groq import Groq
        import os
        groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

        night_context = _load_last_night_report()
        system_prompt = (
            "You are SHARD, an autonomous AI assistant built by Andrea. "
            "Respond in the same language the user writes in (Italian if they write Italian). "
            + (f"Here is your most recent autonomous study session data: {night_context}" if night_context else "")
        )

        # Run synchronous Groq client in a thread to avoid blocking the event loop
        def _call_groq():
            return groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                temperature=0.7,
                max_tokens=1024
            )
        
        response = await asyncio.to_thread(_call_groq)
        reply = response.choices[0].message.content
        await sio.emit('transcription', {'text': reply, 'sender': 'assistant'})
        await sio.emit('status', {'msg': '[GROQ MODE] Gemini offline'})
    except Exception as e:
        await sio.emit('error', {'msg': f'Groq fallback failed: {str(e)}'})

@sio.event
async def video_frame(sid, data):
    image_data = data.get('image')
    if not image_data:
        return
    # Route to the active ShardCore (new system) or legacy audio_loop (old system)
    if _shard_core is not None:
        asyncio.create_task(_shard_core.audio_video_io.send_frame(image_data))
    elif audio_loop is not None:
        asyncio.create_task(audio_loop.send_frame(image_data))

@sio.event
async def save_memory(sid, data):
    if not await _require_auth(sid, "save_memory"): return
    try:
        messages = data.get('messages', [])
        if not messages:
            print("No messages to save.")
            return

        # Ensure directory exists
        memory_dir = Path("long_term_memory")
        memory_dir.mkdir(exist_ok=True)

        # Generate filename
        # Use provided filename if available, else timestamp
        provided_name = data.get('filename')
        
        if provided_name:
            # Simple sanitization
            if not provided_name.endswith('.txt'):
                provided_name += '.txt'
            # Prevent directory traversal
            filename = memory_dir / Path(provided_name).name 
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = memory_dir / f"memory_{timestamp}.txt"

        # Write to file
        with open(filename, 'w', encoding='utf-8') as f:
            for msg in messages:
                sender = msg.get('sender', 'Unknown')
                text = msg.get('text', '')
                f.write(f"[{sender}]: {text}\n")
        print(f"Conversation saved to {filename}")
        await sio.emit('status', {'msg': 'Memory Saved Successfully'})

    except Exception as e:
        print(f"Error saving memory: {e}")
        await sio.emit('error', {'msg': f"Failed to save memory: {str(e)}"})

@sio.event
async def upload_memory(sid, data):
    if not await _require_auth(sid, "upload_memory"): return
    logger.info("[SERVER] Memory upload request from sid=%s", sid)
    try:
        memory_text = data.get('memory', '')
        if not memory_text:
            print("No memory data provided.")
            return

        if not audio_loop:
             print("[SERVER DEBUG] [Error] Audio loop is None. Cannot load memory.")
             await sio.emit('error', {'msg': "System not ready (Audio Loop inactive)"})
             return
        
        if not audio_loop.session:
             print("[SERVER DEBUG] [Error] Session is None. Cannot load memory.")
             await sio.emit('error', {'msg': "System not ready (No active session)"})
             return

        # Send to model
        print("Sending memory context to model...")
        context_msg = f"System Notification: The user has uploaded a long-term memory file. Please load the following context into your understanding. The format is a text log of previous conversations:\n\n{memory_text}"
        
        await audio_loop.session.send(input=context_msg, end_of_turn=True)
        print("Memory context sent successfully.")
        await sio.emit('status', {'msg': 'Memory Loaded into Context'})

    except Exception as e:
        print(f"Error uploading memory: {e}")
        await sio.emit('error', {'msg': f"Failed to upload memory: {str(e)}"})

@sio.event
async def discover_kasa(sid):
    print(f"Received discover_kasa request")
    try:
        devices = await kasa_agent.discover_devices()
        await sio.emit('kasa_devices', devices)
        await sio.emit('status', {'msg': f"Found {len(devices)} Kasa devices"})
        
        # Save to settings
        # devices is a list of full device info dicts. minimizing for storage.
        saved_devices = []
        for d in devices:
            saved_devices.append({
                "ip": d["ip"],
                "alias": d["alias"],
                "model": d["model"]
            })
        
        # Merge with existing to preserve any manual overrides? 
        # For now, just overwrite with latest scan result + previously known if we want to be fancy,
        # but user asked for "Any new devices that are scanned are added there".
        # A simple full persistence of current state is safest.
        SETTINGS["kasa_devices"] = saved_devices
        save_settings()
        print(f"[SERVER] Saved {len(saved_devices)} Kasa devices to settings.")
        
    except Exception as e:
        print(f"Error discovering kasa: {e}")
        await sio.emit('error', {'msg': f"Kasa Discovery Failed: {str(e)}"})

@sio.event
async def iterate_cad(sid, data):
    if not await _require_auth(sid, "iterate_cad"): return
    # data: { prompt: "make it bigger" }
    prompt = data.get('prompt')
    logger.info("[SERVER] iterate_cad from sid=%s: '%s'", sid, prompt)
    
    if not audio_loop or not audio_loop.cad_agent:
        await sio.emit('error', {'msg': "CAD Agent not available"})
        return

    try:
        # Notify user work has started
        await sio.emit('status', {'msg': 'Iterating design...'})
        await sio.emit('cad_status', {'status': 'generating'})
        
        # Call the agent with project path
        cad_output_dir = str(audio_loop.project_manager.get_current_project_path() / "cad")
        result = await audio_loop.cad_agent.iterate_prototype(prompt, output_dir=cad_output_dir)
        
        if result:
            info = f"{len(result.get('data', ''))} bytes (STL)"
            print(f"Sending updated CAD data: {info}")
            await sio.emit('cad_data', result)
            # Save to Project
            if 'file_path' in result:
                saved_path = audio_loop.project_manager.save_cad_artifact(result['file_path'], prompt)
                if saved_path:
                    print(f"[SERVER] Saved iterated CAD to {saved_path}")

            await sio.emit('status', {'msg': 'Design updated'})
        else:
            await sio.emit('error', {'msg': 'Failed to update design'})
            
    except Exception as e:
        print(f"Error iterating CAD: {e}")
        await sio.emit('error', {'msg': f"Iteration Error: {str(e)}"})

@sio.event
async def generate_cad(sid, data):
    if not await _require_auth(sid, "generate_cad"): return
    # data: { prompt: "make a cube" }
    prompt = data.get('prompt')
    logger.info("[SERVER] generate_cad from sid=%s: '%s'", sid, prompt)
    
    if not audio_loop or not audio_loop.cad_agent:
        await sio.emit('error', {'msg': "CAD Agent not available"})
        return

    try:
        await sio.emit('status', {'msg': 'Generating new design...'})
        await sio.emit('cad_status', {'status': 'generating'})
        
        # Use generate_prototype based on prompt with project path
        cad_output_dir = str(audio_loop.project_manager.get_current_project_path() / "cad")
        result = await audio_loop.cad_agent.generate_prototype(prompt, output_dir=cad_output_dir)
        
        if result:
            info = f"{len(result.get('data', ''))} bytes (STL)"
            print(f"Sending newly generated CAD data: {info}")
            await sio.emit('cad_data', result)


            # Save to Project
            if 'file_path' in result:
                saved_path = audio_loop.project_manager.save_cad_artifact(result['file_path'], prompt)
                if saved_path:
                    print(f"[SERVER] Saved generated CAD to {saved_path}")

            await sio.emit('status', {'msg': 'Design generated'})
        else:
            await sio.emit('error', {'msg': 'Failed to generate design'})
            
    except Exception as e:
        print(f"Error generating CAD: {e}")
        await sio.emit('error', {'msg': f"Generation Error: {str(e)}"})

@sio.event
async def prompt_web_agent(sid, data):
    # data: { prompt: "find xyz" }
    prompt = data.get('prompt')
    print(f"Received web agent prompt: '{prompt}'")
    
    if not audio_loop or not audio_loop.web_agent:
        await sio.emit('error', {'msg': "Web Agent not available"})
        return

    try:
        await sio.emit('status', {'msg': 'Web Agent running...'})
        
        # We assume web_agent has a run method or similar.
        # This might block the loop if not strictly async or offloaded.
        # Ideally web_agent.run is async.
        # And it should emit 'browser_snap' and logs automatically via hooks if setup.
        
        # We might need to launch this as a task if it's long running?
        # asyncio.create_task(audio_loop.web_agent.run(prompt))
        # But we want to catch errors here.
        
        # Based on typical agent design, run() is the entry point.
        await audio_loop.web_agent.run(prompt)
        
        await sio.emit('status', {'msg': 'Web Agent finished'})
        
    except Exception as e:
        print(f"Error running Web Agent: {e}")
        await sio.emit('error', {'msg': f"Web Agent Error: {str(e)}"})

@sio.event
async def discover_printers(sid):
    print("Received discover_printers request")
    
    # If audio_loop isn't ready yet, return saved printers from settings
    if not audio_loop or not audio_loop.printer_agent:
        saved_printers = SETTINGS.get("printers", [])
        if saved_printers:
            # Convert saved printers to the expected format
            printer_list = []
            for p in saved_printers:
                printer_list.append({
                    "name": p.get("name", p["host"]),
                    "host": p["host"],
                    "port": p.get("port", 80),
                    "printer_type": p.get("type", "unknown"),
                    "camera_url": p.get("camera_url")
                })
            print(f"[SERVER] Returning {len(printer_list)} saved printers (audio_loop not ready)")
            await sio.emit('printer_list', printer_list)
            return
        else:
            await sio.emit('printer_list', [])
            await sio.emit('status', {'msg': "Connect to SHARD to enable printer discovery"})
            return
        
    try:
        printers = await audio_loop.printer_agent.discover_printers()
        await sio.emit('printer_list', printers)
        await sio.emit('status', {'msg': f"Found {len(printers)} printers"})
    except Exception as e:
        print(f"Error discovering printers: {e}")
        await sio.emit('error', {'msg': f"Printer Discovery Failed: {str(e)}"})

@sio.event
async def add_printer(sid, data):
    # data: { host: "192.168.1.50", name: "My Printer", type: "moonraker" }
    raw_host = data.get('host')
    name = data.get('name') or raw_host
    ptype = data.get('type', "moonraker")
    
    # Parse port if present
    if ":" in raw_host:
        host, port_str = raw_host.split(":")
        port = int(port_str)
    else:
        host = raw_host
        port = 80
    
    print(f"Received add_printer request: {host}:{port} ({ptype})")
    
    if not audio_loop or not audio_loop.printer_agent:
        await sio.emit('error', {'msg': "Printer Agent not available"})
        return
        
    try:
        # Add manually
        camera_url = data.get('camera_url')
        printer = audio_loop.printer_agent.add_printer_manually(name, host, port=port, printer_type=ptype, camera_url=camera_url)
        
        # Save to settings
        new_printer_config = {
            "name": name,
            "host": host,
            "port": port,
            "type": ptype,
            "camera_url": camera_url
        }
        
        # Check if already exists to avoid duplicates
        exists = False
        for p in SETTINGS.get("printers", []):
            if p["host"] == host and p["port"] == port:
                exists = True
                break
        
        if not exists:
            if "printers" not in SETTINGS:
                SETTINGS["printers"] = []
            SETTINGS["printers"].append(new_printer_config)
            save_settings()
            print(f"[SERVER] Saved printer {name} to settings.")
        
        # Probe to confirm/correct type
        print(f"Probing {host} to confirm type...")
        # Try port 7125 (Moonraker) and 4408 (Fluidd/K1) 
        ports_to_try = [80, 7125, 4408]
        
        actual_type = "unknown"
        for port in ports_to_try:
             found_type = await audio_loop.printer_agent._probe_printer_type(host, port)
             if found_type.value != "unknown":
                 actual_type = found_type
                 # Update port if different
                 if port != 80:
                     printer.port = port
                 break
        
        if actual_type != "unknown" and actual_type != printer.printer_type:
             printer.printer_type = actual_type
             print(f"Corrected type to {actual_type.value} on port {printer.port}")
             
        # Refresh list for everyone
        printers = [p.to_dict() for p in audio_loop.printer_agent.printers.values()]
        await sio.emit('printer_list', printers)
        await sio.emit('status', {'msg': f"Added printer: {name}"})
        
    except Exception as e:
        print(f"Error adding printer: {e}")
        await sio.emit('error', {'msg': f"Failed to add printer: {str(e)}"})

@sio.event
async def print_stl(sid, data):
    print(f"Received print_stl request: {data}")
    # data: { stl_path: "path/to.stl" | "current", printer: "name_or_ip", profile: "optional" }
    
    if not audio_loop or not audio_loop.printer_agent:
        await sio.emit('error', {'msg': "Printer Agent not available"})
        return
        
    try:
        stl_path = data.get('stl_path', 'current')
        printer_name = data.get('printer')
        profile = data.get('profile')
        
        if not printer_name:
             await sio.emit('error', {'msg': "No printer specified"})
             return
             
        await sio.emit('status', {'msg': f"Preparing print for {printer_name}..."})
        
        # Get current project path for resolution
        current_project_path = None
        if audio_loop and audio_loop.project_manager:
            current_project_path = str(audio_loop.project_manager.get_current_project_path())
            print(f"[SERVER DEBUG] Using project path: {current_project_path}")

        # Resolve STL path before slicing so we can preview it
        resolved_stl = audio_loop.printer_agent._resolve_file_path(stl_path, current_project_path)
        
        if resolved_stl and os.path.exists(resolved_stl):
            # Open the STL in the CAD module for preview
            try:
                import base64
                with open(resolved_stl, 'rb') as f:
                    stl_data = f.read()
                stl_b64 = base64.b64encode(stl_data).decode('utf-8')
                stl_filename = os.path.basename(resolved_stl)
                
                print(f"[SERVER] Opening STL in CAD module: {stl_filename}")
                await sio.emit('cad_data', {
                    'format': 'stl',
                    'data': stl_b64,
                    'filename': stl_filename
                })
            except Exception as e:
                print(f"[SERVER] Warning: Could not preview STL: {e}")
        
        # Progress Callback
        async def on_slicing_progress(percent, message):
            await sio.emit('slicing_progress', {
                'printer': printer_name,
                'percent': percent,
                'message': message
            })
            if percent < 100:
                 await sio.emit('status', {'msg': f"Slicing: {percent}%"})

        result = await audio_loop.printer_agent.print_stl(
            stl_path, 
            printer_name, 
            profile,
            progress_callback=on_slicing_progress,
            root_path=current_project_path
        )
        
        await sio.emit('print_result', result)
        await sio.emit('status', {'msg': f"Print Job: {result.get('status', 'unknown')}"})
        
    except Exception as e:
        print(f"Error printing STL: {e}")
        await sio.emit('error', {'msg': f"Print Failed: {str(e)}"})

@sio.event
async def get_slicer_profiles(sid):
    """Get available OrcaSlicer profiles for manual selection."""
    print("Received get_slicer_profiles request")
    if not audio_loop or not audio_loop.printer_agent:
        await sio.emit('error', {'msg': "Printer Agent not available"})
        return
    
    try:
        profiles = audio_loop.printer_agent.get_available_profiles()
        await sio.emit('slicer_profiles', profiles)
    except Exception as e:
        print(f"Error getting slicer profiles: {e}")
        await sio.emit('error', {'msg': f"Failed to get profiles: {str(e)}"})

@sio.event
async def control_kasa(sid, data):
    # data: { ip, action: "on"|"off"|"brightness"|"color", value: ... }
    ip = data.get('ip')
    action = data.get('action')
    print(f"Kasa Control: {ip} -> {action}")
    
    try:
        success = False
        if action == "on":
            success = await kasa_agent.turn_on(ip)
        elif action == "off":
            success = await kasa_agent.turn_off(ip)
        elif action == "brightness":
            val = data.get('value')
            success = await kasa_agent.set_brightness(ip, val)
        elif action == "color":
            # value is {h, s, v} - convert to tuple for set_color
            h = data.get('value', {}).get('h', 0)
            s = data.get('value', {}).get('s', 100)
            v = data.get('value', {}).get('v', 100)
            success = await kasa_agent.set_color(ip, (h, s, v))
        
        if success:
            await sio.emit('kasa_update', {
                'ip': ip,
                'is_on': True if action == "on" else (False if action == "off" else None),
                'brightness': data.get('value') if action == "brightness" else None,
            })
 
        else:
             await sio.emit('error', {'msg': f"Failed to control device {ip}"})

    except Exception as e:
         print(f"Error controlling kasa: {e}")
         await sio.emit('error', {'msg': f"Kasa Control Error: {str(e)}"})

@sio.event
async def get_settings(sid):
    await sio.emit('settings', SETTINGS)

@sio.event
async def update_settings(sid, data):
    if not await _require_auth(sid, "update_settings"): return

    valid, reason = _validate_settings_payload(data)
    if not valid:
        logger.warning("[SETTINGS] Rejected invalid payload from sid=%s: %s", sid, reason)
        await sio.emit('error', {'msg': f'Invalid settings update: {reason}'}, to=sid)
        return

    logger.info("[SETTINGS] Update from sid=%s: keys=%s", sid, list(data.keys()))

    if "tool_permissions" in data:
        SETTINGS["tool_permissions"].update(data["tool_permissions"])
        if audio_loop:
            audio_loop.update_permissions(SETTINGS["tool_permissions"])

    if "face_auth_enabled" in data:
        SETTINGS["face_auth_enabled"] = data["face_auth_enabled"]
        if not data["face_auth_enabled"]:
            _authenticated_sids.add(sid)
            await sio.emit('auth_status', {'authenticated': True}, to=sid)
            if authenticator:
                authenticator.stop()

    if "camera_flipped" in data:
        SETTINGS["camera_flipped"] = data["camera_flipped"]
        logger.info("[SETTINGS] Camera flip set to: %s", data['camera_flipped'])

    save_settings()
    await sio.emit('settings', SETTINGS, to=sid)


# Deprecated/Mapped for compatibility if frontend still uses specific events
@sio.event
async def get_tool_permissions(sid):
    await sio.emit('tool_permissions', SETTINGS["tool_permissions"])

@sio.event
async def update_tool_permissions(sid, data):
    if not await _require_auth(sid, "update_tool_permissions"): return
    valid, reason = _validate_settings_payload({"tool_permissions": data})
    if not valid:
        logger.warning("[SETTINGS] Rejected invalid permissions from sid=%s: %s", sid, reason)
        await sio.emit('error', {'msg': f'Invalid permissions update: {reason}'}, to=sid)
        return
    logger.info("[SETTINGS] Permission update from sid=%s: %s", sid, data)
    SETTINGS["tool_permissions"].update(data)
    save_settings()
    if audio_loop:
        audio_loop.update_permissions(SETTINGS["tool_permissions"])
    # Broadcast update to all
    await sio.emit('tool_permissions', SETTINGS["tool_permissions"])

@sio.event
async def start_study(sid, data):
    if not await _require_auth(sid, "start_study"): return
    topic = data.get('topic', '')
    tier = data.get('tier', 1)
    if not topic:
        await sio.emit('error', {'msg': 'No topic provided'}, to=sid)
        return

    await sio.emit('status', {'msg': f'SHARD.STUDY starting: {topic} (Tier {tier})'})

    async def on_progress(phase, topic, score, message, pct):
        print(f"[DEBUG] Invio al frontend: Fase={phase}, Pct={pct}%")
        await sio.emit('study_progress', {
            'phase': phase,
            'topic': topic,
            'score': score,
            'message': message,
            'pct': pct
        })

    async def on_certify(topic, score, data):
        await sio.emit('study_complete', {
            'topic': topic,
            'score': score,
            'data': data
        })
        await sio.emit('status', {'msg': f'SHARD STUDY certified: {topic} ({score}/10)'})
        
        # --- TRACCIA CAUSALE: push evento studio completato alla coscienza ---
        if audio_loop and hasattr(audio_loop, 'consciousness'):
            audio_loop.consciousness.push_event("study_done", {"topic": topic, "score": score})

        # --- SISTEMA RPG: AGGIUNTA XP AL LIBRETTO ---
        if audio_loop and hasattr(audio_loop, 'consciousness'):
            # Determina la skill in base all'argomento studiato
            skill_target = "Python_Advanced" if "python" in topic.lower() else "Unity_ML_Agents"

            # Invia il voto (score) al cervello di SHARD
            leveled_up = audio_loop.consciousness.add_xp(skill_target, float(score))
            
            # Se la funzione ci restituisce True, significa che è scattato il Level Up massimo!
            if leveled_up:
                print(f"[SERVER] BOOM! Inviando notifica di Certificazione per {skill_target} al Frontend!")
                # Avvisa il frontend per far partire un'animazione o sbloccare badge
                await sio.emit('skill_certified', {'skill': skill_target, 'msg': f"Certificazione ottenuta in {skill_target}!"})

        # --- NOTIFICA VOCALE VIA GEMINI LIVE ---
        if audio_loop and audio_loop.session:
            try:
                penalties_info = ""
                if isinstance(data, dict) and "penalties_applied" in data:
                    penalties_list = data.get("penalties_applied", [])
                    if penalties_list:
                        penalties_info = " Penalità applicate: " + ", ".join(
                            [f"{p.get('rule', '?')} ({p.get('points', '?')})" for p in penalties_list[:3]]
                        )

                vocal_prompt = (
                    f"SISTEMA (Non leggere questo testo letteralmente): "
                    f"Hai appena completato in background lo studio di '{topic}'. "
                    f"Hai ottenuto un punteggio di {score}/10.{penalties_info} "
                    f"Usa la tua voce per avvisare il Boss che hai finito, "
                    f"digli il voto che hai preso e fai un breve commento spietato "
                    f"sul perché hai preso quel voto."
                )
                await audio_loop.session.send(input=vocal_prompt, end_of_turn=True)
                print(f"[SERVER] ✅ Notifica vocale iniettata nella sessione Gemini per '{topic}' (score: {score})")
            except Exception as e:
                print(f"[SERVER] ❌ Errore nell'iniezione vocale: {e}")
        else:
            print(f"[SERVER] ⚠️ Sessione Gemini non attiva, notifica vocale saltata per '{topic}'")

    async def on_error(topic, phase, error_msg):
        """Callback for study crash — notify frontend + vocal alert."""
        await sio.emit('study_progress', {
            'phase': 'ERROR',
            'topic': topic,
            'score': 0,
            'message': f'CRASH in {phase}: {error_msg[:200]}',
            'pct': 0
        })
        await sio.emit('status', {'msg': f'SHARD STUDY CRASHED during {phase}: {error_msg[:100]}'})
        
        # --- NOTIFICA VOCALE DI EMERGENZA ---
        if audio_loop and audio_loop.session:
            try:
                crash_prompt = (
                    f"SISTEMA (Non leggere questo testo letteralmente): "
                    f"I tuoi sistemi cognitivi sono andati in crash durante la fase di studio "
                    f"'{phase}' sull'argomento '{topic}'. "
                    f"L'errore è: {error_msg[:150]}. "
                    f"Avvisa il Boss a voce che c'è stato un problema durante lo studio "
                    f"e chiedigli di guardare i log del terminale per capire cosa è successo."
                )
                await audio_loop.session.send(input=crash_prompt, end_of_turn=True)
                print(f"[SERVER] 🔊 Notifica vocale di CRASH iniettata per '{topic}' (fase: {phase})")
            except Exception as e:
                print(f"[SERVER] ❌ Errore nell'iniezione vocale di crash: {e}")
        else:
            print(f"[SERVER] ⚠️ Sessione Gemini non attiva, notifica vocale di crash saltata")
                
    asyncio.create_task(
        study_agent.study_topic(topic, tier=tier, on_progress=on_progress, on_certify=on_certify, on_error=on_error)
    )

@sio.event
async def get_study_status(sid):
    await sio.emit('study_status', {'running': study_agent.is_running})

@sio.event
async def test_mood(sid, data):
    """Test endpoint to change reactor color."""
    mood = data.get('mood', 'calm')
    print(f"[TEST] Setting mood to: {mood}")
    await sio.emit('mood_update', {
        'mood': mood,
        'energy': 0.8,
        'curiosity': 0.5,
        'focus': 0.7,
        'satisfaction': 0.6
    })    

async def _voice_queue_poller():
    """
    Polls voice_broadcaster queue every 3 seconds.
    If Gemini Live is active → injects text into session (native voice).
    Otherwise → emits shard_voice_event to frontend (Web Speech API fallback).
    """
    try:
        from voice_broadcaster import pop_all
    except ImportError:
        return

    while True:
        await asyncio.sleep(3)
        try:
            events = pop_all()
            for event in events:
                text = event.get("text", "")
                if not text:
                    continue
                # Approccio B: Gemini Live attivo → inject voce nativa
                core = _shard_core if _shard_core is not None else audio_loop
                if core is not None and hasattr(core, "session") and core.session:
                    try:
                        await core.session.send(input=text, end_of_turn=True)
                        print(f"[VOICE POLLER] Injected into Gemini: '{text[:60]}'")
                        continue
                    except Exception:
                        pass
                # Approccio A fallback: Web Speech API via Socket.IO
                await sio.emit("shard_voice_event", {
                    "text": text,
                    "priority": event.get("priority", "low"),
                    "event_type": event.get("event_type", "info"),
                })
                print(f"[VOICE POLLER] Emitted to frontend: '{text[:60]}'")
        except Exception as e:
            print(f"[VOICE POLLER] Error: {e}")


async def shard_evolution_heartbeat():
    """Controlla periodicamente se SHARD vuole studiare autonomamente."""
    while True:
        # Aspetta 10 minuti tra un controllo e l'altro (600 secondi)
        await asyncio.sleep(600) 
        
        if audio_loop and hasattr(audio_loop, 'consciousness'):
            print("[SERVER] Heartbeat: Controllo desiderio di evoluzione...")
            # Chiediamo alla coscienza se è il momento di studiare
            async def _study_callback(topic, tier):
                if audio_loop and audio_loop.on_study_request:
                    audio_loop.on_study_request(topic, tier)
            await audio_loop.consciousness.check_for_autonomous_study(_study_callback)

@app.get("/health")
async def health():
    """Expose system vitals for monitoring and debug."""
    # ── ChromaDB ─────────────────────────────────────────────────────────────
    chroma_ok = False
    try:
        import chromadb as _chroma
        _c = _chroma.PersistentClient(path=str(Path("shard_memory")))
        _c.list_collections()
        chroma_ok = True
    except Exception:
        pass



    # ── Capability count (SQLite primary, JSON fallback) ─────────────────────
    cap_count = 0
    try:
        from shard_db import query_one
        row = query_one("SELECT COUNT(*) AS cnt FROM capabilities")
        cap_count = row["cnt"] if row else 0
    except Exception:
        try:
            cap_path = Path("shard_memory") / "capability_graph.json"
            if cap_path.exists():
                cap_data = json.loads(cap_path.read_text(encoding="utf-8"))
                cap_count = len(cap_data)
        except Exception:
            pass

    lock_reason = get_lock_reason() if is_file_locked() else ""

    # ── Meta Learning introspection ───────────────────────────────────────────
    meta_stats: dict = {}
    try:
        raw = study_agent.meta_learning.get_stats()
        gs = raw.get("global", {})
        trend = gs.get("score_trend", 0.0)
        meta_stats = {
            "total_sessions": gs.get("total_sessions", 0),
            "avg_score": gs.get("avg_score", 0.0),
            "cert_rate": gs.get("cert_rate", 0.0),
            "score_trend": "↑" if trend > 0.05 else ("↓" if trend < -0.05 else "→"),
            "best_category": gs.get("best_category"),
            "worst_category": gs.get("worst_category"),
            "categories": raw.get("categories", {}),
        }
    except Exception:
        pass

    return {
        "status": "ok",
        "chromadb": chroma_ok,
        "capability_count": cap_count,
        "audio_session_active": audio_loop is not None,
        "session_lock_active": is_file_locked(),
        "session_lock_reason": lock_reason,
        "semaphore_free": not _session_lock_held,
        "meta_learning": meta_stats,
    }


# ── NightRunner Control ────────────────────────────────────────────────────────

_night_process: asyncio.subprocess.Process = None


async def _monitor_night_process():
    """Reads subprocess stdout line-by-line, logs it, then notifies the frontend."""
    import re as _re
    global _night_process
    if _night_process is None:
        return

    _study_re   = _re.compile(r'\[SHARD\.STUDY\]\s+\[\s*(\d+)%\]\s+(\w+)\s+\|[^|]*\|\s+(.+)')
    _cycle_re   = _re.compile(r'===\s+Cycle\s+(\d+)/(\d+)\s+===')
    _topic_re   = _re.compile(r'Topic selected:\s+(.+)')
    _certif_re  = _re.compile(r'CERTIFIED|score=(\d+(?:\.\d+)?)/10.*CERTIFIED|✅.*certif', _re.IGNORECASE)

    if _night_process.stdout:
        async for raw_line in _night_process.stdout:
            try:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                line = repr(raw_line)
            logger.info("[NR-OUT] %s", line)

            if "[PATCH_READY]" in line:
                asyncio.create_task(_emit_patch_approval())

            # -- Cycle progress → NightRunnerWidget
            m = _cycle_re.search(line)
            if m:
                await sio.emit("nightrunner_cycle", {
                    "cycle": int(m.group(1)),
                    "total": int(m.group(2)),
                })
                continue

            # -- Topic selected → NightRunnerWidget
            m = _topic_re.search(line)
            if m:
                await sio.emit("nightrunner_topic", {"topic": m.group(1).strip()})
                continue

            # -- Study phase progress → StudyWidget
            m = _study_re.search(line)
            if m:
                pct, phase, msg = int(m.group(1)), m.group(2), m.group(3).strip()
                await sio.emit("study_progress", {
                    "phase": phase,
                    "percentage": pct,
                    "message": msg,
                    "topic": "",   # filled by nightrunner_topic event
                })
                continue

            # -- Certification → StudyWidget complete
            if _certif_re.search(line):
                score_m = _re.search(r'score=(\d+(?:\.\d+)?)/10', line)
                score = float(score_m.group(1)) if score_m else 0
                await sio.emit("study_complete", {"score": score, "topic": "", "data": {}})

    await _night_process.wait()
    returncode = _night_process.returncode
    _night_process = None
    state = "crashed" if returncode not in (0, None) else "finished"
    await sio.emit("nightrunner_state_changed", {"running": False, "state": state})
    await sio.emit("nightrunner_cycle", {"cycle": 0, "total": 0})
    logger.info(f"[NIGHT RUNNER] Subprocess ended — state: {state} (rc={returncode})")


async def _emit_patch_approval():
    """Read pending_patch.json and emit patch_approval_required to the frontend.

    Enriches the payload with a static PatchSimulator risk assessment
    (no LLM call — instant) so the human sees risk info immediately.
    """
    try:
        from proactive_refactor import ProactiveRefactor, _ROOT
        patch = ProactiveRefactor.get_pending_patch()
        if patch:
            # Static simulation (no LLM — instant risk estimate)
            try:
                from patch_simulator import simulate_patch_sync
                file_path = _ROOT / patch["file"]
                old_code = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
                new_code = old_code
                for change in patch.get("changes", []):
                    new_code = new_code.replace(change["old"], change["new"], 1)
                sim = simulate_patch_sync(str(file_path), old_code, new_code)
                patch["simulation"] = {
                    "risk_level": sim.risk_level,
                    "recommendation": sim.recommendation,
                    "affected_modules": sim.affected_modules[:8],
                    "changes_detected": sim.changes_detected[:5],
                    "summary": sim.summary,
                }
                logger.info("[PATCH_SIM] Static risk for %s: %s", patch["file"], sim.risk_level)
            except Exception as _se:
                logger.debug("[PATCH_SIM] Static sim skipped: %s", _se)

            await sio.emit("patch_approval_required", patch)
            logger.info("[PROACTIVE] patch_approval_required emitted to frontend.")
    except Exception as exc:
        logger.warning("[PROACTIVE] Could not emit patch_approval_required: %s", exc)


class NightRunnerParams(BaseModel):
    cycles: int = 10
    timeout: int = 120
    pause: int = 10


# ── Benchmark API ──────────────────────────────────────────────────────────────

BENCHMARK_TASKS = {
    "ghost_bug":  Path(ROOT_DIR) / "benchmark" / "task_02_ghost_bug",
    "dirty_data": Path(ROOT_DIR) / "benchmark" / "task_03_dirty_data",
    "bank_race":  Path(ROOT_DIR) / "benchmark" / "task_04_race_condition",
}

class BenchmarkStartRequest(BaseModel):
    tasks: list = ["ghost_bug", "dirty_data", "bank_race"]
    max_attempts: int = 8
    use_episodic_memory: bool = False
    use_swarm: bool = False

_benchmark_task_handle = None


async def _run_benchmark_bg(task_keys: list, max_attempts: int, use_episodic_memory: bool = False, use_swarm: bool = False):
    from benchmark_loop import run_benchmark_loop

    await sio.emit("benchmark_event", {"type": "start", "tasks": task_keys})
    results = []

    for key in task_keys:
        task_dir = BENCHMARK_TASKS[key]
        # Friendly display name
        display = {"ghost_bug": "Ghost Bug", "dirty_data": "Dirty Data", "bank_race": "Bank Race"}.get(key, key)

        # Read source file for diff
        try:
            source_files = sorted(
                f for f in task_dir.glob("*.py")
                if not f.name.startswith("test_") and not f.name.startswith("__")
            )
            source_code = source_files[0].read_text(encoding="utf-8") if source_files else ""
        except Exception:
            source_code = ""

        await sio.emit("benchmark_event", {
            "type": "task_start", "task": key, "display": display,
        })

        async def progress_cb(data, _key=key, _display=display):
            await sio.emit("benchmark_event", {
                "type": "attempt_event", "task": _key, "display": _display, **data,
            })

        try:
            result = await run_benchmark_loop(
                task_dir, max_attempts=max_attempts,
                progress_cb=progress_cb,
                use_episodic_memory=use_episodic_memory,
                use_swarm=use_swarm,
            )
        except asyncio.CancelledError:
            await sio.emit("benchmark_event", {"type": "cancelled"})
            return
        except Exception as e:
            await sio.emit("benchmark_event", {
                "type": "task_error", "task": key, "display": display, "error": str(e),
            })
            continue

        entry = {
            "task": key, "display": display,
            "success": result.success,
            "attempts": result.total_attempts,
            "elapsed": round(result.elapsed_total, 1),
            "source_code": source_code,
            "fixed_code": result.final_code or "",
        }
        results.append(entry)
        await sio.emit("benchmark_event", {"type": "task_done", **entry})

    await sio.emit("benchmark_event", {"type": "all_done", "results": results})


@app.post("/api/benchmark/start")
async def start_benchmark(req: BenchmarkStartRequest):
    global _benchmark_task_handle
    if _benchmark_task_handle and not _benchmark_task_handle.done():
        return {"ok": False, "error": "Benchmark already running"}
    valid = [k for k in req.tasks if k in BENCHMARK_TASKS]
    if not valid:
        return {"ok": False, "error": "No valid tasks specified"}
    _benchmark_task_handle = asyncio.create_task(
        _run_benchmark_bg(valid, req.max_attempts, req.use_episodic_memory, req.use_swarm)
    )
    return {"ok": True, "tasks": valid}


@app.post("/api/benchmark/stop")
async def stop_benchmark():
    global _benchmark_task_handle
    if _benchmark_task_handle and not _benchmark_task_handle.done():
        _benchmark_task_handle.cancel()
        await sio.emit("benchmark_event", {"type": "cancelled"})
        return {"ok": True}
    return {"ok": False, "error": "No benchmark running"}


@app.post("/api/night_runner/start")
async def start_night_runner(params: NightRunnerParams):
    global _night_process
    if _night_process and _night_process.returncode is None:
        return {"ok": False, "error": "NightRunner already running"}

    # Safety net: if an audio session lock was left stale (e.g. browser closed without
    # stop_audio), force-release it now. The user explicitly requested NightRunner.
    global _session_lock_held
    if is_file_locked():
        reason = get_lock_reason()
        logger.warning("[NIGHT RUNNER] Stale lock detected (reason: %s) — force-releasing before start.", reason)
        try:
            release_file_lock()
        except Exception:
            pass
    if _session_lock_held:
        try:
            SHARD_SESSION_LOCK.release()
        except Exception:
            pass
        _session_lock_held = False

    script = Path(BACKEND_DIR) / "night_runner.py"
    cmd = [
        sys.executable, str(script),
        "--cycles",  str(params.cycles),
        "--timeout", str(params.timeout),
        "--pause",   str(params.pause),
    ]
    try:
        _night_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=ROOT_DIR,  # must match terminal launch dir so relative paths resolve correctly
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    asyncio.create_task(_monitor_night_process())
    await sio.emit("nightrunner_state_changed", {"running": True, "state": "running"})

    # Annuncio vocale di avvio
    greeting = (
        "Sessione NightRunner avviata, signore. "
        f"Eseguirò {params.cycles} cicli di studio autonomo. "
        "Le farò un resoconto appena terminata."
    )
    core = _shard_core if _shard_core is not None else audio_loop
    if core is not None and hasattr(core, "session") and core.session:
        try:
            await core.session.send(input=greeting, end_of_turn=True)
        except Exception:
            await sio.emit("shard_voice_event", {"text": greeting, "priority": "high", "event_type": "session_start"})
    else:
        await sio.emit("shard_voice_event", {"text": greeting, "priority": "high", "event_type": "session_start"})

    logger.info(f"[NIGHT RUNNER] Subprocess started — PID {_night_process.pid}")
    return {"ok": True, "pid": _night_process.pid}


@app.post("/api/night_runner/stop")
async def stop_night_runner():
    global _night_process
    if _night_process is None or _night_process.returncode is not None:
        return {"ok": False, "error": "NightRunner not running"}
    try:
        _night_process.terminate()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    await sio.emit("nightrunner_state_changed", {"running": False, "state": "stopped"})
    return {"ok": True}


# ── GUI Dashboard Endpoints ────────────────────────────────────────────────────

@app.get("/api/night_recap")
async def night_recap():
    """Last NightRunner session summary for the Night Shift Recap widget."""
    reports_dir = Path(ROOT_DIR) / "night_reports"
    try:
        sessions = sorted(reports_dir.glob("session_*.json"))
        if not sessions:
            return {"available": False}
        data = json.loads(sessions[-1].read_text(encoding="utf-8"))
        cycles = data.get("cycles", [])
        skills_start = cycles[0].get("skills_before", 0) if cycles else 0
        skills_end   = cycles[-1].get("skills_after", skills_start) if cycles else skills_start
        certified    = [c for c in cycles if c.get("certified")]
        return {
            "available":    True,
            "date":         data.get("date", ""),
            "runtime_min":  round(data.get("total_runtime_minutes", 0), 1),
            "total_cycles": len(cycles),
            "certified":    len(certified),
            "skills_start": skills_start,
            "skills_end":   skills_end,
            "skills_gained":skills_end - skills_start,
            "top_cycle":    max(cycles, key=lambda c: c.get("score", 0), default={}) if cycles else {},
            "cycles":       cycles,
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


@app.get("/api/improvement_queue")
async def improvement_queue():
    """ImprovementEngine queue + top chronic failures for the Clinica widget."""
    try:
        from improvement_engine import ImprovementEngine
        engine = ImprovementEngine()
        status = engine.get_status()

        # Also surface top ticket data from last SelfAnalyzer run (from queue state)
        return {
            "available":      True,
            "queue":          status["pending_queue"],
            "queue_size":     status["queue_size"],
            "last_run_at":    status["last_run_at"],
            "total_queued":   status["total_ever_queued"],
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


@app.get("/api/consciousness/thought_stats")
async def thought_stats():
    """Metriche di interpretabilità sui pensieri di SHARD — per pitch e debug."""
    if audio_loop and hasattr(audio_loop, 'consciousness'):
        return audio_loop.consciousness.self_logger.get_stats()
    return {"total": 0, "summary": "SHARD non ancora inizializzato."}

@app.get("/api/consciousness/reasoning_stats")
async def reasoning_stats():
    """Audit trail ragionamenti interni di SHARD — per pitch e debug."""
    if audio_loop and hasattr(audio_loop, 'consciousness'):
        return audio_loop.consciousness.interpretability.get_stats()
    return {"total": 0, "summary": "SHARD non ancora inizializzato."}

@app.get("/api/brain_graph")
async def brain_graph():
    """Brain Graph data — nodes (skills) + edges (requires/improves) for 3D visualization."""
    import json, os
    from datetime import datetime

    cap_path = os.path.join(os.path.dirname(__file__), "..", "shard_memory", "capability_graph.json")
    meta_path = os.path.join(os.path.dirname(__file__), "..", "shard_memory", "meta_learning.json")

    try:
        with open(cap_path, encoding="utf-8") as f:
            cap = json.load(f)
    except Exception:
        cap = {}

    score_map = {}
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        for entry in meta.get("sessions", []):
            raw_topic = entry.get("topic", "")
            s = entry.get("score")
            if not raw_topic or s is None:
                continue
            score = float(s)
            # Session topics can be composite: "A applied to B" — split and score all parts
            parts = [p.strip() for p in raw_topic.replace(" applied to ", "\n").splitlines()]
            for part in parts:
                if part and (part not in score_map or score_map[part] < score):
                    score_map[part] = score
    except Exception:
        pass

    nodes = []
    links = []
    seen_links = set()

    for name, data in cap.items():
        score = score_map.get(name, 0)
        certified = score >= 7.0
        acquired = data.get("acquired", "")
        nodes.append({
            "id": name,
            "label": name,
            "score": round(score, 1),
            "certified": certified,
            "acquired": acquired[:10] if acquired else "",
            "requires_count": len(data.get("requires", [])),
        })
        for req in data.get("requires", []):
            key = (req, name)
            if key not in seen_links and req in cap:
                links.append({"source": req, "target": name, "type": "requires"})
                seen_links.add(key)

    return {"nodes": nodes, "links": links, "total": len(nodes)}


@app.get("/api/knowledge/graph_stats")
async def knowledge_graph_stats():
    """Statistiche GraphRAG — relazioni causali tra concetti."""
    try:
        from graph_rag import get_graph_stats
        return get_graph_stats()
    except Exception as exc:
        return {"total_relations": 0, "error": str(exc)}

@app.get("/api/llm/cache_stats")
async def llm_cache_stats():
    """LLM cache hit/miss stats."""
    try:
        from llm_cache import get_cache_stats
        return get_cache_stats()
    except Exception as exc:
        return {"entries_in_memory": 0, "error": str(exc)}

@app.post("/api/llm/cache_invalidate")
async def llm_cache_invalidate():
    """Svuota la LLM cache (utile dopo modifiche al codice)."""
    try:
        from llm_cache import invalidate_all
        invalidate_all()
        return {"status": "ok", "message": "Cache invalidated"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

@app.get("/api/skill_radar")
async def skill_radar():
    """Per-category scores for the Skill Radar widget (recharts RadarChart)."""
    from meta_learning import TOPIC_CATEGORIES
    from shard_db import get_db
    try:
        conn = get_db()
        gs_row = conn.execute("SELECT * FROM global_stats").fetchone()
        cat_rows = conn.execute("SELECT * FROM category_stats").fetchall()
        score_rows = conn.execute(
            "SELECT score FROM experiments WHERE score IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT 20"
        ).fetchall()

        cats = {r["category"]: r for r in cat_rows}
        all_cats = list(TOPIC_CATEGORIES.keys()) + ["general"]
        data = []
        for cat in all_cats:
            info = cats.get(cat)
            data.append({
                "category":  cat.replace("_", " ").title(),
                "key":       cat,
                "avg_score": round(float(info["avg_score"] or 0), 1) if info else 0.0,
                "sessions":  info["total"] if info else 0,
                "cert_rate": round(float(info["cert_rate"] or 0) * 100, 1) if info else 0.0,
            })

        data.sort(key=lambda x: -x["avg_score"])

        # Best/worst (min 3 sessions)
        significant = [d for d in data if d["sessions"] >= 3]
        best = max(significant, key=lambda x: x["avg_score"])["key"] if significant else ""
        worst = min(significant, key=lambda x: x["avg_score"])["key"] if significant else ""

        # Score trend (linear slope)
        from meta_learning import _linear_trend
        scores = [r["score"] for r in reversed(score_rows)]
        trend = _linear_trend(scores)

        return {
            "available":  True,
            "categories": data,
            "global": {
                "avg_score":      round(float(gs_row["avg_score"] or 0), 1) if gs_row else 0.0,
                "cert_rate":      round(float(gs_row["cert_rate"] or 0) * 100, 1) if gs_row else 0.0,
                "total_sessions": gs_row["total_sessions"] if gs_row else 0,
                "best":           best,
                "worst":          worst,
                "trend":          trend,
            },
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


# ── SSJ4 Phase 3: Proactive Self-Optimization Gate ────────────────────────────

@app.get("/api/patch/pending")
async def get_pending_patch():
    """Return the current pending patch proposal, or {available: false}."""
    try:
        from proactive_refactor import ProactiveRefactor
        patch = ProactiveRefactor.get_pending_patch()
        if patch:
            return {"available": True, "patch": patch}
        return {"available": False}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


@app.post("/api/patch/notify")
async def notify_pending_patch():
    """Emit patch_approval_required via Socket.IO if a pending patch exists.
    Called by test scripts and by the frontend to re-surface a missed notification.
    """
    await _emit_patch_approval()
    try:
        from proactive_refactor import ProactiveRefactor
        found = ProactiveRefactor.get_pending_patch() is not None
    except Exception:
        found = False
    return {"ok": True, "patch_found": found}


@app.post("/api/patch/simulate")
async def simulate_pending_patch():
    """Run full PatchSimulator (static + LLM) on the pending patch.

    Returns SimulationReport with risk_level, affected_modules, module_risks.
    Async — may take 10-20s (parallel LLM calls for each dependent module).
    """
    try:
        from proactive_refactor import ProactiveRefactor, _ROOT
        from patch_simulator import simulate_patch

        patch_record = ProactiveRefactor.get_pending_patch()
        if not patch_record:
            return {"success": False, "message": "No pending patch found."}

        file_path = _ROOT / patch_record["file"]
        old_code = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        new_code = old_code
        for change in patch_record.get("changes", []):
            new_code = new_code.replace(change["old"], change["new"], 1)

        sim = await simulate_patch(str(file_path), old_code, new_code)
        return {
            "success": True,
            "risk_level": sim.risk_level,
            "recommendation": sim.recommendation,
            "affected_modules": sim.affected_modules,
            "changes_detected": sim.changes_detected,
            "module_risks": sim.module_risks,
            "summary": sim.summary,
        }
    except Exception as exc:
        logger.error("[PATCH_SIM] simulate endpoint error: %s", exc)
        return {"success": False, "error": str(exc)}


@app.post("/api/patch/approve")
async def approve_patch():
    """Apply the pending patch to the target source file, after Impact Analyzer check."""
    try:
        from proactive_refactor import ProactiveRefactor, PENDING_PATCH_PATH, _ROOT
        from impact_analyzer import pre_check

        # 1. Read and simulate the patched content for Impact Analyzer
        patch_record = ProactiveRefactor.get_pending_patch()
        if not patch_record:
            return {"success": False, "message": "No pending patch found."}

        file_path = _ROOT / patch_record["file"]
        source = file_path.read_text(encoding="utf-8")
        simulated = source
        for change in patch_record.get("changes", []):
            simulated = simulated.replace(change["old"], change["new"], 1)

        # 2. Impact Analyzer gate — BLOCK stops the apply
        check = await pre_check(str(file_path), simulated)
        _interp = getattr(getattr(audio_loop, 'consciousness', None), 'interpretability', None)
        if check["risk"] == "BLOCK":
            logger.error("[PROACTIVE] Impact Analyzer BLOCKED patch: %s", check["reason"])
            if _interp:
                _interp.log_patch_decision(patch_record["file"], "BLOCK", False, check["reason"])
            return {"success": False, "message": f"Blocked by Impact Analyzer: {check['reason']}"}
        if check["risk"] in ("HIGH", "MEDIUM"):
            logger.warning("[PROACTIVE] Impact Analyzer %s: %s — applying anyway (human approved).",
                           check["risk"], check["reason"])

        # 3. Apply
        result = ProactiveRefactor(think_fn=lambda p: None).apply_pending_patch()
        if _interp:
            _interp.log_patch_decision(
                patch_record["file"], check["risk"],
                result.get("success", False),
                result.get("message", "")
            )
        if result["success"]:
            await sio.emit("patch_applied", {"message": result["message"]})
            logger.info("[PROACTIVE] Patch approved and applied: %s", result["message"])
        return result
    except Exception as exc:
        logger.error("[PROACTIVE] approve_patch error: %s", exc)
        return {"success": False, "message": str(exc)}


@app.post("/api/patch/reject")
async def reject_patch():
    """Discard the pending patch without applying it."""
    try:
        from proactive_refactor import ProactiveRefactor
        result = ProactiveRefactor(think_fn=lambda p: None).discard_pending_patch()
        await sio.emit("patch_rejected", {"message": result["message"]})
        logger.info("[PROACTIVE] Patch rejected.")
        return result
    except Exception as exc:
        logger.error("[PROACTIVE] reject_patch error: %s", exc)
        return {"success": False, "message": str(exc)}


@app.get("/api/meta_learning/stats")
async def meta_learning_stats(topic: str = ""):
    """Full meta-learning statistics + best strategy suggestion.

    Optional query param ?topic=<string> returns a category-specific suggestion.
    """
    try:
        from meta_learning import MetaLearning, META_DB_PATH
        from strategy_memory import StrategyMemory

        if not META_DB_PATH.exists():
            return {"available": False}

        sm = StrategyMemory()
        ml = MetaLearning(strategy_memory=sm)
        stats = ml.get_stats()
        suggestion = ml.suggest_best_strategy(topic or None)

        return {
            "available":   True,
            "global":      stats.get("global", {}),
            "categories":  stats.get("categories", {}),
            "suggestion":  suggestion,
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


if __name__ == "__main__":
    uvicorn.run(
        "server:app_socketio",
        host="127.0.0.1",
        port=8000,
        reload=False,
        loop="asyncio",
        reload_excludes=["temp_cad_gen.py", "output.stl", "*.stl"]
    )
