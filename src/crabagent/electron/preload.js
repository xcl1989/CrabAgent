const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // Platform info
  platform: process.platform,
  arch: process.arch,
  electronVersion: process.versions.electron,
  nodeVersion: process.versions.node,

  // Window control
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'),
  isMaximized: () => ipcRenderer.invoke('window-is-maximized'),
  onMaximizeChange: (callback) => {
    ipcRenderer.on('window-maximized-changed', (_event, maximized) => callback(maximized));
  },

  // Desktop pet controls are deliberately limited to window-level actions.
  getPetAuthToken: () => ipcRenderer.invoke('pet-auth-token'),
  petAction: (action, sessionId) => ipcRenderer.invoke('pet-action', action, sessionId),
  setPetQuietMode: (minutes) => ipcRenderer.invoke('pet-quiet-mode', minutes),
  getPetQuietStatus: () => ipcRenderer.invoke('pet-quiet-status'),
  resizePet: (height) => ipcRenderer.send('pet-resize', height),
  showPetMenu: () => ipcRenderer.send('pet-menu'),
  startPetDrag: (offsetX, offsetY) => ipcRenderer.send('pet-drag-start', { offsetX, offsetY }),
  movePetDrag: () => ipcRenderer.send('pet-drag-move'),
  endPetDrag: () => ipcRenderer.send('pet-drag-end'),
  collaborationBrowserLayout: (bounds, visible) => ipcRenderer.invoke('collaboration-browser-layout', bounds, visible),
  collaborationBrowserNavigate: (url) => ipcRenderer.invoke('collaboration-browser-navigate', url),
  collaborationBrowserAction: (action) => ipcRenderer.invoke('collaboration-browser-action', action),
  onCollaborationBrowserState: (callback) => ipcRenderer.on('collaboration-browser-state', (_event, state) => callback(state)),
  onOpenSession: (callback) => ipcRenderer.on('open-session', (_event, sessionId) => callback(sessionId)),
  onPetDragDirection: (callback) => ipcRenderer.on('pet-drag-direction', (_event, data) => callback(data)),
});
