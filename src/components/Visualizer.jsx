import React, { useEffect, useRef } from 'react';

const MOOD_COLORS = {
    calm:       { r: 0,   g: 185, b: 235 },
    focused:    { r: 30,  g: 120, b: 255 },
    curious:    { r: 140, g: 80,  b: 255 },
    excited:    { r: 0,   g: 255, b: 180 },
    tired:      { r: 80,  g: 140, b: 180 },
    reflective: { r: 180, g: 60,  b: 255 },
    alert:      { r: 255, g: 60,  b: 60  },
};

function moodRGBA(mood, alpha = 1) {
    const c = MOOD_COLORS[mood] || MOOD_COLORS.calm;
    return `rgba(${c.r},${c.g},${c.b},${alpha})`;
}
function moodHex(mood) {
    const c = MOOD_COLORS[mood] || MOOD_COLORS.calm;
    return '#' + [c.r,c.g,c.b].map(v => v.toString(16).padStart(2,'0')).join('');
}

const Visualizer = ({ audioData, isListening, intensity = 0, width = 600, height = 400, mood = 'calm' }) => {
    const canvasRef = useRef(null);
    const frameRef = useRef(0);

    const audioDataRef = useRef(audioData);
    const intensityRef = useRef(intensity);
    const isListeningRef = useRef(isListening);
    const moodRef = useRef(mood);

    useEffect(() => {
        audioDataRef.current = audioData;
        intensityRef.current = intensity;
        isListeningRef.current = isListening;
        moodRef.current = mood;
    }, [audioData, intensity, isListening, mood]);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        canvas.width = width;
        canvas.height = height;

        const ctx = canvas.getContext('2d');
        let animationId;

        const orbitParticles = Array.from({ length: 55 }, (_, i) => ({
            orbit: 68 + Math.random() * 18,
            angle: (i / 55) * Math.PI * 2,
            speed: (0.006 + Math.random() * 0.010) * (Math.random() > .5 ? 1 : -1),
            size:  0.7 + Math.random() * 1.4,
            alpha: 0.25 + Math.random() * 0.55,
            tilt:  Math.random() * Math.PI,
        }));

        const draw = () => {
            const w = canvas.width;
            const h = canvas.height;
            const centerX = w / 2;
            const centerY = h / 2;
            const currentIsListening = isListeningRef.current;
            const currentMood = moodRef.current;
            const mc = MOOD_COLORS[currentMood] || MOOD_COLORS.calm;
            const R = Math.min(w, h) * 0.36;

            // Faster frame increment when listening (reactor speeds up)
            frameRef.current += currentIsListening ? 0.018 : 0.011;
            const frame = frameRef.current;

            ctx.clearRect(0, 0, w, h);

            // Ambient glow - mood colored
            const bg = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, R * 1.1);
            bg.addColorStop(0,   `rgba(${Math.floor(mc.r*0.2)},${Math.floor(mc.g*0.3)},${Math.floor(mc.b*0.5)},0.22)`);
            bg.addColorStop(0.6, `rgba(${Math.floor(mc.r*0.1)},${Math.floor(mc.g*0.15)},${Math.floor(mc.b*0.3)},0.10)`);
            bg.addColorStop(1,   'rgba(0,0,0,0)');
            ctx.beginPath(); ctx.arc(centerX, centerY, R * 1.1, 0, Math.PI * 2);
            ctx.fillStyle = bg; ctx.fill();

            // Rings - mood colored
            [
                { r: R*1.000, lw: 1.2, a: 0.28, dash: null },
                { r: R*0.945, lw: 3.2, a: 0.62, dash: null, glow: true },
                { r: R*0.895, lw: 0.8, a: 0.22, dash: null },
                { r: R*0.835, lw: 1.8, a: 0.48, dash: null },
                { r: R*0.775, lw: 0.7, a: 0.18, dash: null },
                { r: R*0.715, lw: 2.5, a: 0.58, dash: null, glow: true },
                { r: R*0.655, lw: 0.7, a: 0.20, dash: [4, 5] },
                { r: R*0.595, lw: 1.4, a: 0.42, dash: null },
                { r: R*0.535, lw: 0.7, a: 0.22, dash: [3, 4] },
            ].forEach(({ r, lw, a, dash, glow }, i) => {
                ctx.save(); ctx.translate(centerX, centerY);
                if (dash) { ctx.rotate(frame * 0.28 * (i % 2 ? 1 : -1)); ctx.setLineDash(dash); }
                ctx.beginPath(); ctx.arc(0, 0, r, 0, Math.PI * 2);
                ctx.strokeStyle = moodRGBA(currentMood, a); ctx.lineWidth = lw;
                if (glow) { ctx.shadowBlur = 16; ctx.shadowColor = moodRGBA(currentMood, 0.65); }
                ctx.stroke(); ctx.shadowBlur = 0; ctx.setLineDash([]); ctx.restore();
            });

            // Tick marks
            for (let i = 0; i < 72; i++) {
                const a = (i / 72) * Math.PI * 2;
                const maj = i % 6 === 0, med = i % 3 === 0 && !maj;
                const len = maj ? 0.13 : (med ? 0.08 : 0.04);
                ctx.beginPath();
                ctx.moveTo(centerX + Math.cos(a) * R * 0.94, centerY + Math.sin(a) * R * 0.94);
                ctx.lineTo(centerX + Math.cos(a) * (R * 0.94 - R * len), centerY + Math.sin(a) * (R * 0.94 - R * len));
                ctx.strokeStyle = maj ? moodRGBA(currentMood, 0.65) : moodRGBA(currentMood, 0.30);
                ctx.lineWidth = maj ? 1.4 : 0.7; ctx.stroke();
            }

            // Dots ring 1
            for (let i = 0; i < 32; i++) {
                const a = (i / 32) * Math.PI * 2 - frame * 0.16;
                const x = centerX + Math.cos(a) * R * 0.715, y = centerY + Math.sin(a) * R * 0.715;
                const big = i % 4 === 0, med = i % 2 === 0 && !big;
                ctx.beginPath(); ctx.arc(x, y, big ? 3.2 : (med ? 2.0 : 1.3), 0, Math.PI * 2);
                ctx.fillStyle = big ? moodHex(currentMood) : (med ? moodRGBA(currentMood, 0.7) : moodRGBA(currentMood, 0.4));
                if (big) { ctx.shadowBlur = 12; ctx.shadowColor = moodHex(currentMood); }
                ctx.fill(); ctx.shadowBlur = 0;
            }

            // Dots ring 2
            for (let i = 0; i < 48; i++) {
                const a = (i / 48) * Math.PI * 2 + frame * 0.09;
                const x = centerX + Math.cos(a) * R * 0.945, y = centerY + Math.sin(a) * R * 0.945;
                const big = i % 6 === 0;
                ctx.beginPath(); ctx.arc(x, y, big ? 2.6 : 1.1, 0, Math.PI * 2);
                ctx.fillStyle = big ? moodRGBA(currentMood, 0.88) : moodRGBA(currentMood, 0.28);
                if (big) { ctx.shadowBlur = 9; ctx.shadowColor = moodHex(currentMood); }
                ctx.fill(); ctx.shadowBlur = 0;
            }

            // Inner zone clipped
            ctx.save();
            ctx.beginPath(); ctx.arc(centerX, centerY, R * 0.53, 0, Math.PI * 2); ctx.clip();

            [{ r: R*0.48, sides: 8, sp: 0.18, a: 0.32 },
             { r: R*0.37, sides: 6, sp: -0.22, a: 0.26 }]
            .forEach(({ r, sides, sp, a }) => {
                ctx.save(); ctx.translate(centerX, centerY); ctx.rotate(frame * sp);
                ctx.beginPath();
                for (let s = 0; s <= sides; s++) {
                    const ang = (s / sides) * Math.PI * 2;
                    s === 0 ? ctx.moveTo(Math.cos(ang)*r, Math.sin(ang)*r)
                            : ctx.lineTo(Math.cos(ang)*r, Math.sin(ang)*r);
                }
                ctx.strokeStyle = moodRGBA(currentMood, a); ctx.lineWidth = 1.0;
                ctx.stroke(); ctx.restore();
            });

            // Wireframe mesh
            const mR = R * 0.46, mPts = [];
            [{ r: 0,       cnt: 1,  sp: 0     },
             { r: mR*0.22, cnt: 6,  sp: 0.20  },
             { r: mR*0.44, cnt: 10, sp: -0.15 },
             { r: mR*0.66, cnt: 14, sp: 0.11  },
             { r: mR*0.88, cnt: 18, sp: -0.07 }]
            .forEach(({ r, cnt, sp }) => {
                for (let i = 0; i < cnt; i++) {
                    const ang = (i / Math.max(cnt, 1)) * Math.PI * 2 + frame * sp;
                    mPts.push({ x: centerX + Math.cos(ang)*r, y: centerY + Math.sin(ang)*r });
                }
            });
            const maxD = mR * 0.42;
            for (let i = 0; i < mPts.length; i++)
                for (let j = i + 1; j < mPts.length; j++) {
                    const dx = mPts[j].x - mPts[i].x, dy = mPts[j].y - mPts[i].y;
                    const d = Math.sqrt(dx*dx + dy*dy);
                    if (d < maxD) {
                        ctx.beginPath(); ctx.moveTo(mPts[i].x, mPts[i].y); ctx.lineTo(mPts[j].x, mPts[j].y);
                        ctx.strokeStyle = moodRGBA(currentMood, (1-d/maxD)*0.52); ctx.lineWidth = 0.65; ctx.stroke();
                    }
                }
            mPts.forEach((pt, idx) => {
                ctx.beginPath(); ctx.arc(pt.x, pt.y, idx === 0 ? 2.2 : 1.6, 0, Math.PI * 2);
                ctx.fillStyle = idx === 0 ? moodRGBA(currentMood, 0.88) : moodRGBA(currentMood, 0.50); ctx.fill();
            });
            ctx.restore();

            // Orbit particles - mood colored
            orbitParticles.forEach(p => {
                p.angle += p.speed * (currentIsListening ? 1.8 : 1.0);
                const cosT = Math.cos(p.tilt), sinT = Math.sin(p.tilt);
                const px = centerX + cosT*Math.cos(p.angle)*p.orbit - sinT*Math.sin(p.angle)*p.orbit*0.38;
                const py = centerY + sinT*Math.cos(p.angle)*p.orbit + cosT*Math.sin(p.angle)*p.orbit*0.38;
                ctx.beginPath(); ctx.arc(px, py, p.size, 0, Math.PI * 2);
                ctx.fillStyle = moodRGBA(currentMood, p.alpha*0.55); ctx.fill();
            });

            // Electrons - mood colored
            const eOrbR = R * 0.50, eOrbRy = eOrbR * 0.32;
            [0, Math.PI/3, -Math.PI/3].forEach((tilt, idx) => {
                ctx.save(); ctx.translate(centerX, centerY); ctx.rotate(tilt);
                ctx.beginPath(); ctx.ellipse(0, 0, eOrbR, eOrbRy, 0, 0, Math.PI * 2);
                ctx.strokeStyle = moodRGBA(currentMood, 0.13); ctx.lineWidth = 0.8; ctx.stroke(); ctx.restore();
                const ea = frame * (1.2 + idx * 0.22) + idx * (Math.PI * 2 / 3);
                const cosT = Math.cos(tilt), sinT = Math.sin(tilt);
                for (let t = 1; t <= 8; t++) {
                    const ta = ea - t * 0.09;
                    const tx = centerX + cosT*Math.cos(ta)*eOrbR - sinT*Math.sin(ta)*eOrbRy;
                    const ty = centerY + sinT*Math.cos(ta)*eOrbR + cosT*Math.sin(ta)*eOrbRy;
                    ctx.beginPath(); ctx.arc(tx, ty, 2.2*(1-t/10), 0, Math.PI*2);
                    ctx.fillStyle = moodRGBA(currentMood, 0.48*(1-t/9)); ctx.fill();
                }
                const ex = centerX + cosT*Math.cos(ea)*eOrbR - sinT*Math.sin(ea)*eOrbRy;
                const ey = centerY + sinT*Math.cos(ea)*eOrbR + cosT*Math.sin(ea)*eOrbRy;
                ctx.beginPath(); ctx.arc(ex, ey, 4.2, 0, Math.PI*2);
                ctx.fillStyle = moodHex(currentMood); ctx.shadowBlur = 16; ctx.shadowColor = moodHex(currentMood);
                ctx.fill(); ctx.shadowBlur = 0;
            });

            // Proton core - mood colored with enhanced pulse
            const pR0 = R * 0.112;
            const basePulse = 0.90 + 0.10 * Math.sin(frame * 3.8);
            const listenBoost = currentIsListening ? (1.2 + 0.15 * Math.sin(frame * 12)) : 1.0;
            const pulse = basePulse * listenBoost;
            const pR = pR0 * pulse;

            // Outer halo
            const h1 = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, pR0*6);
            h1.addColorStop(0, moodRGBA(currentMood, 0.24*pulse));
            h1.addColorStop(0.4, moodRGBA(currentMood, 0.10*pulse));
            h1.addColorStop(1, 'rgba(0,0,0,0)');
            ctx.beginPath(); ctx.arc(centerX, centerY, pR0*6, 0, Math.PI*2);
            ctx.fillStyle = h1; ctx.fill();

            // Inner halo
            const h2 = ctx.createRadialGradient(centerX, centerY, pR*0.5, centerX, centerY, pR*3);
            h2.addColorStop(0, `rgba(${Math.min(255,mc.r+100)},${Math.min(255,mc.g+28)},${Math.min(255,mc.b)},${0.38*pulse})`);
            h2.addColorStop(1, 'rgba(0,0,0,0)');
            ctx.beginPath(); ctx.arc(centerX, centerY, pR*3, 0, Math.PI*2);
            ctx.fillStyle = h2; ctx.fill();

            // Core gradient
            const cG = ctx.createRadialGradient(centerX-pR*0.3, centerY-pR*0.3, pR*0.05, centerX, centerY, pR);
            cG.addColorStop(0,    'rgba(255,255,255,1.0)');
            cG.addColorStop(0.15, `rgba(${Math.min(255,mc.r+200)},${Math.min(255,mc.g+45)},${Math.min(255,mc.b)},0.98)`);
            cG.addColorStop(0.45, moodRGBA(currentMood, 0.90));
            cG.addColorStop(0.80, moodRGBA(currentMood, 0.55));
            cG.addColorStop(1,    moodRGBA(currentMood, 0.0));
            ctx.beginPath(); ctx.arc(centerX, centerY, pR, 0, Math.PI*2);
            ctx.fillStyle = cG; ctx.shadowBlur = 40; ctx.shadowColor = moodRGBA(currentMood, 1.0);
            ctx.fill(); ctx.shadowBlur = 0;

            // Specular highlight
            const sG = ctx.createRadialGradient(centerX-pR*0.30, centerY-pR*0.30, 0, centerX-pR*0.30, centerY-pR*0.30, pR*0.33);
            sG.addColorStop(0, 'rgba(255,255,255,0.72)'); sG.addColorStop(1, 'rgba(255,255,255,0)');
            ctx.beginPath(); ctx.arc(centerX-pR*0.30, centerY-pR*0.30, pR*0.33, 0, Math.PI*2);
            ctx.fillStyle = sG; ctx.fill();

            // Energy spikes - mood colored
            const sp = 0.5 + 0.5 * Math.sin(frame * 4.5);
            const sMult = currentIsListening ? 1.6 : 1.0;
            for (let i = 0; i < 8; i++) {
                const a = (i / 8) * Math.PI * 2 + frame * 0.5;
                ctx.beginPath();
                ctx.moveTo(centerX + Math.cos(a)*pR*1.1, centerY + Math.sin(a)*pR*1.1);
                ctx.lineTo(centerX + Math.cos(a)*pR*(2.8+sp*1.5), centerY + Math.sin(a)*pR*(2.8+sp*1.5));
                ctx.strokeStyle = moodRGBA(currentMood, (0.28+sp*0.32)*(1-(i%2)*0.35)*sMult);
                ctx.lineWidth = 0.85; ctx.stroke();
            }

            // S.H.A.R.D. label - mood colored
            ctx.font = `900 ${Math.min(w, h) * 0.07}px 'Share Tech Mono', monospace`;
            ctx.textAlign = 'center';
            ctx.fillStyle = moodHex(currentMood);
            ctx.shadowBlur = 16; ctx.shadowColor = moodRGBA(currentMood, 0.85);
            ctx.fillText('S.H.A.R.D.', centerX, centerY + R * 1.28);
            ctx.shadowBlur = 0;

            animationId = requestAnimationFrame(draw);
        };

        draw();
        return () => cancelAnimationFrame(animationId);
    }, [width, height]);

    return (
        <div className="relative" style={{ width, height }}>
            <canvas
                ref={canvasRef}
                style={{ width: '100%', height: '100%' }}
            />
        </div>
    );
};

export default Visualizer;