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
  petAction: (action) => ipcRenderer.invoke('pet-action', action),
  showPetMenu: () => ipcRenderer.send('pet-menu'),
  startPetDrag: (offsetX, offsetY) => ipcRenderer.send('pet-drag-start', { offsetX, offsetY }),
  movePetDrag: () => ipcRenderer.send('pet-drag-move'),
  endPetDrag: () => ipcRenderer.send('pet-drag-end'),
});
