import { useState, useEffect } from 'react';
import { useDraggable } from '../hooks/useDraggable';

export default function NightRunnerWidget({ socket }) {
    const [running, setRunning] = useState(false);
    const [state, setState] = useState('idle');
    const [cycles, setCycles] = useState(10);
    const [timeout, setTimeout_] = useState(120);
    const [pause, setPause] = useState(10);
    const [loading, setLoading] = useState(false);
    const [currentCycle, setCurrentCycle] = useState(0);
    const [totalCycles, setTotalCycles] = useState(0);
    const [currentTopic, setCurrentTopic] = useState('');

    useEffect(() => {
        if (!socket) return;

        socket.on('nightrunner_state_changed', (data) => {
            setRunning(data.running);
            setState(data.state ?? (data.running ? 'running' : 'idle'));
            if (!data.running) {
                setLoading(false);
                setCurrentCycle(0);
                setTotalCycles(0);
                setCurrentTopic('');
            }
        });

        socket.on('nightrunner_cycle', (data) => {
            if (data.cycle > 0) {
                setCurrentCycle(data.cycle);
                setTotalCycles(data.total);
            }
        });

        socket.on('nightrunner_topic', (data) => {
            setCurrentTopic(data.topic || '');
        });

        return () => {
            socket.off('nightrunner_state_changed');
            socket.off('nightrunner_cycle');
            socket.off('nightrunner_topic');
        };
    }, [socket]);

    const handleStart = async () => {
        setLoading(true);
        try {
            const res = await fetch('http://localhost:8000/api/night_runner/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cycles, timeout, pause }),
            });
            const data = await res.json();
            if (!data.ok) {
                console.error('[NightRunner] Start failed:', data.error);
                setLoading(false);
            }
        } catch (e) {
            console.error('[NightRunner] Fetch error:', e);
            setLoading(false);
        }
    };

    const handleStop = async () => {
        try {
            await fetch('http://localhost:8000/api/night_runner/stop', { method: 'POST' });
        } catch (e) {
            console.error('[NightRunner] Stop error:', e);
        }
    };

    const stateColor = {
        idle:     'text-cyan-400/60',
        running:  'text-cyan-300',
        finished: 'text-green-400',
        crashed:  'text-red-400',
        stopped:  'text-yellow-400',
    }[state] ?? 'text-cyan-400/60';

    const stateLabel = {
        idle:     'IDLE',
        running:  'IN ESECUZIONE',
        finished: 'COMPLETATA',
        crashed:  'CRASH',
        stopped:  'FERMATA',
    }[state] ?? 'IDLE';

    const cycleProgress = running && totalCycles > 0
        ? Math.round((currentCycle / totalCycles) * 100)
        : 0;

    const { dragStyles, dragHandleProps } = useDraggable('night-runner-widget', {
        defaultPos: { offsetX: 16, offsetY: 16 }, anchor: 'bottom-right'
    });

    return (
        <div style={{
            ...dragStyles,
            zIndex: 50,
            background: 'rgba(0,0,0,0.75)',
            border: '1px solid rgba(34,211,238,0.3)',
            borderRadius: '4px',
            padding: '10px 14px',
            minWidth: '210px',
            fontFamily: 'monospace',
            fontSize: '11px',
            color: '#67e8f9',
            backdropFilter: 'blur(6px)',
        }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                <span {...dragHandleProps}>⠿</span>
                <span style={{ color: '#22d3ee', fontSize: '10px', letterSpacing: '0.1em' }}>
                    ◈ NIGHT RUNNER
                </span>
                <span className={stateColor} style={{ marginLeft: 'auto', fontSize: '9px', letterSpacing: '0.08em', display: 'flex', alignItems: 'center' }}>
                    {running && (
                        <span style={{
                            display: 'inline-block',
                            width: '6px', height: '6px',
                            borderRadius: '50%',
                            background: '#22d3ee',
                            marginRight: '4px',
                            animation: 'pulse 1.5s infinite',
                        }} />
                    )}
                    {stateLabel}
                </span>
            </div>

            {/* Cycle progress — solo se in esecuzione */}
            {running && totalCycles > 0 && (
                <div style={{ marginBottom: '8px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
                        <span style={{ fontSize: '9px', color: '#67e8f9', opacity: 0.6 }}>CICLO</span>
                        <span style={{ fontSize: '9px', color: '#22d3ee' }}>{currentCycle}/{totalCycles}</span>
                    </div>
                    <div style={{ width: '100%', height: '3px', background: 'rgba(34,211,238,0.1)', borderRadius: '2px', overflow: 'hidden' }}>
                        <div style={{
                            height: '100%',
                            width: `${cycleProgress}%`,
                            background: 'linear-gradient(90deg, #0891b2, #22d3ee)',
                            borderRadius: '2px',
                            transition: 'width 0.5s ease',
                        }} />
                    </div>
                </div>
            )}

            {/* Topic corrente */}
            {running && currentTopic && (
                <div style={{
                    fontSize: '9px',
                    color: '#67e8f9',
                    opacity: 0.7,
                    marginBottom: '8px',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    letterSpacing: '0.05em',
                }}>
                    ▸ {currentTopic.toUpperCase()}
                </div>
            )}

            {/* Inputs — solo se non in esecuzione */}
            {!running && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '6px', marginBottom: '8px' }}>
                    {[
                        { label: 'CICLI', value: cycles, set: setCycles, min: 1, max: 50 },
                        { label: 'TIMEOUT', value: timeout, set: setTimeout_, min: 30, max: 480 },
                        { label: 'PAUSA', value: pause, set: setPause, min: 1, max: 60 },
                    ].map(({ label, value, set, min, max }) => (
                        <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                            <span style={{ fontSize: '8px', color: '#67e8f9', opacity: 0.6 }}>{label}</span>
                            <input
                                type="number"
                                value={value}
                                min={min}
                                max={max}
                                onChange={e => set(Number(e.target.value))}
                                style={{
                                    background: 'rgba(34,211,238,0.07)',
                                    border: '1px solid rgba(34,211,238,0.2)',
                                    borderRadius: '2px',
                                    color: '#22d3ee',
                                    fontFamily: 'monospace',
                                    fontSize: '11px',
                                    padding: '2px 4px',
                                    width: '100%',
                                    outline: 'none',
                                }}
                            />
                        </div>
                    ))}
                </div>
            )}

            {/* Button */}
            {!running ? (
                <button
                    onClick={handleStart}
                    disabled={loading}
                    style={{
                        width: '100%',
                        padding: '5px 0',
                        background: loading ? 'rgba(34,211,238,0.05)' : 'rgba(34,211,238,0.12)',
                        border: '1px solid rgba(34,211,238,0.4)',
                        borderRadius: '2px',
                        color: loading ? '#67e8f9' : '#22d3ee',
                        fontFamily: 'monospace',
                        fontSize: '11px',
                        letterSpacing: '0.1em',
                        cursor: loading ? 'not-allowed' : 'pointer',
                    }}
                >
                    {loading ? 'AVVIO...' : '▶ AVVIA SESSIONE'}
                </button>
            ) : (
                <button
                    onClick={handleStop}
                    style={{
                        width: '100%',
                        padding: '5px 0',
                        background: 'rgba(239,68,68,0.1)',
                        border: '1px solid rgba(239,68,68,0.4)',
                        borderRadius: '2px',
                        color: '#f87171',
                        fontFamily: 'monospace',
                        fontSize: '11px',
                        letterSpacing: '0.1em',
                        cursor: 'pointer',
                    }}
                >
                    ■ FERMA SESSIONE
                </button>
            )}
        </div>
    );
}
