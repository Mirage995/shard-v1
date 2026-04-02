import React, { useEffect, useRef, useState } from 'react';

const MOOD_COLORS = {
    calm:       '#00b9eb',
    focused:    '#1e78ff',
    curious:    '#8c50ff',
    excited:    '#00ffb4',
    tired:      '#508cb4',
    reflective: '#b43cff',
    alert:      '#ff3c3c',
};

const MOOD_LABELS = {
    calm:       'Calm',
    focused:    'Focused',
    curious:    'Curious',
    excited:    'Excited',
    tired:      'Tired',
    reflective: 'Reflective',
    alert:      'Alert',
};

const SidebarPanel = ({ mood, messages, isConnected, isMuted, socket }) => {
    const [visible, setVisible] = useState(false);
    const [activity, setActivity] = useState('idle'); // 'speaking' | 'listening' | 'idle'
    const hideTimerRef = useRef(null);

    const color = MOOD_COLORS[mood] || MOOD_COLORS.calm;
    const msgCount = messages.length;
    const lastShardMsg = [...messages].reverse().find(m => m.sender !== 'You' && m.sender !== 'System');

    // Show sidebar on transcription, hide after 5s of silence
    useEffect(() => {
        if (!socket) return;

        const handleTranscription = (data) => {
            setVisible(true);
            setActivity(data.sender === 'You' ? 'listening' : 'speaking');

            clearTimeout(hideTimerRef.current);
            hideTimerRef.current = setTimeout(() => {
                setActivity('idle');
                setVisible(false);
            }, 5000);
        };

        socket.on('transcription', handleTranscription);
        return () => {
            socket.off('transcription', handleTranscription);
            clearTimeout(hideTimerRef.current);
        };
    }, [socket]);

    // Also show when connected and not muted
    useEffect(() => {
        if (isConnected && !isMuted) {
            setVisible(true);
        }
    }, [isConnected, isMuted]);

    return (
        <div
            className="fixed top-[68px] right-0 z-20 transition-transform duration-500 ease-in-out"
            style={{
                transform: visible ? 'translateX(0)' : 'translateX(100%)',
                width: 220,
            }}
        >
            <div
                className="m-2 rounded-xl p-4 flex flex-col gap-4"
                style={{
                    background: 'rgba(2, 13, 26, 0.55)',
                    border: `1px solid ${color}22`,
                    boxShadow: `0 0 20px ${color}11`,
                }}
            >
                {/* Mood */}
                <div className="flex flex-col gap-1">
                    <span className="text-[10px] tracking-widest font-mono opacity-40 uppercase">Mood</span>
                    <div className="flex items-center gap-2">
                        <span
                            className="w-2.5 h-2.5 rounded-full animate-pulse"
                            style={{ backgroundColor: color, boxShadow: `0 0 8px ${color}` }}
                        />
                        <span className="text-sm font-bold font-mono" style={{ color }}>
                            {MOOD_LABELS[mood] || mood}
                        </span>
                    </div>
                </div>

                {/* Activity */}
                <div className="flex flex-col gap-1">
                    <span className="text-[10px] tracking-widest font-mono opacity-40 uppercase">Status</span>
                    <div className="flex items-center gap-2">
                        {activity === 'speaking' && (
                            <>
                                <span className="w-2 h-2 rounded-full bg-green-400 animate-ping" />
                                <span className="text-xs font-mono text-green-400">Speaking</span>
                            </>
                        )}
                        {activity === 'listening' && (
                            <>
                                <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
                                <span className="text-xs font-mono text-cyan-400">Listening</span>
                            </>
                        )}
                        {activity === 'idle' && (
                            <>
                                <span className="w-2 h-2 rounded-full opacity-30" style={{ backgroundColor: color }} />
                                <span className="text-xs font-mono opacity-30" style={{ color }}>Idle</span>
                            </>
                        )}
                    </div>
                </div>

                {/* Last message preview */}
                {lastShardMsg && (
                    <div className="flex flex-col gap-1">
                        <span className="text-[10px] tracking-widest font-mono opacity-40 uppercase">Last response</span>
                        <p className="text-xs text-gray-400 leading-relaxed line-clamp-3">
                            {lastShardMsg.text.slice(0, 120)}{lastShardMsg.text.length > 120 ? '…' : ''}
                        </p>
                    </div>
                )}

                {/* Session counter */}
                <div className="flex items-center justify-between pt-1 border-t border-white/5">
                    <span className="text-[10px] font-mono opacity-30 uppercase tracking-widest">Messages</span>
                    <span className="text-xs font-mono font-bold" style={{ color }}>{msgCount}</span>
                </div>
            </div>
        </div>
    );
};

export default SidebarPanel;
