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
const DEBUG_MULTI_PEER = process.env.ELECTRON_DEBUG_MULTI === "1";
const DEBUG_CHILD = process.env.ELECTRON_DEBUG_CHILD === "1";
const FORCED_APP_URL = process.env.ELECTRON_APP_URL || "";
const USER_DATA_SUFFIX = process.env.ELECTRON_USER_DATA_SUFFIX || "";

let djangoProcess = null;
let quitting = false;
let appUrl = `http://${DJANGO_HOST}:${DJANGO_PORT}/`;
let p2pNode = null;
let p2pStarted = false;
let debugPeerProcess = null;
const p2pDialedPeers = new Set();

const LIBP2P_TOPIC = process.env.LIBP2P_TOPIC || "epstein/annotations/v1";
const LIBP2P_ANN_STREAM_PROTOCOL = "/epstein/annotations/1.0.0";
const LIBP2P_BOOTSTRAP = (process.env.LIBP2P_BOOTSTRAP || "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const LIBP2P_LISTEN = (process.env.LIBP2P_LISTEN || "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);

if (USER_DATA_SUFFIX) {
  app.setPath("userData", `${app.getPath("userData")}-${USER_DATA_SUFFIX}`);
}

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

function libp2pBootstrapAddrs() {
  if (!p2pNode) {
    return [];
  }
  const peerId = p2pNode.peerId?.toString?.() || "";
  if (!peerId) {
    return [];
  }
  return p2pNode.getMultiaddrs()
    .map((addr) => addr.toString())
    .map((addr) => {
      let normalized = addr;
      // 0.0.0.0 is not dialable for local child process bootstrap.
      if (normalized.startsWith("/ip4/0.0.0.0/")) {
        normalized = normalized.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/");
      }
      if (!normalized.includes("/p2p/")) {
        normalized = `${normalized}/p2p/${peerId}`;
      }
      return normalized;
    })
    .filter(Boolean);
}

function broadcastAnnotationEvent(payload) {
  const windows = BrowserWindow.getAllWindows();
  const kind = payload?.kind || "unknown";
  const pdf = payload?.pdf || "n/a";
  logP2P(`broadcast kind=${kind} pdf=${pdf} windows=${windows.length}`);
  for (const window of windows) {
    if (!window.isDestroyed()) {
      window.webContents.send("epstein:p2p:annotation-event", payload);
    }
  }
}

function relayToLocalWindows(payload, sourceWebContentsId = null) {
  const windows = BrowserWindow.getAllWindows();
  let relayed = 0;
  for (const window of windows) {
    if (window.isDestroyed()) {
      continue;
    }
    if (sourceWebContentsId != null && window.webContents.id === sourceWebContentsId) {
      continue;
    }
    window.webContents.send("epstein:p2p:annotation-event", payload);
    relayed += 1;
  }
  if (relayed > 0) {
    const kind = payload?.kind || "unknown";
    const pdf = payload?.pdf || "n/a";
    logP2P(`relay local kind=${kind} pdf=${pdf} targets=${relayed}`);
  }
}

function relayToDebugPeerProcess(payload) {
  if (!debugPeerProcess || !DEBUG_MULTI_PEER) {
    return;
  }
  if (!debugPeerProcess.connected) {
    return;
  }
  try {
    debugPeerProcess.send({ type: "annotation-event", payload });
    const kind = payload?.kind || "unknown";
    const pdf = payload?.pdf || "n/a";
    logP2P(`relay debug child kind=${kind} pdf=${pdf}`);
  } catch (error) {
    logP2P(`relay debug child failed (${error.message})`);
  }
}

function decodeChunkToString(chunk) {
  if (!chunk) return "";
  if (typeof chunk === "string") return chunk;
  if (chunk instanceof Uint8Array) {
    return new TextDecoder().decode(chunk);
  }
  if (typeof chunk.subarray === "function") {
    try {
      return new TextDecoder().decode(chunk.subarray());
    } catch (_error) {
      return "";
    }
  }
  return "";
}

