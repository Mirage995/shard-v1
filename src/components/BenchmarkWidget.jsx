import { useState, useEffect, useRef } from 'react';
import { useDraggable } from '../hooks/useDraggable';

const TASKS = [
    { key: 'ghost_bug',  label: 'Ghost Bug',   desc: '5 runtime-only bugs' },
    { key: 'dirty_data', label: 'Dirty Data',  desc: '10K dirty transactions' },
    { key: 'bank_race',  label: 'Bank Race',   desc: 'Race condition under concurrency' },
];

const cyan   = '#22d3ee';
const green  = '#4ade80';
const red    = '#f87171';
const yellow = '#fbbf24';
const dim    = 'rgba(103,232,249,0.45)';

export default function BenchmarkWidget({ socket }) {
    const { dragStyles, dragHandleProps } = useDraggable('benchmark-widget', {
        defaultPos: { offsetX: 16, offsetY: 290 }, anchor: 'bottom-right'
    });
    const [open, setOpen]               = useState(false);
    const [selected, setSelected]       = useState(new Set(['ghost_bug', 'dirty_data', 'bank_race']));
    const [maxAttempts, setMaxAttempts]           = useState(8);
    const [episodicMemory, setEpisodicMemory]     = useState(false);
    const [useSwarm, setUseSwarm]               = useState(false);
    const [running, setRunning]         = useState(false);
    const [log, setLog]                 = useState([]);       // [{id, text, color, bold}]
    const [results, setResults]         = useState([]);       // task_done payloads
    const [diffTask, setDiffTask]       = useState(null);     // key of task to show diff for
    const [diffView, setDiffView]       = useState('fixed');  // 'source' | 'fixed'
    const logRef = useRef(null);
    const logId  = useRef(0);

    const addLog = (text, color = cyan, bold = false) => {
        setLog(prev => [...prev, { id: logId.current++, text, color, bold }]);
    };

    // Auto-scroll log
    useEffect(() => {
        if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
    }, [log]);

    useEffect(() => {
        if (!socket) return;

        const handler = (data) => {
            switch (data.type) {
                case 'start':
                    setRunning(true);
                    setResults([]);
                    setDiffTask(null);
                    setLog([]);
                    addLog(`◈ SHARD BENCHMARK — ${data.tasks.length} task(s)`, cyan, true);
                    addLog('─'.repeat(48), dim);
                    break;

                case 'task_start':
                    addLog('');
                    addLog(`▶ TASK: ${data.display.toUpperCase()}`, yellow, true);
                    break;

                case 'attempt_event': {
                    const { event, attempt, mode, success, syntax_error, passed, failed, failed_tests } = data;
                    if (event === 'attempt_start') {
                        const label = mode === 'LLM SOLO' ? 'LLM SOLO    ' : 'SHARD FEEDBACK';
                        addLog(`  [${attempt}] ${label} ⏳ calling model...`, dim);
                    } else if (event === 'attempt_done') {
                        if (syntax_error) {
                            addLog(`  [${attempt}] ✗ SYNTAX ERROR`, red);
                        } else if (success) {
                            addLog(`  [${attempt}] ✓ ALL PASSED (${passed} tests)`, green, true);
                        } else {
                            addLog(`  [${attempt}] ✗ ${passed} passed / ${failed} failed`, red);
                            if (failed_tests?.length) {
                                failed_tests.forEach(t => addLog(`       · ${t}`, red));
                            }
                        }
                    }
                    break;
                }

                case 'task_done': {
                    const { display, success, attempts, elapsed } = data;
                    const winner = success
                        ? (attempts === 1 ? `LLM SOLO (1/${maxAttempts})` : `SHARD (${attempts}/${maxAttempts})`)
                        : `FAILED (${maxAttempts}/${maxAttempts})`;
                    const col = success ? green : red;
                    addLog(`  → ${display}: ${winner} — ${elapsed}s`, col, true);
                    setResults(prev => [...prev, data]);
                    break;
                }

                case 'all_done': {
                    const { results: r } = data;
                    const shardWins  = r.filter(x => x.success && x.attempts > 1).length;
                    const soloWins   = r.filter(x => x.success && x.attempts === 1).length;
                    const total      = r.length;
                    const totalWins  = soloWins + shardWins;
                    const shardPct   = total ? Math.round(totalWins / total * 100) : 0;
                    const soloPct    = total ? Math.round(soloWins  / total * 100) : 0;
                    addLog('');
                    addLog('─'.repeat(48), dim);
                    addLog(`  LLM SOLO  : ${soloWins}/${total}  (${soloPct}%)`, soloWins === total ? green : red, true);
                    addLog(`  SHARD     : ${totalWins}/${total}  (${shardPct}%)`, totalWins === total ? green : yellow, true);
                    if (shardWins > 0) {
                        addLog(`  SHARD solved ${shardWins}/${total} tasks the LLM alone could not.`, cyan, true);
                    }
                    setRunning(false);
                    break;
                }

                case 'cancelled':
                    addLog('  ■ Benchmark cancelled.', yellow);
                    setRunning(false);
                    break;

                case 'task_error':
                    addLog(`  ERROR: ${data.display} — ${data.error}`, red);
                    break;

                default:
                    break;
            }
        };

        socket.on('benchmark_event', handler);
        return () => socket.off('benchmark_event', handler);
    }, [socket, maxAttempts]);

    const handleStart = async () => {
        if (running) return;
        try {
            const res = await fetch('http://localhost:8000/api/benchmark/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    tasks: [...selected],
                    max_attempts: maxAttempts,
                    use_episodic_memory: episodicMemory,
                    use_swarm: useSwarm,
                }),
            });
            const data = await res.json();
            if (!data.ok) addLog(`ERROR: ${data.error}`, red);
        } catch (e) {
            addLog(`Fetch error: ${e.message}`, red);
        }
    };

    const handleStop = async () => {
        try {
            await fetch('http://localhost:8000/api/benchmark/stop', { method: 'POST' });
        } catch (e) { /* ignore */ }
    };

    const toggleTask = (key) => {
        if (running) return;
        setSelected(prev => {
            const next = new Set(prev);
            next.has(key) ? next.delete(key) : next.add(key);
            return next;
        });
    };

    const diffData = diffTask ? results.find(r => r.task === diffTask) : null;

    // ── TRIGGER BUTTON (always visible) ─────────────────────────────────────
    if (!open) {
        return (
            <button
                onClick={() => setOpen(true)}
                style={{
                    ...dragStyles,
                    zIndex: 50,
                    background: 'rgba(0,0,0,0.75)',
                    border: `1px solid rgba(34,211,238,${running ? '0.7' : '0.3'})`,
                    borderRadius: '4px',
                    padding: '6px 12px',
                    fontFamily: 'monospace',
                    fontSize: '11px',
                    color: running ? cyan : 'rgba(34,211,238,0.6)',
                    cursor: 'pointer',
                    letterSpacing: '0.08em',
                    backdropFilter: 'blur(6px)',
                }}
            >
                {running
                    ? <><span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: cyan, marginRight: 6, animation: 'pulse 1.5s infinite' }} />BENCHMARK ⏳</>
                    : '◈ BENCHMARK'}
            </button>
        );
    }

    // ── FULL PANEL ───────────────────────────────────────────────────────────
    return (
        <div style={{
            ...dragStyles,
            zIndex: 50,
            width: '520px',
            background: 'rgba(0,0,0,0.88)',
            border: '1px solid rgba(34,211,238,0.3)',
            borderRadius: '6px',
            fontFamily: 'monospace',
            fontSize: '11px',
            color: cyan,
            backdropFilter: 'blur(8px)',
            display: 'flex',
            flexDirection: 'column',
            maxHeight: '80vh',
        }}>
            {/* ── HEADER ── */}
            <div style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 12px',
                borderBottom: '1px solid rgba(34,211,238,0.15)',
            }}>
                <span {...dragHandleProps}>⠿</span>
                <span style={{ color: cyan, letterSpacing: '0.1em', fontSize: '10px' }}>
                    ◈ BENCHMARK MODE
                </span>
                {running && (
                    <span style={{
                        display: 'inline-block', width: 6, height: 6,
                        borderRadius: '50%', background: cyan,
                        animation: 'pulse 1.5s infinite',
                    }} />
                )}
                <span style={{ marginLeft: 'auto', color: dim, cursor: 'pointer', fontSize: '13px' }}
                      onClick={() => setOpen(false)}>✕</span>
            </div>

            {/* ── TASK SELECTOR ── */}
            {!running && (
                <div style={{ padding: '10px 12px', borderBottom: '1px solid rgba(34,211,238,0.1)' }}>
                    <div style={{ color: dim, fontSize: '9px', marginBottom: 6, letterSpacing: '0.08em' }}>SELECT TASKS</div>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
                        {TASKS.map(t => (
                            <button key={t.key} onClick={() => toggleTask(t.key)} style={{
                                padding: '4px 10px',
                                background: selected.has(t.key) ? 'rgba(34,211,238,0.15)' : 'transparent',
                                border: `1px solid rgba(34,211,238,${selected.has(t.key) ? '0.5' : '0.2'})`,
                                borderRadius: '3px',
                                color: selected.has(t.key) ? cyan : dim,
                                fontFamily: 'monospace',
                                fontSize: '10px',
                                cursor: 'pointer',
                                letterSpacing: '0.05em',
                            }}>
                                {t.label}
                            </button>
                        ))}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ color: dim, fontSize: '9px' }}>MAX ATTEMPTS</span>
                            <input
                                type="number" min={1} max={15} value={maxAttempts}
                                onChange={e => setMaxAttempts(Number(e.target.value))}
                                style={{
                                    width: 40, padding: '2px 4px',
                                    background: 'rgba(34,211,238,0.07)',
                                    border: '1px solid rgba(34,211,238,0.2)',
                                    borderRadius: '2px',
                                    color: cyan, fontFamily: 'monospace', fontSize: '11px', outline: 'none',
                                }}
                            />
                        </div>
                        <button onClick={() => setEpisodicMemory(v => !v)} style={{
                            padding: '3px 10px',
                            background: episodicMemory ? 'rgba(251,191,36,0.15)' : 'transparent',
                            border: `1px solid rgba(251,191,36,${episodicMemory ? '0.6' : '0.2'})`,
                            borderRadius: '3px',
                            color: episodicMemory ? yellow : dim,
                            fontFamily: 'monospace', fontSize: '9px',
                            cursor: 'pointer', letterSpacing: '0.05em',
                        }}>
                            {episodicMemory ? '◈ MEMORIA ON' : '◦ MEMORIA OFF'}
                        </button>
                        <button onClick={() => setUseSwarm(v => !v)} style={{
                            padding: '3px 10px',
                            background: useSwarm ? 'rgba(34,211,238,0.15)' : 'transparent',
                            border: `1px solid rgba(34,211,238,${useSwarm ? '0.6' : '0.2'})`,
                            borderRadius: '3px',
                            color: useSwarm ? cyan : dim,
                            fontFamily: 'monospace', fontSize: '9px',
                            cursor: 'pointer', letterSpacing: '0.05em',
                        }}>
                            {useSwarm ? '◈ SWARM ON' : '◦ SWARM OFF'}
                        </button>
                    </div>
                </div>
            )}

            {/* ── START / STOP ── */}
            <div style={{ padding: '8px 12px', borderBottom: '1px solid rgba(34,211,238,0.1)' }}>
                {!running ? (
                    <button onClick={handleStart} disabled={selected.size === 0} style={{
                        width: '100%', padding: '6px 0',
                        background: selected.size === 0 ? 'rgba(34,211,238,0.03)' : 'rgba(34,211,238,0.12)',
                        border: `1px solid rgba(34,211,238,${selected.size === 0 ? '0.15' : '0.45'})`,
                        borderRadius: '3px',
                        color: selected.size === 0 ? dim : cyan,
                        fontFamily: 'monospace', fontSize: '11px',
                        letterSpacing: '0.1em', cursor: selected.size === 0 ? 'not-allowed' : 'pointer',
                    }}>
                        ▶ LANCIA AGENTE
                    </button>
                ) : (
                    <button onClick={handleStop} style={{
                        width: '100%', padding: '6px 0',
                        background: 'rgba(239,68,68,0.1)',
                        border: '1px solid rgba(239,68,68,0.4)',
                        borderRadius: '3px',
                        color: '#f87171', fontFamily: 'monospace', fontSize: '11px',
                        letterSpacing: '0.1em', cursor: 'pointer',
                    }}>
                        ■ FERMA
                    </button>
                )}
            </div>

            {/* ── LIVE LOG ── */}
            {log.length > 0 && (
                <div ref={logRef} style={{
                    flex: '1 1 auto',
                    overflowY: 'auto',
                    padding: '8px 12px',
                    maxHeight: '260px',
                    borderBottom: results.length > 0 ? '1px solid rgba(34,211,238,0.1)' : 'none',
                }}>
                    {log.map(line => (
                        <div key={line.id} style={{
                            color: line.color,
                            fontWeight: line.bold ? 700 : 400,
                            lineHeight: '1.5',
                            whiteSpace: 'pre',
                        }}>
                            {line.text || '\u00A0'}
                        </div>
                    ))}
                </div>
            )}

            {/* ── RESULTS + DIFF ── */}
            {results.length > 0 && (
                <div style={{ padding: '8px 12px' }}>
                    <div style={{ color: dim, fontSize: '9px', marginBottom: 6, letterSpacing: '0.08em' }}>
                        CODICE — seleziona task per vedere il diff
                    </div>
                    <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
                        {results.map(r => (
                            <button key={r.task} onClick={() => setDiffTask(diffTask === r.task ? null : r.task)} style={{
                                padding: '3px 8px',
                                background: diffTask === r.task ? 'rgba(34,211,238,0.15)' : 'transparent',
                                border: `1px solid rgba(${r.success ? '74,222,128' : '248,113,113'},${diffTask === r.task ? '0.6' : '0.35'})`,
                                borderRadius: '3px',
                                color: r.success ? green : red,
                                fontFamily: 'monospace', fontSize: '10px', cursor: 'pointer',
                            }}>
                                {r.display} {r.success ? '✓' : '✗'}
                            </button>
                        ))}
                    </div>

                    {diffData && (
                        <div>
                            <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                                {['source', 'fixed'].map(v => (
                                    <button key={v} onClick={() => setDiffView(v)} style={{
                                        padding: '2px 8px',
                                        background: diffView === v ? 'rgba(34,211,238,0.12)' : 'transparent',
                                        border: `1px solid rgba(34,211,238,${diffView === v ? '0.4' : '0.15'})`,
                                        borderRadius: '2px',
                                        color: diffView === v ? cyan : dim,
                                        fontFamily: 'monospace', fontSize: '9px', cursor: 'pointer',
                                        letterSpacing: '0.05em',
                                    }}>
                                        {v === 'source' ? '◦ BUGGY' : '◈ FIXED BY SHARD'}
                                    </button>
                                ))}
                            </div>
                            <pre style={{
                                margin: 0, padding: '8px',
                                background: 'rgba(0,0,0,0.5)',
                                border: '1px solid rgba(34,211,238,0.1)',
                                borderRadius: '3px',
                                color: diffView === 'fixed' ? green : '#f87171',
                                fontSize: '9.5px',
                                overflowY: 'auto',
                                maxHeight: '200px',
                                whiteSpace: 'pre',
                            }}>
                                {(diffView === 'source' ? diffData.source_code : diffData.fixed_code) || '— nessun codice disponibile —'}
                            </pre>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
