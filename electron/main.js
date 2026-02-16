const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");

const isLinux = process.platform === "linux";
const explicitLinuxPlatform = process.env.ELECTRON_OZONE_PLATFORM || process.env.OZONE_PLATFORM || "";
const explicitLinuxHint = process.env.ELECTRON_OZONE_PLATFORM_HINT || "";

let resolvedLinuxPlatform = "";
if (explicitLinuxPlatform) {
  resolvedLinuxPlatform = explicitLinuxPlatform;
} else if (explicitLinuxHint === "x11" || explicitLinuxHint === "wayland") {
  resolvedLinuxPlatform = explicitLinuxHint;
} else {
  resolvedLinuxPlatform = "x11";
}

const disableGpuEnv = process.env.ELECTRON_DISABLE_GPU || "";
const shouldDisableGpu = disableGpuEnv === "1" || (isLinux && resolvedLinuxPlatform === "wayland");

if (shouldDisableGpu) {
  app.disableHardwareAcceleration();
}

if (isLinux) {
  if (explicitLinuxPlatform) {
    app.commandLine.appendSwitch("ozone-platform", explicitLinuxPlatform);
  } else if (explicitLinuxHint) {
    app.commandLine.appendSwitch("ozone-platform-hint", explicitLinuxHint);
  } else {
    app.commandLine.appendSwitch("enable-features", "UseOzonePlatform");
    app.commandLine.appendSwitch("ozone-platform", "x11");
  }
  if (shouldDisableGpu) {
    app.commandLine.appendSwitch("disable-gpu-compositing");
  }
}

const DJANGO_HOST = process.env.ELECTRON_DJANGO_HOST || "127.0.0.1";
const DJANGO_PORT = Number.parseInt(process.env.ELECTRON_DJANGO_PORT || "8000", 10);
const SERVER_WAIT_TIMEOUT_MS = 30_000;
const SERVER_RETRY_INTERVAL_MS = 250;
const PORT_SCAN_LIMIT = 50;

let djangoProcess = null;
let quitting = false;
let appUrl = `http://${DJANGO_HOST}:${DJANGO_PORT}/`;
let p2pNode = null;
let p2pStarted = false;

const LIBP2P_TOPIC = process.env.LIBP2P_TOPIC || "epstein/annotations/v1";
const LIBP2P_BOOTSTRAP = (process.env.LIBP2P_BOOTSTRAP || "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const LIBP2P_LISTEN = (process.env.LIBP2P_LISTEN || "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);

function logP2P(message) {
  console.log(`[libp2p] ${message}`);
}

function p2pStateSnapshot() {
  return {
    enabled: Boolean(p2pNode && p2pStarted),
    peerId: p2pNode?.peerId?.toString?.() || null,
    topic: LIBP2P_TOPIC,
    listen: p2pNode ? p2pNode.getMultiaddrs().map((addr) => addr.toString()) : [],
  };
}

function broadcastAnnotationEvent(payload) {
  for (const window of BrowserWindow.getAllWindows()) {
    if (!window.isDestroyed()) {
      window.webContents.send("epstein:p2p:annotation-event", payload);
    }
  }
}

function canRun(cmd, args = ["--version"]) {
  const result = spawnSync(cmd, args, { stdio: "ignore" });
  return result.status === 0;
}

function pickServerCommand() {
  if (canRun("uv")) {
    return {
      cmd: "uv",
      args: ["run", "python", "backend/manage.py", "runserver"],
    };
  }
  if (canRun("python3")) {
    return {
      cmd: "python3",
      args: ["backend/manage.py", "runserver"],
    };
  }
  if (canRun("python")) {
    return {
      cmd: "python",
      args: ["backend/manage.py", "runserver"],
    };
  }
  throw new Error("Could not find uv, python3, or python in PATH.");
}

function buildUrl(port) {
  return `http://${DJANGO_HOST}:${port}/`;
}

function waitForServer(url, timeoutMs) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tryConnect = () => {
      const request = http.get(url, (res) => {
        res.resume();
        resolve();
      });

      request.on("error", () => {
        if (Date.now() - start >= timeoutMs) {
          reject(new Error(`Django server did not start within ${timeoutMs}ms.`));
          return;
        }
        setTimeout(tryConnect, SERVER_RETRY_INTERVAL_MS);
      });
    };
    tryConnect();
  });
}

function isPortFree(host, port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, host);
  });
}

function looksLikeEpsteinStudio(url) {
  return new Promise((resolve) => {
    const request = http.get(url, (res) => {
      let body = "";
      res.on("data", (chunk) => {
        if (body.length < 8192) {
          body += chunk.toString();
        }
      });
      res.on("end", () => {
        const signature = body.toLowerCase();
        resolve(signature.includes("epstein studio"));
      });
    });
    request.on("error", () => resolve(false));
    request.setTimeout(2000, () => {
      request.destroy();
      resolve(false);
    });
  });
}

async function findFreePort(host, startPort, maxTries) {
  for (let offset = 0; offset <= maxTries; offset += 1) {
    const candidate = startPort + offset;
    // eslint-disable-next-line no-await-in-loop
    const free = await isPortFree(host, candidate);
    if (free) {
      return candidate;
    }
  }
  throw new Error(`No free port found in range ${startPort}-${startPort + maxTries}.`);
}

function startDjangoServer(port) {
  const command = pickServerCommand();
  const args = [...command.args, `${DJANGO_HOST}:${port}`, "--noreload"];
  const cwd = path.resolve(__dirname, "..");
  djangoProcess = spawn(command.cmd, args, {
    cwd,
    stdio: "inherit",
    env: {
      ...process.env,
      DJANGO_DEBUG: process.env.DJANGO_DEBUG || "true",
    },
  });

  djangoProcess.on("exit", (code) => {
    djangoProcess = null;
    if (!quitting && code !== 0) {
      dialog.showErrorBox("Epstein Studio", "Django server exited unexpectedly.");
      app.quit();
    }
  });

  return waitForServer(buildUrl(port), SERVER_WAIT_TIMEOUT_MS);
}

