const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  backendUrl: process.env.FTDESK_BACKEND_URL || "http://127.0.0.1:8766",
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
  },
});
