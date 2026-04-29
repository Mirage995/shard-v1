const { contextBridge, ipcRenderer, shell } = require('electron');

const allowedWindowChannels = new Set([
    'window-minimize',
    'window-maximize',
    'window-close',
]);

function sendWindowCommand(channel) {
    if (!allowedWindowChannels.has(channel)) {
        throw new Error(`Blocked IPC channel: ${channel}`);
    }
    ipcRenderer.send(channel);
}

async function openExternal(url) {
    const parsed = new URL(url);
    if (!['http:', 'https:'].includes(parsed.protocol)) {
        throw new Error(`Blocked external protocol: ${parsed.protocol}`);
    }
    return shell.openExternal(parsed.toString());
}

contextBridge.exposeInMainWorld('electronAPI', {
    minimizeWindow: () => sendWindowCommand('window-minimize'),
    maximizeWindow: () => sendWindowCommand('window-maximize'),
    closeWindow: () => sendWindowCommand('window-close'),
    openExternal,
});
