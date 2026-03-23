import { useEffect, useState } from 'react';
import { Activity, RefreshCw, WifiOff } from 'lucide-react';

const POLL_MS = 30_000;

const ClinicaWidget = ({ socket }) => {
    const [tickets, setTickets] = useState([]);
    const [meta, setMeta]       = useState(null);
    const [visible, setVisible] = useState(false);
    const [loading, setLoading] = useState(false);
    const [offline, setOffline] = useState(false);

    const fetchData = () => {
        setLoading(true);
        fetch('http://localhost:8000/api/improvement_queue')
            .then(r => r.json())
            .then(d => {
                setOffline(false);
                setMeta(d.available ? d : null);
                const cards = (d.queue || []).map((topic, i) => ({
                    id: i, topic,
                    priority: i < 2 ? 1 : i < 5 ? 2 : 3,
                }));
                setTickets(cards);
            })
            .catch(() => setOffline(true))
            .finally(() => setLoading(false));
    };

    useEffect(() => {
        fetchData();
        const interval = setInterval(fetchData, POLL_MS);
        return () => clearInterval(interval);
    }, []);

    useEffect(() => {
        if (!socket) return;
        socket.on('study_complete', fetchData);
        return () => socket.off('study_complete', fetchData);
    }, [socket]);

    const priorityColor = (p) => p === 1 ? '#f87171' : p === 2 ? '#facc15' : '#22d3ee';
    const priorityLabel = (p) => p === 1 ? 'CRITICO' : p === 2 ? 'NORMALE' : 'BASSA';

    return (
        <>
            {/* Toggle button — always visible */}
            <button
                onClick={() => setVisible(v => !v)}
                className="fixed bottom-5 left-5 z-[9500] pointer-events-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-500/30 bg-black/75 backdrop-blur-xl hover:border-red-400/60 transition-all"
            >
                <Activity size={12} className={offline ? 'text-white/30' : 'text-red-400'} />
                <span className={`text-[10px] font-bold tracking-wider uppercase ${offline ? 'text-white/30' : 'text-red-300'}`}>
                    Clinica
                </span>
                {tickets.length > 0 && !offline && (
                    <span className="ml-1 w-4 h-4 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center">
                        {tickets.length}
                    </span>
                )}
            </button>

            {visible && (
                <div className="fixed bottom-14 left-5 w-80 z-[9500] pointer-events-auto">
                    <div className="relative rounded-xl border border-red-500/20 bg-black/85 backdrop-blur-xl shadow-[0_0_30px_rgba(248,113,113,0.10)] overflow-hidden">

                        {/* Header */}
                        <div className="flex items-center justify-between px-4 py-2.5 border-b border-red-500/10">
                            <div className="flex items-center gap-2">
                                <Activity size={12} className="text-red-400" />
                                <span className="text-[11px] font-bold tracking-widest text-red-300 uppercase">
                                    Pensieri Intrusivi
                                </span>
                            </div>
                            <div className="flex items-center gap-2">
                                <button onClick={fetchData} className="text-cyan-500/50 hover:text-cyan-400 transition-colors">
                                    <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
                                </button>
                                <button onClick={() => setVisible(false)} className="text-white/30 hover:text-white/60 text-xs">✕</button>
                            </div>
                        </div>

                        {/* Meta / last run */}
                        {meta?.last_run_at && (
                            <div className="px-4 py-1.5 text-[9px] text-white/30 font-mono border-b border-white/5">
                                Ultimo scan: {new Date(meta.last_run_at).toLocaleString('it-IT')}
                                {' · '}{meta.total_queued ?? 0} ticket totali
                            </div>
                        )}

                        {/* Content */}
                        <div className="max-h-80 overflow-y-auto divide-y divide-white/5">
                            {offline ? (
                                <div className="px-4 py-6 flex flex-col items-center gap-2 text-[11px] text-white/30 font-mono">
                                    <WifiOff size={18} className="text-white/15" />
                                    Backend offline.<br />Avvia il server per vedere i ticket.
                                </div>
                            ) : tickets.length === 0 ? (
                                <div className="px-4 py-6 text-center text-[11px] text-white/30 font-mono">
                                    Nessun ticket pendente.<br />SHARD è in forma.
                                </div>
                            ) : (
                                tickets.map(t => (
                                    <div key={t.id} className="px-4 py-2.5 hover:bg-white/3 transition-colors">
                                        <div className="flex items-center gap-1.5 mb-1">
                                            <span className="text-[8px] font-bold px-1.5 py-0.5 rounded font-mono tracking-wider"
                                                style={{
                                                    color: priorityColor(t.priority),
                                                    border: `1px solid ${priorityColor(t.priority)}40`,
                                                    background: `${priorityColor(t.priority)}10`,
                                                }}>
                                                P{t.priority} · {priorityLabel(t.priority)}
                                            </span>
                                        </div>
                                        <div className="text-[11px] text-white/80 font-mono leading-snug">
                                            {t.topic}
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>

                        <div className="px-4 py-2 border-t border-white/5 text-[9px] text-white/20 font-mono">
                            SSJ3 · ImprovementEngine · {tickets.length} in coda
                        </div>
                    </div>
                </div>
            )}
        </>
    );
};

export default ClinicaWidget;
