import { useEffect, useRef } from 'react';

// speedMult: 1.0 = idle, 3.5 = SHARD speaking
const IDLE_SPEED   = 1.0;
const ACTIVE_SPEED = 3.5;
const IDLE_ALPHA   = 0.45;
const ACTIVE_ALPHA = 0.75;
const DECAY_MS     = 2800; // ms after last speech event to return to idle

const CircuitBackground = ({ socket }) => {
    const canvasRef   = useRef(null);
    const reactiveRef = useRef({ speedMult: IDLE_SPEED, alpha: IDLE_ALPHA, lastSpeech: 0 });

    // Wire socket: boost on SHARD transcription, decay after DECAY_MS
    useEffect(() => {
        if (!socket) return;
        const handle = (data) => {
            if (data?.sender === 'shard' || data?.text) {
                reactiveRef.current.lastSpeech = performance.now();
            }
        };
        socket.on('transcription', handle);
        return () => socket.off('transcription', handle);
    }, [socket]);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        let animId;
        let traces = [], pulses = [];

        function resize() {
            canvas.width  = window.innerWidth;
            canvas.height = window.innerHeight;
            buildTraces();
        }

        function buildTraces() {
            traces = [];
            const W = canvas.width, H = canvas.height;
            const SCX = W / 2, SCY = H / 2;
            for (let i = 0; i < 60; i++) {
                let sx, sy;
                const edge = Math.floor(Math.random() * 4);
                if      (edge === 0) { sx = Math.random() * W; sy = 0; }
                else if (edge === 1) { sx = W; sy = Math.random() * H; }
                else if (edge === 2) { sx = Math.random() * W; sy = H; }
                else                 { sx = 0; sy = Math.random() * H; }

                const tx = SCX + (Math.random() - 0.5) * 180;
                const ty = SCY + (Math.random() - 0.5) * 180;
                const segs = [];
                let x = sx, y = sy;
                const steps = 2 + Math.floor(Math.random() * 3);

                for (let s = 0; s < steps; s++) {
                    const prog = (s + 1) / steps;
                    const nx = x + (tx - x) * prog;
                    const ny = y + (ty - y) * prog;
                    if (s % 2 === 0) {
                        segs.push({ x1: x,  y1: y,  x2: nx, y2: y  });
                        segs.push({ x1: nx, y1: y,  x2: nx, y2: ny });
                    } else {
                        segs.push({ x1: x,  y1: y,  x2: x,  y2: ny });
                        segs.push({ x1: x,  y1: ny, x2: nx, y2: ny });
                    }
                    x = nx; y = ny;
                }
                traces.push({ segs, alpha: IDLE_ALPHA + Math.random() * 0.25, endX: tx, endY: ty });
            }
        }

        function spawnPulse(speedMult) {
            if (!traces.length) return;
            const trace = traces[Math.floor(Math.random() * traces.length)];
            const pts = [];
            for (const s of trace.segs) {
                if (!pts.length) pts.push({ x: s.x1, y: s.y1 });
                pts.push({ x: s.x2, y: s.y2 });
            }
            if (pts.length < 2) return;
            pulses.push({
                pts,
                t: 0,
                speed: (0.005 + Math.random() * 0.009) * speedMult,
            });
        }

        // Dynamic interval: respawns pulses faster when SHARD is speaking
        let pulseInterval = null;
        let currentIntervalMs = 220;

        function setSpawnRate(ms) {
            if (ms === currentIntervalMs) return;
            currentIntervalMs = ms;
            clearInterval(pulseInterval);
            pulseInterval = setInterval(() => spawnPulse(reactiveRef.current.speedMult), ms);
        }

        pulseInterval = setInterval(() => spawnPulse(reactiveRef.current.speedMult), currentIntervalMs);
        window.addEventListener('resize', resize);
        resize();

        function draw() {
            // Smooth speedMult and alpha transitions
            const r = reactiveRef.current;
            const elapsed = performance.now() - r.lastSpeech;
            const active = elapsed < DECAY_MS;
            const target  = active ? ACTIVE_SPEED : IDLE_SPEED;
            const tAlpha  = active ? ACTIVE_ALPHA : IDLE_ALPHA;

            r.speedMult += (target - r.speedMult) * 0.04;
            r.alpha     += (tAlpha - r.alpha)     * 0.04;

            // Adjust spawn rate dynamically
            const spawnMs = active ? 80 : 220;
            setSpawnRate(spawnMs);

            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // Draw static traces — brighten when active
            for (const tr of traces) {
                const a = tr.alpha * r.alpha / IDLE_ALPHA;
                ctx.lineWidth = active ? 0.9 : 0.7;
                for (const s of tr.segs) {
                    ctx.beginPath();
                    ctx.moveTo(s.x1, s.y1);
                    ctx.lineTo(s.x2, s.y2);
                    ctx.strokeStyle = `rgba(0,180,255,${a})`;
                    ctx.stroke();
                }
                ctx.beginPath();
                ctx.arc(tr.endX, tr.endY, active ? 2 : 1.5, 0, Math.PI * 2);
                ctx.fillStyle = `rgba(0,220,255,${a * 2})`;
                ctx.fill();
            }

            // Draw pulses — wider glow when active
            const glowRadius = active ? 3.0 : 2.2;
            const glowBlur   = active ? 14  : 8;

            for (let i = pulses.length - 1; i >= 0; i--) {
                const p = pulses[i];
                p.t += p.speed * r.speedMult;
                if (p.t >= 1) { pulses.splice(i, 1); continue; }
                const tot = p.pts.length - 1;
                for (let t = 0; t < 5; t++) {
                    const pt  = Math.max(0, p.t - t * 0.020);
                    const pos = pt * tot;
                    const idx = Math.min(Math.floor(pos), tot - 1);
                    const f   = pos - idx;
                    if (idx >= tot) continue;
                    const px = p.pts[idx].x + (p.pts[idx+1].x - p.pts[idx].x) * f;
                    const py = p.pts[idx].y + (p.pts[idx+1].y - p.pts[idx].y) * f;
                    ctx.beginPath();
                    ctx.arc(px, py, glowRadius * (1 - t / 6), 0, Math.PI * 2);
                    ctx.fillStyle = `rgba(0,238,255,${0.75 * (1 - t / 5) * (1 - p.t * 0.4)})`;
                    if (t === 0) { ctx.shadowBlur = glowBlur; ctx.shadowColor = '#00eeff'; }
                    ctx.fill();
                    ctx.shadowBlur = 0;
                }
            }

            animId = requestAnimationFrame(draw);
        }
        draw();

        return () => {
            cancelAnimationFrame(animId);
            clearInterval(pulseInterval);
            window.removeEventListener('resize', resize);
        };
    }, []);

    return (
        <canvas
            ref={canvasRef}
            style={{
                position: 'fixed',
                top: 0, left: 0,
                width: '100vw',
                height: '100vh',
                zIndex: 0,
                pointerEvents: 'none',
                opacity: 1,
            }}
        />
    );
};

export default CircuitBackground;
