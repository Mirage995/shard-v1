/**
 * useDraggable — makes any fixed/absolute widget draggable.
 *
 * Usage:
 *   const { pos, dragHandleProps, dragStyles } = useDraggable('widget-id', { x: 16, y: 16, anchor: 'bottom-right' })
 *
 *   <div style={dragStyles}>
 *     <div {...dragHandleProps}>⠿ drag here</div>
 *     ... widget content ...
 *   </div>
 *
 * anchor: where the default position is relative to ('bottom-right' | 'bottom-left' | 'top-right' | 'top-left')
 * Positions are saved to localStorage under key `shard_widget_pos_<id>`.
 */
import { useState, useEffect, useRef, useCallback } from 'react';

const STORAGE_KEY = (id) => `shard_widget_pos_${id}`;

function resolveDefault(defaultPos, anchor) {
    if (defaultPos.x !== undefined && defaultPos.y !== undefined) return defaultPos;
    const w = window.innerWidth;
    const h = window.innerHeight;
    const ox = defaultPos.offsetX ?? 16;
    const oy = defaultPos.offsetY ?? 16;
    switch (anchor) {
        case 'bottom-right': return { x: w - ox, y: h - oy };
        case 'bottom-left':  return { x: ox,     y: h - oy };
        case 'top-right':    return { x: w - ox, y: oy };
        case 'top-left':     return { x: ox,     y: oy };
        default:             return { x: w - ox, y: h - oy };
    }
}

export function useDraggable(id, { defaultPos = {}, anchor = 'bottom-right' } = {}) {
    const loadSaved = () => {
        try {
            const raw = localStorage.getItem(STORAGE_KEY(id));
            if (raw) return JSON.parse(raw);
        } catch (_) {}
        return null;
    };

    const [pos, setPos] = useState(() => loadSaved() || resolveDefault(defaultPos, anchor));
    const dragging = useRef(false);
    const startMouse = useRef({ x: 0, y: 0 });
    const startPos = useRef({ x: 0, y: 0 });

    // Persist position
    useEffect(() => {
        try { localStorage.setItem(STORAGE_KEY(id), JSON.stringify(pos)); } catch (_) {}
    }, [id, pos]);

    const onMouseDown = useCallback((e) => {
        if (e.button !== 0) return;
        dragging.current = true;
        startMouse.current = { x: e.clientX, y: e.clientY };
        startPos.current = pos;
        e.preventDefault();
    }, [pos]);

    useEffect(() => {
        const onMouseMove = (e) => {
            if (!dragging.current) return;
            const dx = e.clientX - startMouse.current.x;
            const dy = e.clientY - startMouse.current.y;
            setPos({
                x: startPos.current.x + dx,
                y: startPos.current.y + dy,
            });
        };
        const onMouseUp = () => { dragging.current = false; };

        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
        return () => {
            window.removeEventListener('mousemove', onMouseMove);
            window.removeEventListener('mouseup', onMouseUp);
        };
    }, []);

    // Convert logical pos to CSS fixed position.
    // pos.x / pos.y are screen coordinates of the widget's top-left corner.
    const dragStyles = {
        position: 'fixed',
        left: `${pos.x}px`,
        top: `${pos.y}px`,
        cursor: 'default',
        userSelect: 'none',
    };

    const dragHandleProps = {
        onMouseDown,
        style: {
            cursor: 'grab',
            padding: '2px 6px',
            opacity: 0.5,
            fontSize: '11px',
            userSelect: 'none',
        },
        title: 'Trascina per spostare',
    };

    return { pos, setPos, dragStyles, dragHandleProps };
}