async function publishViaDirectPeerStreams(payload) {
  if (!p2pNode) {
    return;
  }
  const peers = typeof p2pNode.getPeers === "function" ? p2pNode.getPeers() : [];
  if (!Array.isArray(peers) || peers.length === 0) {
    logP2P("direct stream skipped (no connected peers)");
    return;
  }
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  for (const peerId of peers) {
    const peer = peerId?.toString?.() || "unknown";
    try {
      // eslint-disable-next-line no-await-in-loop
      const stream = await p2pNode.dialProtocol(peerId, LIBP2P_ANN_STREAM_PROTOCOL);
      // eslint-disable-next-line no-await-in-loop
      await stream.sink((async function* writeOnce() {
        yield bytes;
      }()));
      logP2P(`direct send ok peer=${peer} bytes=${bytes.length}`);
    } catch (error) {
      logP2P(`direct send failed peer=${peer} (${error.message})`);
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
  logP2P("init start");
  if (p2pNode) {
    logP2P("init skipped (already started)");
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

    const listen = LIBP2P_LISTEN.length > 0
      ? LIBP2P_LISTEN
      : ["/ip4/0.0.0.0/tcp/0", "/ip4/0.0.0.0/tcp/0/ws"];
    const peerDiscovery = [];
    if (LIBP2P_BOOTSTRAP.length > 0) {
      peerDiscovery.push(bootstrapPkg.bootstrap({ list: LIBP2P_BOOTSTRAP }));
    }
    logP2P(`mode=${DEBUG_CHILD ? "child" : "primary"} topic=${LIBP2P_TOPIC}`);
    if (LIBP2P_BOOTSTRAP.length > 0) {
      logP2P(`bootstrap=${LIBP2P_BOOTSTRAP.join(", ")}`);
    }

    p2pNode = await libp2pPkg.createLibp2p({
      addresses: { listen },
      transports: [tcpPkg.tcp(), webSocketsPkg.webSockets()],
      connectionEncrypters: [noisePkg.noise()],
      peerDiscovery,
      services: {
        identify: identifyPkg.identify(),
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

    p2pNode.handle(LIBP2P_ANN_STREAM_PROTOCOL, async ({ stream, connection }) => {
      const remote = connection?.remotePeer?.toString?.() || "unknown";
      try {
        for await (const chunk of stream.source) {
          const text = decodeChunkToString(chunk);
          if (!text) {
            continue;
          }
          const parsed = JSON.parse(text);
          if (parsed && typeof parsed === "object") {
            logP2P(`direct recv peer=${remote}`);
            broadcastAnnotationEvent(parsed);
          }
        }
      } catch (error) {
        logP2P(`direct recv error peer=${remote} (${error.message})`);
      }
    });
    logP2P(`direct protocol ready ${LIBP2P_ANN_STREAM_PROTOCOL}`);

    p2pNode.addEventListener("peer:discovery", async (event) => {
      const peerId = event?.detail?.id;
      const id = peerId?.toString?.() || "unknown";
      logP2P(`discovered peer=${id}`);
      if (!peerId || p2pDialedPeers.has(id)) {
        return;
      }
      p2pDialedPeers.add(id);
      try {
        await p2pNode.dial(peerId);
        logP2P(`dial ok peer=${id}`);
      } catch (error) {
        logP2P(`dial failed peer=${id} (${error.message})`);
      }
    });
    p2pNode.addEventListener("peer:connect", (event) => {
      const id = event?.detail?.toString?.() || event?.detail?.remotePeer?.toString?.() || "unknown";
      logP2P(`connected peer=${id}`);
    });

    if (LIBP2P_BOOTSTRAP.length > 0) {
      logP2P("awaiting peer discovery for explicit peer dial");
    }
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
    title: DEBUG_CHILD ? "Epstein Studio (Peer 2)" : "Epstein Studio",
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

function startDebugPeer() {
  if (!DEBUG_MULTI_PEER || DEBUG_CHILD || debugPeerProcess) {
    return;
  }
  const entryArgs = process.argv.slice(1);
  if (entryArgs.length === 0) {
    logP2P("debug peer skipped (missing electron entrypoint args)");
    return;
  }
  const bootstrapAddrs = libp2pBootstrapAddrs();
  const env = {
    ...process.env,
    ELECTRON_DEBUG_MULTI: "0",
    ELECTRON_DEBUG_CHILD: "1",
    ELECTRON_USER_DATA_SUFFIX: "peer-2",
    ELECTRON_APP_URL: appUrl,
  };
  if (bootstrapAddrs.length > 0) {
    env.LIBP2P_BOOTSTRAP = bootstrapAddrs.join(",");
  }
  debugPeerProcess = spawn(process.execPath, entryArgs, {
    stdio: ["inherit", "inherit", "inherit", "ipc"],
    env,
  });
  debugPeerProcess.on("message", (message) => {
    if (!message || message.type !== "annotation-event") {
      return;
    }
    const payload = message.payload;
    const kind = payload?.kind || "unknown";
    const pdf = payload?.pdf || "n/a";
    logP2P(`relay from debug child kind=${kind} pdf=${pdf}`);
    broadcastAnnotationEvent(payload);
  });
  debugPeerProcess.on("exit", () => {
    debugPeerProcess = null;
  });
}

function stopDebugPeer() {
  if (!debugPeerProcess) {
    return;
  }
  debugPeerProcess.kill("SIGTERM");
  debugPeerProcess = null;
}

ipcMain.handle("epstein:p2p:state", async () => p2pStateSnapshot());

ipcMain.handle("epstein:p2p:publish-annotation-event", async (_event, payload) => {
  const kind = payload?.kind || "unknown";
  const pdf = payload?.pdf || "n/a";
  logP2P(`publish request kind=${kind} pdf=${pdf}`);
  if (!p2pNode || !p2pStarted || !p2pNode.services?.pubsub) {
    logP2P("publish rejected (p2p unavailable)");
    return { ok: false, error: "p2p_unavailable" };
  }
  if (!payload || typeof payload !== "object") {
    logP2P("publish rejected (invalid payload)");
    return { ok: false, error: "invalid_payload" };
  }
  try {
    const subscribers = p2pNode.services.pubsub.getSubscribers(LIBP2P_TOPIC);
    logP2P(`publish peers topic=${LIBP2P_TOPIC} subscribers=${subscribers.length}`);
    const bytes = new TextEncoder().encode(JSON.stringify(payload));
    await p2pNode.services.pubsub.publish(LIBP2P_TOPIC, bytes);
    logP2P(`publish ok topic=${LIBP2P_TOPIC} bytes=${bytes.length}`);
    if (subscribers.length === 0) {
      await publishViaDirectPeerStreams(payload);
    }
    // Local debug helper: mirror events between app windows even if gossipsub delivery lags.
    relayToLocalWindows(payload, _event?.sender?.id ?? null);
    relayToDebugPeerProcess(payload);
    if (DEBUG_CHILD && typeof process.send === "function") {
      process.send({ type: "annotation-event", payload });
      logP2P("relay debug parent");
    }
    return { ok: true };
  } catch (error) {
    logP2P(`publish error (${error.message})`);
    return { ok: false, error: "publish_failed" };
  }
});

if (DEBUG_CHILD) {
  process.on("message", (message) => {
    if (!message || message.type !== "annotation-event") {
      return;
    }
    const payload = message.payload;
    const kind = payload?.kind || "unknown";
    const pdf = payload?.pdf || "n/a";
    logP2P(`relay from debug parent kind=${kind} pdf=${pdf}`);
    broadcastAnnotationEvent(payload);
  });
}

async function bootstrap() {
  try {
    logP2P("bootstrap begin");
    await startP2PNode();

    if (FORCED_APP_URL) {
      appUrl = FORCED_APP_URL;
      createWindow();
      startDebugPeer();
      return;
    }

    const configuredUrl = buildUrl(DJANGO_PORT);
    const existingAppOnConfiguredPort = await looksLikeEpsteinStudio(configuredUrl);
    if (existingAppOnConfiguredPort) {
      appUrl = configuredUrl;
      createWindow();
      startDebugPeer();
      return;
    }

    const configuredPortFree = await isPortFree(DJANGO_HOST, DJANGO_PORT);
    const portToUse = configuredPortFree
      ? DJANGO_PORT
      : await findFreePort(DJANGO_HOST, DJANGO_PORT + 1, PORT_SCAN_LIMIT);

    await startDjangoServer(portToUse);
    appUrl = buildUrl(portToUse);
    createWindow();
    startDebugPeer();
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
  stopDebugPeer();
  void stopP2PNode();
  stopDjangoServer();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
