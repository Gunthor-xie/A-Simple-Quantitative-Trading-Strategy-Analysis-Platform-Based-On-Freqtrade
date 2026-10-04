const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("path");

const BACKEND_URL = process.env.FTDESK_BACKEND_URL || "http://127.0.0.1:8766";

function createWindow() {
  const win = new BrowserWindow({
    width: 1480,
    height: 940,
    title: "Freqtrade Desktop",
    backgroundColor: "#14161c",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  const devUrl = process.env.VITE_DEV_SERVER_URL || "http://127.0.0.1:5173";
  if (process.env.NODE_ENV === "development") {
    win.loadURL(devUrl);
  } else {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
  return win;
}

app.whenReady().then(() => {
  ipcMain.handle("backend-url", () => BACKEND_URL);
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
