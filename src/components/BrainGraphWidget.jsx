import { useEffect, useState, useRef, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { Brain, WifiOff, X, Maximize2 } from 'lucide-react';
import { useDraggable } from '../hooks/useDraggable';

// ── Color logic ───────────────────────────────────────────────────────────────

function nodeColor(node) {
    if (node.score >= 8.0)  return '#00ff88';
    if (node.score >= 7.0)  return '#4fc3f7';
    if (node.score >= 5.0)  return '#ff6b35';
    if (node.score > 0)     return '#cc44ff';
    return '#2a2a44';
}

function nodeRadius(node) {
    const base = node.score > 0 ? 6 : 4;
    return base + Math.min(node.requires_count * 0.8, 5);
}

// ── Custom node canvas painter (label + glow) ─────────────────────────────────

function paintNode(node, ctx, globalScale) {
    const r     = nodeRadius(node);
    const color = nodeColor(node);
    const label = node.label;
    const fontSize = Math.max(10 / globalScale, 2);

    // Glow for scored nodes
    if (node.score > 0) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 3, 0, 2 * Math.PI);
        ctx.fillStyle = color + '33';
        ctx.fill();
    }

    // Node circle
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();

    // Label — only visible when zoomed in enough
    if (globalScale > 1.2) {
        ctx.font = `${fontSize}px monospace`;
        ctx.fillStyle = node.score > 0 ? '#ffffff' : '#888899';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(
            label.length > 22 ? label.slice(0, 20) + '…' : label,
            node.x,
            node.y + r + fontSize * 0.9
        );
    }
}

// ── NodeInspector sidebar ─────────────────────────────────────────────────────

function NodeInspector({ node, onClose }) {
    if (!node) return null;

    const statusLabel = node.score >= 8   ? 'MASTER'
                      : node.score >= 7   ? 'CERTIFIED'
                      : node.score >= 5   ? 'NEAR-MISS'
                      : node.score > 0    ? 'FAILED'
                      : 'UNEXPLORED';

    const color = nodeColor(node);

    return (
        <div style={{
            position: 'absolute', top: 12, right: 12,
            width: 240, background: 'rgba(8,8,18,0.97)',
            border: `1px solid ${color}44`,
            borderRadius: 10, padding: '14px 16px',
            color: '#e0e0e0', zIndex: 10,
            fontFamily: 'monospace', fontSize: 12,
            boxShadow: `0 4px 24px ${color}22`,
        }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                <span style={{ fontWeight: 700, fontSize: 12, color: '#fff', wordBreak: 'break-word', flex: 1, paddingRight: 8, lineHeight: 1.4 }}>
                    {node.label}
                </span>
                <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#555', cursor: 'pointer', padding: 0, flexShrink: 0 }}>
                    <X size={13} />
                </button>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <span style={{
                    background: color + '22', color, border: `1px solid ${color}55`,
                    borderRadius: 4, padding: '2px 8px', fontSize: 10, fontWeight: 700,
                }}>
                    {statusLabel}
                </span>
                {node.score > 0 && (
                    <span style={{ color, fontWeight: 700, fontSize: 14 }}>{node.score.toFixed(1)}/10</span>
                )}
            </div>

            {node.acquired && (
                <div style={{ fontSize: 10, color: '#555', marginBottom: 4 }}>
                    Acquired: <span style={{ color: '#888' }}>{node.acquired}</span>
                </div>
            )}
            <div style={{ fontSize: 10, color: '#555' }}>
                Prerequisites: <span style={{ color: '#888' }}>{node.requires_count}</span>
            </div>

            {node.score > 0 && (
                <div style={{ marginTop: 10 }}>
                    <div style={{ background: '#111122', borderRadius: 3, height: 5, overflow: 'hidden' }}>
                        <div style={{
                            height: '100%', width: `${node.score * 10}%`,
                            background: `linear-gradient(90deg, ${color}88, ${color})`,
                            borderRadius: 3, transition: 'width 0.4s ease',
                        }} />
                    </div>
                </div>
            )}
        </div>
    );
}

// ── Legend ────────────────────────────────────────────────────────────────────

function Legend() {
    const items = [
        { color: '#00ff88', label: 'Master (≥8.0)' },
        { color: '#4fc3f7', label: 'Certified (≥7.0)' },
        { color: '#ff6b35', label: 'Near-miss (≥5.0)' },
        { color: '#cc44ff', label: 'Failed (<5.0)' },
        { color: '#2a2a44', label: 'Unexplored' },
    ];
    return (
        <div style={{
            position: 'absolute', bottom: 10, left: 10,
            background: 'rgba(8,8,18,0.85)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: 8, padding: '7px 10px',
            fontFamily: 'monospace', fontSize: 9, color: '#aaa', zIndex: 10,
        }}>
            {items.map(({ color, label }) => (
                <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 2 }}>
                    <div style={{ width: 7, height: 7, borderRadius: '50%', background: color, flexShrink: 0 }} />
                    <span>{label}</span>
                </div>
            ))}
        </div>
    );
}

// ── Main component ────────────────────────────────────────────────────────────

