const { contextBridge, ipcRenderer } = require('electron');
const invoke =
  (name) =>
  (...args) =>
    ipcRenderer.invoke(name, ...args);
contextBridge.exposeInMainWorld('tablink', {
  getState: invoke('getState'),
  getLogs: invoke('getLogs'),
  setConfig: invoke('setConfig'),
  selectDevice: invoke('selectDevice'),
  forgetDevice: invoke('forgetDevice'),
  connectIp: invoke('connectIp'),
  pair: invoke('pair'),
  hide: invoke('hide'),
  quit: invoke('quit'),
  onState: (cb) => ipcRenderer.on('state', (_, v) => cb(v)),
  onLog: (cb) => ipcRenderer.on('log', (_, v) => cb(v)),
});
