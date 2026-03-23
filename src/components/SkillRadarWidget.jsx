import { useEffect, useState } from 'react';
import {
    RadarChart, Radar, PolarGrid, PolarAngleAxis,
    ResponsiveContainer, Tooltip,
} from 'recharts';
import { Brain, WifiOff } from 'lucide-react';

const SkillRadarWidget = ({ socket }) => {
    const [data, setData]       = useState(null);
    const [visible, setVisible] = useState(false);
    const [pulse, setPulse]     = useState(false);
    const [offline, setOffline] = useState(false);

    const fetchData = () =>
        fetch('http://localhost:8000/api/skill_radar')
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
            setPulse(true);
            setTimeout(() => setPulse(false), 1200);
        };
        socket.on('study_complete', handle);
        return () => socket.off('study_complete', handle);
    }, [socket]);

    const chartData = data
        ? data.categories.map(c => ({
            subject:  c.category.length > 9 ? c.category.slice(0, 9) + '…' : c.category,
            fullKey:  c.category,
            score:    c.avg_score,
            sessions: c.sessions,
            cert:     c.cert_rate,
            fullMark: 10,
        }))
        : [];

    const g = data?.global || {};
    const trendArrow = g.trend > 0.05 ? '↑' : g.trend < -0.05 ? '↓' : '→';
    const trendColor = g.trend > 0.05 ? '#4ade80' : g.trend < -0.05 ? '#f87171' : '#22d3ee';

    return (
        <>
            {/* Toggle button — always visible */}
            <button
                onClick={() => setVisible(v => !v)}
                className={`fixed bottom-5 left-28 z-[9500] pointer-events-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg border bg-black/75 backdrop-blur-xl transition-all duration-500 ${
                    offline       ? 'border-white/10' :
                    pulse         ? 'border-green-400/60 shadow-[0_0_12px_rgba(74,222,128,0.3)]' :
                                    'border-cyan-500/30 hover:border-cyan-400/60'
                }`}
            >
                <Brain size={12} className={offline ? 'text-white/30' : pulse ? 'text-green-400' : 'text-cyan-400'} />
                <span className={`text-[10px] font-bold tracking-wider uppercase ${
                    offline ? 'text-white/30' : pulse ? 'text-green-300' : 'text-cyan-300'
                }`}>
                    Skill Radar
                </span>
            </button>

            {visible && (
                <div className="fixed bottom-14 left-28 w-80 z-[9500] pointer-events-auto">
                    <div className="rounded-xl border border-cyan-500/20 bg-black/85 backdrop-blur-xl shadow-[0_0_30px_rgba(0,242,255,0.10)] overflow-hidden">

                        {/* Header */}
                        <div className="flex items-center justify-between px-4 py-2.5 border-b border-cyan-500/10">
                            <div className="flex items-center gap-2">
                                <Brain size={12} className="text-cyan-400" />
                                <span className="text-[11px] font-bold tracking-widest text-cyan-300 uppercase">
                                    Radar Competenze
                                </span>
                            </div>
                            <button onClick={() => setVisible(false)} className="text-white/30 hover:text-white/60 text-xs">✕</button>
                        </div>

                        {/* Offline */}
                        {offline && (
                            <div className="px-4 py-8 flex flex-col items-center gap-2 text-[11px] text-white/30 font-mono">
                                <WifiOff size={18} className="text-white/15" />
                                Backend offline.
                            </div>
                        )}

                        {/* No data yet */}
                        {!offline && !data && (
                            <div className="px-4 py-8 text-center text-[11px] text-white/30 font-mono">
                                Nessun dato di studio ancora.<br />
                                <span className="text-white/20">Il radar si popola dopo il primo ciclo notturno.</span>
                            </div>
                        )}

                        {/* Data available */}
                        {!offline && data && (
                            <>
                                {/* Global stats */}
                                <div className="flex items-center justify-around px-4 py-2 border-b border-white/5 text-center">
                                    <GlobalStat label="Avg Score" value={g.avg_score?.toFixed(1)} color="text-cyan-300" />
                                    <GlobalStat label="Cert Rate" value={`${g.cert_rate?.toFixed(0)}%`} color="text-green-400" />
                                    <GlobalStat label="Sessions" value={g.total_sessions} color="text-cyan-400" />
                                    <div className="flex flex-col items-center">
                                        <span className="text-base font-bold font-mono" style={{ color: trendColor }}>{trendArrow}</span>
                                        <span className="text-[9px] text-white/30 uppercase tracking-wider">Trend</span>
                                    </div>
                                </div>

                                {/* Radar chart */}
                                <div className="px-2 py-3" style={{ height: 230 }}>
                                    <ResponsiveContainer width="100%" height="100%">
                                        <RadarChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 16 }}>
                                            <PolarGrid stroke="rgba(0,242,255,0.10)" gridType="polygon" />
                                            <PolarAngleAxis
                                                dataKey="subject"
                                                tick={{ fill: 'rgba(0,242,255,0.55)', fontSize: 9, fontFamily: 'monospace' }}
                                                tickLine={false}
                                            />
                                            <Radar
                                                name="Score"
                                                dataKey="score"
                                                stroke="#00f2ff"
                                                fill="#00f2ff"
                                                fillOpacity={0.15}
                                                strokeWidth={1.5}
                                                dot={{ r: 2.5, fill: '#00f2ff', strokeWidth: 0 }}
                                            />
                                            <Tooltip content={<RadarTooltip />} />
                                        </RadarChart>
                                    </ResponsiveContainer>
                                </div>

                                {/* Best / Worst */}
                                <div className="flex divide-x divide-white/5 border-t border-white/5">
                                    <CalloutCell label="Migliore" value={g.best?.replace(/_/g, ' ')} color="#4ade80" />
                                    <CalloutCell label="Da migliorare" value={g.worst?.replace(/_/g, ' ')} color="#f87171" />
                                </div>
                            </>
                        )}
                    </div>
                </div>
            )}
        </>
    );
};

const GlobalStat = ({ label, value, color }) => (
    <div className="flex flex-col items-center">
        <span className={`text-sm font-bold font-mono ${color}`}>{value ?? '—'}</span>
        <span className="text-[9px] text-white/30 uppercase tracking-wider">{label}</span>
    </div>
);

const CalloutCell = ({ label, value, color }) => (
    <div className="flex-1 px-3 py-2 text-center">
        <div className="text-[9px] text-white/30 uppercase tracking-wider mb-0.5">{label}</div>
        <div className="text-[11px] font-mono font-bold capitalize" style={{ color }}>{value || '—'}</div>
    </div>
);

const RadarTooltip = ({ active, payload }) => {
    if (!active || !payload?.length) return null;
    const d = payload[0]?.payload;
    return (
        <div className="rounded-lg border border-cyan-500/20 bg-black/90 backdrop-blur px-3 py-2 text-[11px] font-mono">
            <div className="text-cyan-300 font-bold mb-1">{d?.fullKey}</div>
            <div className="text-white/70">Score: <span className="text-cyan-300">{d?.score}/10</span></div>
            <div className="text-white/70">Sessions: <span className="text-cyan-300">{d?.sessions}</span></div>
            <div className="text-white/70">Cert: <span className="text-green-400">{d?.cert}%</span></div>
        </div>
    );
};

export default SkillRadarWidget;