const BrainGraphWidget = ({ socket }) => {
    const [graphData, setGraphData]       = useState(null);
    const [selectedNode, setSelectedNode] = useState(null);
    const [offline, setOffline]           = useState(false);
    const [visible, setVisible]           = useState(false);
    const [fullscreen, setFullscreen]     = useState(false);
    const fgRef = useRef();

    const { pos, dragHandleProps, dragStyles } = useDraggable('brain-graph', {
        defaultPos: { x: 80, y: 80 }, anchor: 'top-left',
    });

    const fetchData = useCallback(() => {
        fetch('http://localhost:8000/api/brain_graph')
            .then(r => r.json())
            .then(d => { setOffline(false); setGraphData(d); })
            .catch(() => setOffline(true));
    }, []);

    useEffect(() => { fetchData(); }, [fetchData]);

    useEffect(() => {
        if (!socket) return;
        const handle = () => fetchData();
        socket.on('night_runner_update', handle);
        socket.on('study_complete', handle);
        return () => {
            socket.off('night_runner_update', handle);
            socket.off('study_complete', handle);
        };
    }, [socket, fetchData]);

    const handleNodeClick = useCallback((node) => {
        setSelectedNode(node);
        if (fgRef.current) {
            fgRef.current.centerAt(node.x, node.y, 600);
            fgRef.current.zoom(3, 600);
        }
    }, []);

    const certified = graphData ? graphData.nodes.filter(n => n.certified).length : 0;
    const total     = graphData ? graphData.total : 0;

    const w = fullscreen ? window.innerWidth  - 40 : 700;
    const h = fullscreen ? window.innerHeight - 60 : 520;

    if (!visible) {
        return (
            <div
                {...dragHandleProps}
                onClick={() => setVisible(true)}
                style={{
                    ...dragStyles,
                    background: 'rgba(8,8,18,0.92)',
                    border: '1px solid rgba(0,255,136,0.3)',
                    borderRadius: 10, padding: '8px 14px',
                    cursor: 'pointer', zIndex: 100,
                    display: 'flex', alignItems: 'center', gap: 8,
                    fontFamily: 'monospace', fontSize: 12, color: '#00ff88',
                    boxShadow: '0 0 16px rgba(0,255,136,0.12)',
                }}
            >
                <Brain size={15} />
                <span>Brain Graph</span>
                {total > 0 && <span style={{ color: '#555', fontSize: 10 }}>{certified}/{total}</span>}
                {offline && <WifiOff size={11} style={{ color: '#ff3366' }} />}
            </div>
        );
    }

    return (
        <div style={{
            position: 'fixed',
            left: fullscreen ? 20 : pos.x,
            top:  fullscreen ? 20 : pos.y,
            width: w, height: h,
            background: '#050508',
            border: '1px solid rgba(0,255,136,0.15)',
            borderRadius: 12, overflow: 'hidden',
            zIndex: 100,
            boxShadow: '0 8px 48px rgba(0,0,0,0.9)',
            userSelect: 'none',
        }}>
            {/* Header */}
            <div
                {...(fullscreen ? {} : dragHandleProps)}
                style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '7px 14px',
                    background: 'rgba(0,255,136,0.04)',
                    borderBottom: '1px solid rgba(0,255,136,0.1)',
                    cursor: fullscreen ? 'default' : 'move',
                    flexShrink: 0,
                }}
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Brain size={13} color="#00ff88" />
                    <span style={{ fontFamily: 'monospace', fontSize: 11, color: '#00ff88', fontWeight: 700, letterSpacing: 1 }}>
                        BRAIN GRAPH
                    </span>
                    {total > 0 && (
                        <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#444' }}>
                            {certified} certified / {total} nodes
                        </span>
                    )}
                    {offline && <WifiOff size={11} color="#ff3366" />}
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                    <button onClick={() => setFullscreen(f => !f)}
                        style={{ background: 'none', border: 'none', color: '#444', cursor: 'pointer', padding: 3 }}>
                        <Maximize2 size={12} />
                    </button>
                    <button onClick={() => setVisible(false)}
                        style={{ background: 'none', border: 'none', color: '#444', cursor: 'pointer', padding: 3 }}>
                        <X size={12} />
                    </button>
                </div>
            </div>

            {/* Graph canvas */}
            <div style={{ position: 'relative', width: '100%', height: h - 36 }}>
                {graphData && graphData.nodes.length > 0 ? (
                    <ForceGraph2D
                        ref={fgRef}
                        graphData={{ nodes: graphData.nodes, links: graphData.links }}
                        width={w}
                        height={h - 36}
                        backgroundColor="#050508"
                        nodeCanvasObject={paintNode}
                        nodeCanvasObjectMode={() => 'replace'}
                        nodeVal={nodeRadius}
                        linkColor={() => 'rgba(255,255,255,0.06)'}
                        linkWidth={0.6}
                        linkDirectionalParticles={2}
                        linkDirectionalParticleSpeed={0.005}
                        linkDirectionalParticleWidth={1.5}
                        linkDirectionalParticleColor={() => '#00ff8866'}
                        onNodeClick={handleNodeClick}
                        enableNodeDrag={true}
                        enableZoomInteraction={true}
                        cooldownTicks={120}
                        d3AlphaDecay={0.015}
                        d3VelocityDecay={0.3}
                    />
                ) : (
                    <div style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        height: '100%', color: '#333', fontFamily: 'monospace', fontSize: 11,
                    }}>
                        {offline ? 'backend offline' : 'loading brain...'}
                    </div>
                )}
                <NodeInspector node={selectedNode} onClose={() => setSelectedNode(null)} />
                <Legend />
            </div>
        </div>
    );
};

export default BrainGraphWidget;