function stopDjangoServer() {
  if (!djangoProcess) {
    return;
  }
  djangoProcess.kill("SIGTERM");
  djangoProcess = null;
}

async function startP2PNode() {
  if (p2pNode) {
    return;
  }
  try {
    const libp2pPkg = await import("libp2p");
    const noisePkg = await import("@chainsafe/libp2p-noise");
    const gossipsubPkg = await import("@chainsafe/libp2p-gossipsub");
    const tcpPkg = await import("@libp2p/tcp");
    const webSocketsPkg = await import("@libp2p/websockets");
    const bootstrapPkg = await import("@libp2p/bootstrap");
    const identifyPkg = await import("@libp2p/identify");
    const dhtPkg = await import("@libp2p/kad-dht");

    const listen = LIBP2P_LISTEN.length > 0
      ? LIBP2P_LISTEN
      : ["/ip4/0.0.0.0/tcp/0", "/ip4/0.0.0.0/tcp/0/ws"];
    const peerDiscovery = [];
    if (LIBP2P_BOOTSTRAP.length > 0) {
      peerDiscovery.push(bootstrapPkg.bootstrap({ list: LIBP2P_BOOTSTRAP }));
    }

    p2pNode = await libp2pPkg.createLibp2p({
      addresses: { listen },
      transports: [tcpPkg.tcp(), webSocketsPkg.webSockets()],
      connectionEncryption: [noisePkg.noise()],
      peerDiscovery,
      services: {
        identify: identifyPkg.identify(),
        dht: dhtPkg.kadDHT(),
        pubsub: gossipsubPkg.gossipsub({ allowPublishToZeroTopicPeers: true }),
      },
    });

    await p2pNode.start();
    p2pStarted = true;
    logP2P(`started peerId=${p2pNode.peerId.toString()}`);
    const addresses = p2pNode.getMultiaddrs().map((addr) => addr.toString()).join(", ");
    logP2P(`listen=${addresses || "none"}`);

    if (p2pNode.services?.pubsub) {
      p2pNode.services.pubsub.subscribe(LIBP2P_TOPIC);
      logP2P(`subscribed topic=${LIBP2P_TOPIC}`);
      p2pNode.services.pubsub.addEventListener("message", (event) => {
        const from = event?.detail?.from?.toString?.() || "unknown";
        const size = event?.detail?.data?.length || 0;
        logP2P(`message topic=${LIBP2P_TOPIC} from=${from} bytes=${size}`);
        try {
          const raw = event?.detail?.data;
          if (!raw) return;
          const parsed = JSON.parse(new TextDecoder().decode(raw));
          if (parsed && typeof parsed === "object") {
            broadcastAnnotationEvent(parsed);
          }
        } catch (error) {
          logP2P(`message decode error (${error.message})`);
        }
      });
    }

    p2pNode.addEventListener("peer:discovery", (event) => {
      const id = event?.detail?.id?.toString?.() || "unknown";
      logP2P(`discovered peer=${id}`);
    });
  } catch (error) {
    // Keep app functional even when p2p dependencies are not available yet.
    p2pStarted = false;
    logP2P(`disabled (${error.message})`);
  }
}

async function stopP2PNode() {
  if (!p2pNode) {
    return;
  }
  try {
    await p2pNode.stop();
    logP2P("stopped");
  } catch (error) {
    logP2P(`stop error (${error.message})`);
  } finally {
    p2pStarted = false;
    p2pNode = null;
  }
}

function createWindow() {
  const mainWindow = new BrowserWindow({
    title: "Epstein Studio",
    width: 1600,
    height: 980,
    minWidth: 1200,
    minHeight: 760,
    frame: true,
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  mainWindow.loadURL(appUrl);
}

ipcMain.handle("epstein:p2p:state", async () => p2pStateSnapshot());

ipcMain.handle("epstein:p2p:publish-annotation-event", async (_event, payload) => {
  if (!p2pNode || !p2pStarted || !p2pNode.services?.pubsub) {
    return { ok: false, error: "p2p_unavailable" };
  }
  if (!payload || typeof payload !== "object") {
    return { ok: false, error: "invalid_payload" };
  }
  try {
    const bytes = new TextEncoder().encode(JSON.stringify(payload));
    await p2pNode.services.pubsub.publish(LIBP2P_TOPIC, bytes);
    return { ok: true };
  } catch (error) {
    logP2P(`publish error (${error.message})`);
    return { ok: false, error: "publish_failed" };
  }
});

async function bootstrap() {
  try {
    await startP2PNode();

    const configuredUrl = buildUrl(DJANGO_PORT);
    const existingAppOnConfiguredPort = await looksLikeEpsteinStudio(configuredUrl);
    if (existingAppOnConfiguredPort) {
      appUrl = configuredUrl;
      createWindow();
      return;
    }

    const configuredPortFree = await isPortFree(DJANGO_HOST, DJANGO_PORT);
    const portToUse = configuredPortFree
      ? DJANGO_PORT
      : await findFreePort(DJANGO_HOST, DJANGO_PORT + 1, PORT_SCAN_LIMIT);

    await startDjangoServer(portToUse);
    appUrl = buildUrl(portToUse);
    createWindow();
  } catch (error) {
    dialog.showErrorBox(
      "Epstein Studio",
      `Failed to start desktop app.\n\n${error.message}`
    );
    app.quit();
  }
}

app.whenReady().then(bootstrap);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  quitting = true;
  void stopP2PNode();
  stopDjangoServer();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
