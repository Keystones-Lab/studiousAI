const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("studious", {
  appName: "StudiousAI",
  platform: process.platform,
});
