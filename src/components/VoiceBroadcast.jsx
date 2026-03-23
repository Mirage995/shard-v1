import { useEffect, useRef } from 'react';

/**
 * VoiceBroadcast — listens for shard_voice_event from the backend
 * and speaks via Web Speech API (fallback when Gemini Live is offline).
 *
 * Mounts invisibly in App.jsx. No UI rendered.
 */
export default function VoiceBroadcast({ socket }) {
    const synthRef = useRef(window.speechSynthesis);
    const queueRef = useRef([]);
    const speakingRef = useRef(false);

    const speak = (text) => {
        if (!synthRef.current) return;
        const utt = new SpeechSynthesisUtterance(text);
        utt.lang = 'it-IT';
        utt.rate = 1.05;
        utt.pitch = 0.9;
        utt.onend = () => {
            speakingRef.current = false;
            if (queueRef.current.length > 0) {
                const next = queueRef.current.shift();
                speakingRef.current = true;
                synthRef.current.speak(next);
            }
        };

        if (speakingRef.current) {
            queueRef.current.push(utt);
        } else {
            speakingRef.current = true;
            synthRef.current.speak(utt);
        }
    };

    useEffect(() => {
        if (!socket) return;

        const handler = (data) => {
            const text = data?.text;
            if (!text) return;
            console.log(`[VOICE BROADCAST] Speaking (${data.priority}): ${text}`);
            speak(text);
        };

        socket.on('shard_voice_event', handler);
        return () => socket.off('shard_voice_event', handler);
    }, [socket]);

    return null;
}
