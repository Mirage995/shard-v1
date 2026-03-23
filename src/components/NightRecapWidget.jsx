import { useEffect, useState } from 'react';
import { Moon, TrendingUp, Award, Zap, WifiOff } from 'lucide-react';
import { useDraggable } from '../hooks/useDraggable';

const NightRecapWidget = ({ socket }) => {
    const [data, setData]         = useState(null);
    const [expanded, setExpanded] = useState(false);
    const [flash, setFlash]       = useState(false);
    const [offline, setOffline]   = useState(false);

    const fetchData = () =>
        fetch('http://localhost:8000/api/night_recap')
            .then(r => r.json())
            .then(d => {
                setOffline(false);
                if (d.available) setData(d);
                else setData(null);
            })
            .catch(() => setOffline(true));

    useEffect(() => { fetchData(); }, []);

    useEffect(() => {
        if (!socket) return;
        const handle = () => {
            fetchData();
            setFlash(true);
            setTimeout(() => setFlash(false), 1200);
        };
        socket.on('study_complete', handle);
        return () => socket.off('study_complete', handle);
    }, [socket]);

    // Always visible — shows offline state if backend unreachable
    const certified = data?.certified ?? 0;
    const total     = data?.total_cycles ?? 0;
    const topCycle  = data?.top_cycle || {};

    const { dragStyles, dragHandleProps } = useDraggable('night-recap-widget', {
        defaultPos: { offsetX: 20, offsetY: 20 }, anchor: 'top-right'
    });

    return (
        <div
            style={{ ...dragStyles, width: '18rem', zIndex: 9000 }}
            className="cursor-pointer pointer-events-auto"
            onClick={() => !offline && setExpanded(e => !e)}
        >
            <div className={`relative overflow-hidden rounded-xl border bg-black/75 backdrop-blur-xl p-3 transition-all duration-500 ${
                flash
                    ? 'border-green-400/60 shadow-[0_0_24px_rgba(74,222,128,0.25)]'
                    : 'border-cyan-500/20 shadow-[0_0_24px_rgba(0,242,255,0.08)]'
            }`}>

                {/* Header */}
                <div className="flex items-center gap-2 mb-2" onClick={e => e.stopPropagation()}>
                    <span {...dragHandleProps}>⠿</span>
                    <Moon size={13} className="text-cyan-400" />
                    <span className="text-[10px] font-bold tracking-[0.18em] text-cyan-300 uppercase">
                        Notte Scorsa {data ? `· ${data.date}` : ''}
                    </span>
                    {!offline && data && (
                        <span className="ml-auto text-[9px] text-cyan-500/50 font-mono">
                            {expanded ? '▲' : '▼'}
                        </span>
                    )}
                </div>

                {/* Offline state */}
                {offline && (
                    <div className="flex items-center gap-2 py-1 text-[11px] text-white/30 font-mono">
                        <WifiOff size={11} className="text-white/20" />
                        backend offline
                    </div>
                )}

                {/* No data yet */}
                {!offline && !data && (
                    <div className="text-[11px] text-white/30 font-mono py-1">
                        Nessuna sessione notturna trovata.
                    </div>
                )}

                {/* Stats row */}
                {data && (
                    <>
                        <div className="grid grid-cols-3 gap-2 mb-2">
                            <Stat icon={<Zap size={10} />} label="Skills" value={`+${data.skills_gained}`} color="text-cyan-300" />
                            <Stat icon={<Award size={10} />} label="Cert." value={`${certified}/${total}`} color="text-green-400" />
                            <Stat icon={<TrendingUp size={10} />} label="Min" value={data.runtime_min} color="text-cyan-400" />
                        </div>

                        {topCycle.topic && (
                            <div className="rounded-lg bg-cyan-500/5 border border-cyan-500/10 px-2 py-1.5">
                                <div className="text-[9px] text-cyan-500/60 font-mono uppercase tracking-wider mb-0.5">
                                    Best session
                                </div>
                                <div className="text-[11px] text-white/80 font-mono truncate">
                                    {topCycle.topic}
                                </div>
                                <div className="text-[10px] font-bold mt-0.5"
                                    style={{ color: topCycle.score >= 7.5 ? '#4ade80' : topCycle.score >= 6 ? '#facc15' : '#f87171' }}>
                                    Score: {topCycle.score}/10
                                </div>
                            </div>
                        )}

                        {expanded && data.cycles?.length > 0 && (
                            <div className="mt-2 space-y-1 max-h-48 overflow-y-auto">
                                {data.cycles.map((c, i) => (
                                    <div key={i} className="flex items-center gap-2 px-1 py-0.5 rounded text-[10px] font-mono">
                                        <span className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                                            style={{ backgroundColor: c.certified ? '#4ade80' : c.score >= 6 ? '#facc15' : '#f87171' }} />
                                        <span className="text-white/60 truncate flex-1">{c.topic}</span>
                                        <span className="text-cyan-400/80 flex-shrink-0">{c.score}/10</span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
};

const Stat = ({ icon, label, value, color }) => (
    <div className="flex flex-col items-center rounded-lg bg-white/3 py-1.5 gap-0.5">
        <span className="text-cyan-500/60">{icon}</span>
        <span className={`text-sm font-bold font-mono ${color}`}>{value}</span>
        <span className="text-[9px] text-white/40 uppercase tracking-wider">{label}</span>
    </div>
);

export default NightRecapWidget;
