const { contextBridge, ipcRenderer } = require("electron");

const CHANNEL_EVENT = "epstein:p2p:annotation-event";
const CHANNEL_PUBLISH = "epstein:p2p:publish-annotation-event";
const CHANNEL_STATE = "epstein:p2p:state";

contextBridge.exposeInMainWorld("epsteinP2P", {
  publishAnnotationEvent(payload) {
    return ipcRenderer.invoke(CHANNEL_PUBLISH, payload);
  },
  getState() {
    return ipcRenderer.invoke(CHANNEL_STATE);
  },
  onAnnotationEvent(handler) {
    if (typeof handler !== "function") {
      return () => {};
    }
    const wrapped = (_event, payload) => {
      handler(payload);
    };
    ipcRenderer.on(CHANNEL_EVENT, wrapped);
    return () => {
      ipcRenderer.removeListener(CHANNEL_EVENT, wrapped);
    };
  },
});
