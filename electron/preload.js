const { contextBridge, ipcRenderer } = require('electron');

// Expose a minimal API to the renderer process
// Currently empty - all communication goes through HTTP to the Python backend
contextBridge.exposeInMainWorld('electronAPI', {
  // Placeholder for future IPC needs
  platform: process.platform,
});
