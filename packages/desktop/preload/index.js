const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  getConfig: () => ipcRenderer.invoke('config:load'),
  saveConfig: (data) => ipcRenderer.invoke('config:save', data),
  selectFile: () => ipcRenderer.invoke('file:select'),
  onMenuAction: (callback) => ipcRenderer.on('menu:action', (_, data) => callback(data)),
});
