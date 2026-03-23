import { useState, useEffect } from 'react';
import { useDraggable } from '../hooks/useDraggable';

const API = 'http://localhost:8000';

export default function SystemStatsWidget() {
    const [graph, setGraph] = useState(null);
    const [cache, setCache] = useState(null);

    const { position, handleMouseDown } = useDraggable({ x: 20, y: 400 });

    const fetchStats = async () => {
        try {
            const [gRes, cRes] = await Promise.all([
                fetch(`${API}/api/knowledge/graph_stats`),
                fetch(`${API}/api/llm/cache_stats`),
            ]);
            setGraph(await gRes.json());
            setCache(await cRes.json());
        } catch (_) {}
    };

    useEffect(() => {
        fetchStats();
        const id = setInterval(fetchStats, 30_000);
        return () => clearInterval(id);
    }, []);

    const handleInvalidateCache = async () => {
        try {
            await fetch(`${API}/api/llm/cache_invalidate`, { method: 'POST' });
            fetchStats();
        } catch (_) {}
    };

    const hitPct = cache ? Math.round((cache.hit_rate ?? 0) * 100) : 0;
    const hitColor = hitPct >= 50 ? 'text-green-400' : hitPct >= 20 ? 'text-yellow-400' : 'text-red-400';

    return (
        <div
            className="fixed z-[150] w-56 bg-black/90 border border-cyan-400/30 rounded-lg shadow-lg font-mono text-xs select-none"
            style={{ left: position.x, top: position.y }}
        >
            {/* Header */}
            <div
                className="flex items-center justify-between px-3 py-1.5 border-b border-cyan-400/20 cursor-move bg-cyan-400/5"
                onMouseDown={handleMouseDown}
            >
                <span className="text-cyan-400 font-bold tracking-widest uppercase text-[10px]">System Stats</span>
                <button
                    onClick={fetchStats}
                    className="text-cyan-400/50 hover:text-cyan-400 transition-colors text-[10px]"
                    title="Refresh"
                >↻</button>
            </div>

            <div className="px-3 py-2 space-y-3">
                {/* GraphRAG */}
                <div>
                    <div className="text-cyan-400/60 uppercase tracking-widest text-[9px] mb-1">GraphRAG</div>
                    {graph ? (
                        <>
                            <div className="flex justify-between">
                                <span className="text-white/50">relations</span>
                                <span className="text-cyan-300">{graph.total_relations ?? 0}</span>
                            </div>
                            {graph.by_type && Object.entries(graph.by_type).slice(0, 4).map(([type, cnt]) => (
                                <div key={type} className="flex justify-between text-[10px]">
                                    <span className="text-white/30 truncate max-w-[110px]">{type}</span>
                                    <span className="text-cyan-400/70">{cnt}</span>
                                </div>
                            ))}
                        </>
                    ) : (
                        <div className="text-white/30">loading…</div>
                    )}
                </div>

                {/* LLM Cache */}
                <div>
                    <div className="text-cyan-400/60 uppercase tracking-widest text-[9px] mb-1">LLM Cache</div>
                    {cache ? (
                        <>
                            <div className="flex justify-between">
                                <span className="text-white/50">hit rate</span>
                                <span className={`font-bold ${hitColor}`}>{hitPct}%</span>
                            </div>
                            <div className="flex justify-between text-[10px]">
                                <span className="text-white/30">hits / misses</span>
                                <span className="text-white/50">{cache.hits} / {cache.misses}</span>
                            </div>
                            <div className="flex justify-between text-[10px]">
                                <span className="text-white/30">entries</span>
                                <span className="text-white/50">{cache.entries_in_memory} / {cache.max_entries}</span>
                            </div>
                            <button
                                onClick={handleInvalidateCache}
                                className="mt-1.5 w-full py-0.5 bg-red-900/20 hover:bg-red-900/40 border border-red-500/30 text-red-400/70 hover:text-red-400 text-[9px] rounded tracking-widest transition-colors"
                            >
                                INVALIDATE
                            </button>
                        </>
                    ) : (
                        <div className="text-white/30">loading…</div>
                    )}
                </div>
            </div>
        </div>
    );
}
