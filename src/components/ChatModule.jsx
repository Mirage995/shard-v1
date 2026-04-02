import React, { useEffect, useRef } from 'react';

const ChatModule = ({
    messages,
    inputValue,
    setInputValue,
    handleSend,
    isModularMode,
    activeDragElement,
    position,
    width = 672,
    height,
    onMouseDown,
    onFileUpload,
}) => {
    const messagesEndRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    return (
        <div
            id="chat"
            onMouseDown={onMouseDown}
            className={`absolute px-6 py-4 pointer-events-auto transition-all duration-200
            border rounded-2xl
            ${isModularMode ? (activeDragElement === 'chat' ? 'ring-2 ring-green-500' : 'ring-1 ring-yellow-500/30') : ''}
        `}
        style={{
            left: position.x,
            top: position.y,
            transform: 'translate(-50%, 0)',
            width: width,
            height: height,
            background: 'rgba(2, 13, 26, 0.15)',
            borderColor: 'rgba(0, 185, 235, 0.15)',
            boxShadow: '0 0 40px rgba(0, 185, 235, 0.06), 0 25px 50px rgba(0,0,0,0.5)',
        }}
        >
            <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-5 pointer-events-none mix-blend-overlay"></div>

            <div
                className="flex flex-col gap-3 overflow-y-auto mb-4 scrollbar-hide mask-image-gradient relative z-10"
                style={{ height: height ? `calc(${height}px - 70px)` : '15rem' }}
            >
                {messages.map((msg, i) => {
                    const isUser = msg.sender === 'You';
                    return (
                        <div key={i} className={`flex flex-col text-sm ${isUser ? 'items-end' : 'items-start'}`}>
                            <span className="text-cyan-600 font-mono text-xs opacity-70 mb-0.5">
                                {isUser ? '' : <span className="font-bold text-cyan-400 mr-1">{msg.sender}</span>}
                                [{msg.time}]
                                {isUser ? <span className="font-bold text-cyan-300 ml-1">{msg.sender}</span> : ''}
                            </span>
                            <div className={`px-3 py-2 rounded-xl max-w-[80%] leading-relaxed ${
                                isUser
                                    ? 'bg-cyan-900/30 border border-cyan-600/30 text-cyan-50'
                                    : 'bg-white/5 border border-white/10 text-gray-300'
                            }`}>
                                {msg.text}
                            </div>
                        </div>
                    );
                })}
                <div ref={messagesEndRef} />
            </div>

            <div className="flex gap-2 relative z-10 absolute bottom-4 left-6 right-6">
                {/* File upload button */}
                <label className="flex items-center justify-center w-10 h-10 rounded-lg border border-cyan-700/30 bg-black/40 text-cyan-500 hover:border-cyan-400 hover:text-cyan-300 cursor-pointer transition-all shrink-0" title="Upload document">
                    <span className="text-xl leading-none">+</span>
                    <input
                        type="file"
                        className="hidden"
                        accept=".pdf,.txt,.docx,.md"
                        onChange={onFileUpload}
                    />
                </label>
                <input
                    type="text"
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onKeyDown={handleSend}
                    placeholder="INITIALIZE COMMAND..."
                    className="flex-1 bg-black/40 border border-cyan-700/30 rounded-lg p-3 text-cyan-50 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400/50 transition-all placeholder-cyan-800/50 backdrop-blur-sm"
                />
            </div>
            {isModularMode && <div className={`absolute -top-6 left-0 text-xs font-bold tracking-widest ${activeDragElement === 'chat' ? 'text-green-500' : 'text-yellow-500/50'}`}>CHAT MODULE</div>}
        </div>
    );
};

export default ChatModule;
