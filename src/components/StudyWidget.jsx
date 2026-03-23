import React, { useState, useEffect, useRef } from 'react';

const StudyWidget = ({ socket }) => {
    const [status, setStatus] = useState({
        phase: '',
        percentage: 0,
        message: '',
        visible: false,
        complete: false,
        topic: '',
    });
    const displayPct = useRef(0);

    useEffect(() => {
        if (!socket) return;

        const handleProgress = (data) => {
            // Prevent regression: never go below current displayed value
            const incomingPct = data.percentage ?? data.pct ?? 0;
            const safePct = Math.max(displayPct.current, incomingPct);
            displayPct.current = safePct;

            setStatus({
                phase: data.phase,
                percentage: safePct,
                message: data.message,
                topic: data.topic || '',
                visible: true,
                complete: false,
            });
        };

        const handleComplete = (data) => {
            displayPct.current = 100;
            setStatus(prev => ({
                ...prev,
                phase: 'CERTIFIED',
                percentage: 100,
                message: `Score: ${data.score}/10`,
                complete: true,
            }));
            setTimeout(() => {
                setStatus(prev => ({ ...prev, visible: false }));
                displayPct.current = 0;
            }, 8000);
        };

        socket.on('study_progress', handleProgress);
        socket.on('study_complete', handleComplete);

        return () => {
            socket.off('study_progress', handleProgress);
            socket.off('study_complete', handleComplete);
        };
    }, [socket]);

    if (!status.visible) return null;

    const pct = status.percentage;
    const isComplete = status.complete;

    return (
        <div className="fixed bottom-36 right-5 w-80 z-[10000] pointer-events-auto">
            {/* Glass container */}
            <div className="relative overflow-hidden rounded-xl border border-cyan-500/30 bg-black/80 backdrop-blur-xl shadow-[0_0_30px_rgba(0,242,255,0.15)] p-4">
                {/* Animated glow border */}
                <div
                    className="absolute inset-0 rounded-xl pointer-events-none"
                    style={{
                        background: isComplete
                            ? 'linear-gradient(135deg, rgba(57,255,20,0.08), transparent)'
                            : 'linear-gradient(135deg, rgba(0,242,255,0.06), transparent)',
                    }}
                />

                {/* Header */}
                <div className="flex items-center justify-between mb-1 relative z-10">
                    <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${isComplete ? 'bg-green-400' : 'bg-cyan-400 animate-pulse'}`} />
                        <span className="text-[11px] font-bold tracking-[0.15em] text-cyan-300 uppercase">
                            {status.phase || 'STUDY'}
                        </span>
                    </div>
                    <span className={`text-sm font-mono font-bold ${isComplete ? 'text-green-400' : 'text-cyan-300'}`}>
                        {pct}%
                    </span>
                </div>

                {/* Topic */}
                {status.topic && (
                    <div className="text-[10px] text-cyan-500/60 font-mono tracking-wider mb-2 truncate relative z-10">
                        ◈ {status.topic.toUpperCase()}
                    </div>
                )}

                {/* Progress Bar */}
                <div className="relative w-full h-2 bg-white/5 rounded-full overflow-hidden mb-2">
                    {/* Track glow */}
                    <div
                        className="absolute inset-y-0 left-0 rounded-full transition-all duration-700 ease-out"
                        style={{
                            width: `${pct}%`,
                            background: isComplete
                                ? 'linear-gradient(90deg, #22c55e, #39ff14)'
                                : 'linear-gradient(90deg, #0891b2, #00f2ff, #67e8f9)',
                            boxShadow: isComplete
                                ? '0 0 12px rgba(57,255,20,0.6)'
                                : '0 0 12px rgba(0,242,255,0.5)',
                        }}
                    />
                    {/* Shimmer effect on bar */}
                    {!isComplete && pct > 0 && pct < 100 && (
                        <div
                            className="absolute inset-y-0 left-0 rounded-full animate-pulse opacity-40"
                            style={{
                                width: `${pct}%`,
                                background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent)',
                            }}
                        />
                    )}
                </div>

                {/* Message */}
                <div className="text-[11px] text-white/70 font-mono truncate relative z-10">
                    {status.message}
                </div>
            </div>
        </div>
    );
};

export default StudyWidget;