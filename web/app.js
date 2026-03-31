// OndePi Web UI

const AppState = { config: null, devices: [], streaming: false, connected: false };

const API = {
  async get(endpoint) {
    const res = await fetch("/api/" + endpoint);
    if (!res.ok) throw new Error("API error");
    return res.json();
  },
  async post(endpoint, data) {
    const res = await fetch("/api/" + endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data || {})
    });
    if (!res.ok) throw new Error("API error");
    return res.json();
  },
  async put(endpoint, data) {
    const res = await fetch("/api/" + endpoint, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data || {})
    });
    if (!res.ok) throw new Error("API error");
    return res.json();
  },
  async patch(endpoint, data) {
    const res = await fetch("/api/" + endpoint, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data || {})
    });
    if (!res.ok) throw new Error("API error");
    return res.json();
  }
};

const Toast = {
  show(msg, type) {
    const c = document.getElementById("toast-container");
    const t = document.createElement("div");
    t.className = "toast " + (type || "");
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(() => t.remove(), 3000);
  }
};

const Navigation = {
  init() {
    document.querySelectorAll("[data-tab]").forEach(link => {
      link.addEventListener("click", e => {
        e.preventDefault();
        this.switchTab(link.dataset.tab);
      });
    });
  },
  switchTab(tabId) {
    document.querySelectorAll(".tab-content").forEach(t => t.classList.remove("active"));
    document.querySelectorAll("[data-tab]").forEach(l => l.classList.remove("active"));
    const tab = document.getElementById("tab-" + tabId);
    if (tab) tab.classList.add("active");
    document.querySelectorAll("[data-tab='" + tabId + "']").forEach(l => l.classList.add("active"));
    if (tabId === "stream") document.getElementById("setup-overlay").classList.add("hidden");
  }
};

const Meters = {
  peakHoldL: { value: 0, time: 0 },
  peakHoldR: { value: 0, time: 0 },
  peakHoldMs: 1000,
  peakDecayPerMs: 0.01,
  smoothL: -60,
  smoothR: -60,
  smoothFactor: 0.6, // 0-1, lower = smoother
  update(rmsLeft, peakLeft, rmsRight, peakRight, limiterActive) {
    const now = Date.now();
    const toDb = v => v > 0 ? 20 * Math.log10(v) : -60;
    const toPct = db => Math.max(0, Math.min(100, (db + 60) / 60 * 100));

    const rawDbL = toDb(peakLeft), rawDbR = toDb(peakRight);
    
    // Exponential moving average for smoothing
    this.smoothL += (rawDbL - this.smoothL) * this.smoothFactor;
    this.smoothR += (rawDbR - this.smoothR) * this.smoothFactor;
    
    const dbL = this.smoothL, dbR = this.smoothR;
    const pctL = toPct(dbL), pctR = toPct(dbR);

    // Update masks (mask covers the unrevealed portion)
    document.getElementById("meter-left").style.width = (100 - pctL) + "%";
    document.getElementById("meter-right").style.width = (100 - pctR) + "%";

    // Peak hold with smooth decay
    const rawPctL = toPct(toDb(peakLeft)), rawPctR = toPct(toDb(peakRight));
    const decayL = Math.max(0, (now - this.peakHoldL.time) * this.peakDecayPerMs);
    const decayR = Math.max(0, (now - this.peakHoldR.time) * this.peakDecayPerMs);
    const nextL = Math.max(0, this.peakHoldL.value - decayL);
    const nextR = Math.max(0, this.peakHoldR.value - decayR);
    if (rawPctL >= nextL) {
      this.peakHoldL = { value: rawPctL, time: now };
    } else {
      this.peakHoldL = { value: nextL, time: now };
    }
    if (rawPctR >= nextR) {
      this.peakHoldR = { value: rawPctR, time: now };
    } else {
      this.peakHoldR = { value: nextR, time: now };
    }
    document.getElementById("peak-left").style.left = this.peakHoldL.value + "%";
    document.getElementById("peak-right").style.left = this.peakHoldR.value + "%";

    // dB display - show peak values, red when limiter active
    const dbLeftEl = document.getElementById("db-left");
    const dbRightEl = document.getElementById("db-right");
    dbLeftEl.textContent = peakLeft > 0 ? toDb(peakLeft).toFixed(1) + " dB" : "-inf";
    dbRightEl.textContent = peakRight > 0 ? toDb(peakRight).toFixed(1) + " dB" : "-inf";
    
    if (limiterActive) {
      dbLeftEl.classList.add("db-limit");
      dbRightEl.classList.add("db-limit");
    } else {
      dbLeftEl.classList.remove("db-limit");
      dbRightEl.classList.remove("db-limit");
    }
  }
};

const GainControl = {
  _sendTimer: null,
  _lastServerDb: null,
  _userDragging: false,
  init() {
    const s = document.getElementById("gain-slider");
    if (s) {
      s.addEventListener("input", () => {
        this._userDragging = true;
        const pct = parseInt(s.value);
        this.updateDisplay(pct);
        this.queueSend(pct);
      });
      s.addEventListener("change", () => {
        const pct = parseInt(s.value);
        this.sendGain(pct);
        this._userDragging = false;
      });
      s.addEventListener("mouseup", () => { this._userDragging = false; });
      s.addEventListener("touchend", () => { this._userDragging = false; });
    }
  },
  pctToDb(pct) {
    if (!pct || pct <= 0) {
      return -60;
    }
    return 20 * Math.log10(pct / 100);
  },
  dbToPct(db) {
    if (db <= -60) return 0;
    return Math.round(Math.pow(10, db / 20) * 100);
  },
  queueSend(pct) {
    if (this._sendTimer) {
      clearTimeout(this._sendTimer);
    }
    this._sendTimer = setTimeout(() => this.sendGain(pct), 80);
  },
  sendGain(pct) {
    const gain_db = this.pctToDb(pct);
    this._lastServerDb = gain_db;
    API.post("gain", { gain_db }).catch(() => Toast.show("Failed", "error"));
  },
  formatDb(pct) {
    if (!pct || pct <= 0) {
      return "-inf dB";
    }
    return this.pctToDb(pct).toFixed(1) + " dB";
  },
  updateDisplay(pct) {
    const valEl = document.getElementById("gain-value");
    valEl.textContent = this.formatDb(pct);
    valEl.classList.remove("gain-warn", "gain-danger");
    if (pct > 120) {
      valEl.classList.add("gain-danger");
    } else if (pct > 100) {
      valEl.classList.add("gain-warn");
    }
  },
  setValue(v) {
    // v is linear gain (1.0 = 100%)
    const pct = Math.min(282, Math.max(0, Math.round(v * 100)));
    document.getElementById("gain-slider").value = pct;
    this.updateDisplay(pct);
  },
  setValueDb(db) {
    // Don't update while user is dragging the slider
    if (this._userDragging) return;
    // Don't update if we just sent this value
    if (this._lastServerDb !== null && Math.abs(db - this._lastServerDb) < 0.1) return;
    const pct = this.dbToPct(db);
    document.getElementById("gain-slider").value = pct;
    this.updateDisplay(pct);
    this._lastServerDb = db;
  }
};

const LimiterControl = {
  init() {
    const t = document.getElementById("limiter-toggle");
    if (t) {
      t.addEventListener("change", () => {
        API.patch("config", { input: { limiter_enabled: t.checked } })
          .then(() => Toast.show(t.checked ? "Limiter enabled" : "Limiter disabled", "success"))
          .catch(() => Toast.show("Failed to update limiter", "error"));
      });
    }
  },
  setValue(enabled) {
    document.getElementById("limiter-toggle").checked = enabled;
  },
  setActive(active) {
    const ind = document.getElementById("limiter-indicator");
    if (active) {
      ind.classList.remove("hidden");
    } else {
      ind.classList.add("hidden");
    }
  }
};

const InputClipIndicator = {
  setActive(active) {
    const ind = document.getElementById("clip-indicator");
    const meters = document.querySelector(".meters");
    if (active) {
      ind.classList.remove("hidden");
      if (meters) meters.classList.add("clip-active");
    } else {
      ind.classList.add("hidden");
      if (meters) meters.classList.remove("clip-active");
    }
  }
};

const MonitorControl = {
  enabled: false,
  locked: false,
  _releaseTimer: null,
  _unlocking: false,
  init() {
    const btn = document.getElementById("btn-monitor");
    btn.addEventListener("mousedown", (e) => { e.preventDefault(); this.onPress(); });
    btn.addEventListener("mouseup", () => this.onRelease());
    btn.addEventListener("mouseleave", () => this.onRelease());
    btn.addEventListener("touchstart", (e) => { e.preventDefault(); this.onPress(); });
    btn.addEventListener("touchend", (e) => { e.preventDefault(); this.onRelease(); });
    btn.addEventListener("dblclick", (e) => { e.preventDefault(); this.onDblClick(); });
    btn.addEventListener("contextmenu", (e) => e.preventDefault());
  },
  onPress() {
    if (this._releaseTimer) {
      clearTimeout(this._releaseTimer);
      this._releaseTimer = null;
    }
    if (this.locked) {
      this.locked = false;
      this._unlocking = true;
      this.setMonitor(false);
      Toast.show("Monitor unlocked", "success");
      return;
    }
    this._unlocking = false;
    this.setMonitor(true);
  },
  onRelease() {
    if (this.locked || this._unlocking) return;
    if (!this.enabled) return;
    this._releaseTimer = setTimeout(() => {
      this._releaseTimer = null;
      if (!this.locked) {
        this.setMonitor(false);
      }
    }, 300);
  },
  onDblClick() {
    if (this._releaseTimer) {
      clearTimeout(this._releaseTimer);
      this._releaseTimer = null;
    }
    this.locked = true;
    this.setMonitor(true);
    Toast.show("Monitor locked", "success");
    this.updateUI();
  },
  async setMonitor(enabled) {
    try {
      const res = await API.post("monitor", { enabled });
      this.enabled = !!res.enabled;
      if (!this.enabled) this.locked = false;
      this.updateUI();
    } catch (e) {
      // ignore errors
    }
  },
  updateUI() {
    const btn = document.getElementById("btn-monitor");
    btn.classList.toggle("active", this.enabled);
    btn.classList.toggle("locked", this.locked);
  },
  setValue(enabled) {
    this.enabled = enabled;
    if (!enabled) this.locked = false;
    this.updateUI();
  }
};

const DeviceSelector = {
  init() {
    document.getElementById("btn-refresh-devices").addEventListener("click", () => this.load());
    const sel = document.getElementById("device-select");
    sel.addEventListener("change", e => this.select(e.target.value));
    sel.addEventListener("click", e => { this._lastValue = sel.value; });
    sel.addEventListener("mouseup", e => {
      setTimeout(() => { if (sel.value === this._lastValue) this.select(sel.value); }, 50);
    });
  },
  _lastValue: null,
  async load() {
    try {
      const data = await API.get("devices");
      AppState.devices = data.devices || [];
      this.render();
    } catch (e) { Toast.show("Failed to load devices", "error"); }
  },
  render() {
    const sel = document.getElementById("device-select");
    const current = AppState.config?.input?.alsa_device || "";
    sel.innerHTML = AppState.devices.map(d =>
      "<option value='" + d.id + "'" + (String(d.id) === String(current) || d.name === current ? " selected" : "") + ">" + d.name + "</option>"
    ).join("") || "<option>No devices</option>";
  },
  async select(deviceId) {
    try {
      const id = parseInt(deviceId);
      const device = (AppState.devices || []).find(d => String(d.id) === String(id));
      const channels = device && device.channels === 1
        ? 1
        : (AppState.config?.input?.channels || 2);
      await API.patch("config", { input: { alsa_device: id, channels } });
      if (AppState.config) {
        if (!AppState.config.input) AppState.config.input = {};
        AppState.config.input.alsa_device = id;
        AppState.config.input.channels = channels;
      }
      Toast.show("Device applied", "success");
    } catch (e) { Toast.show("Failed to apply device", "error"); }
  }
};

const StreamControls = {
  state: "stopped", // stopped, connecting, streaming, error
  init() {
    document.getElementById("btn-connect").addEventListener("click", () => this.toggle());
  },
  async toggle() {
    if (this.state === "streaming") {
      await this.stop();
    } else if (this.state === "stopped" || this.state === "error") {
      await this.connect();
    }
  },
  async connect() {
    // First save config
    const btn = document.getElementById("btn-connect");
    btn.disabled = true;
    btn.textContent = "Saving...";
    this.setState("connecting");
    
    const base = AppState.config || {};
    const cfg = {
      ...base,
      stream: {
        ...(base.stream || {}),
        server: document.getElementById("cfg-host").value,
        port: parseInt(document.getElementById("cfg-port").value) || 8000,
        mount: document.getElementById("cfg-mount").value,
        tls: true,
        username: document.getElementById("cfg-user").value || "source",
        password: document.getElementById("cfg-password").value,
        format: document.getElementById("cfg-format").value,
        bitrate_kbps: parseInt(document.getElementById("cfg-bitrate").value) || 256,
        bitrate_mode: (base.stream && base.stream.bitrate_mode) || "cbr",
        icy: true
      }
    };
    try {
      await API.put("config", cfg);
      AppState.config = cfg;
      btn.textContent = "Connecting...";
      await API.post("stream/start");
    } catch (e) {
      Toast.show("Failed to connect", "error");
      this.setState("stopped");
    }
    btn.disabled = false;
  },
  async stop() {
    const btn = document.getElementById("btn-connect");
    btn.disabled = true;
    try {
      await API.post("stream/stop");
      Toast.show("Stopped", "success");
    } catch (e) {
      Toast.show("Failed to stop", "error");
    }
    btn.disabled = false;
  },
  setState(state) {
    this.state = state;
    const btn = document.getElementById("btn-connect");
    const dot = document.getElementById("stream-status-dot");
    const text = document.getElementById("stream-status-text");
    
    dot.classList.remove("streaming", "connecting", "error");
    btn.classList.remove("btn-success", "btn-danger", "btn-warn", "btn-error");
    
    if (state === "streaming") {
      dot.classList.add("streaming");
      text.textContent = "Streaming";
      btn.textContent = "Stop";
      btn.classList.add("btn-danger");
    } else if (state === "connecting") {
      dot.classList.add("connecting");
      text.textContent = "Connecting...";
      btn.textContent = "Connecting...";
      btn.classList.add("btn-warn");
    } else if (state === "error") {
      dot.classList.add("error");
      text.textContent = "Error";
      btn.textContent = "Retry";
      btn.classList.add("btn-error");
    } else {
      text.textContent = "Stopped";
      btn.textContent = "Connect";
      btn.classList.add("btn-success");
    }
  },
  update(streaming, streamingRequested, lastError) {
    if (streaming && this.state !== "streaming") {
      this.setState("streaming");
    } else if (!streaming && streamingRequested && lastError) {
      this.setState("error");
    } else if (!streaming && this.state === "streaming") {
      this.setState("stopped");
    } else if (!streaming && this.state === "connecting") {
      // Still connecting, wait for it
    } else if (!streaming && this.state !== "connecting") {
      this.setState("stopped");
    }
  }
};

const ConfigForm = {
  _ready: false,
  _saveTimer: null,
  _saveStateTimer: null,
  async load() {
    try {
      const data = await API.get("config");
      AppState.config = data;
      this.populate(data);
      this.checkSetup(data);
      this._ready = true;
      // Also fetch status for runtime values like gain
      const status = await API.get("status");
      if (status.state && typeof status.state.gain_db === "number") {
        GainControl.setValueDb(status.state.gain_db);
      }
    } catch (e) { console.error(e); }
  },
  populate(cfg) {
    const stream = cfg.stream || {};
    const metadata = cfg.metadata || {};
    document.getElementById("cfg-host").value = stream.server || "";
    document.getElementById("cfg-port").value = stream.port || "";
    document.getElementById("cfg-mount").value = stream.mount || "";
    document.getElementById("cfg-user").value = stream.username || "source";
    document.getElementById("cfg-password").value = stream.password || "";
    document.getElementById("cfg-format").value = stream.format || "mp3";
    document.getElementById("cfg-bitrate").value = stream.bitrate_kbps || 256;
  const webradio = cfg.webradio || {};
  document.getElementById("cfg-webradio-url").value = webradio.url || "";
  // Gain is now loaded from status API, not config
  const input = cfg.input || {};
  LimiterControl.setValue(input.limiter_enabled || false);
  },
  checkSetup(cfg) {
    const issues = [];
    const stream = cfg.stream || {};
    if (!stream.server) issues.push("Host not set");
    if (!stream.password) issues.push("Password not set");
    if (!stream.mount) issues.push("Mount not set");
    const overlay = document.getElementById("setup-overlay");
    const ul = document.getElementById("setup-issues");
    if (issues.length > 0) {
      ul.innerHTML = issues.map(i => "<li>" + i + "</li>").join("");
      overlay.classList.remove("hidden");
    } else {
      overlay.classList.add("hidden");
    }
  },
  init() {
    const fields = [
      "cfg-host",
      "cfg-port",
      "cfg-mount",
      "cfg-user",
      "cfg-password",
      "cfg-format",
      "cfg-bitrate",
      "cfg-webradio-url"
    ];
    fields.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      const event = el.type === "checkbox" || el.tagName === "SELECT" ? "change" : "input";
      el.addEventListener(event, () => this.queueSave());
    });
  },
  setSaveState(state) {
    const ind = document.getElementById("status-save-ind");
    if (!ind) return;
    ind.classList.remove("hidden", "saving");
    if (state === "saving") {
      ind.textContent = "Saving...";
      ind.classList.add("saving");
    } else if (state === "saved") {
      ind.textContent = "Saved";
    } else {
      ind.classList.add("hidden");
    }
  },
  queueSave() {
    if (!this._ready) return;
    if (this._saveTimer) clearTimeout(this._saveTimer);
    this.setSaveState("saving");
    this._saveTimer = setTimeout(() => this.saveStream(), 250);
  },
  async saveStream() {
    const payload = {
      stream: {
        server: document.getElementById("cfg-host").value,
        port: parseInt(document.getElementById("cfg-port").value) || 8000,
        mount: document.getElementById("cfg-mount").value,
        tls: true,
        username: document.getElementById("cfg-user").value || "source",
        password: document.getElementById("cfg-password").value,
        format: document.getElementById("cfg-format").value,
        bitrate_kbps: parseInt(document.getElementById("cfg-bitrate").value) || 256,
        bitrate_mode: (AppState.config?.stream && AppState.config.stream.bitrate_mode) || "cbr",
        icy: true
      },
      webradio: {
        url: document.getElementById("cfg-webradio-url").value
      }
    };
    try {
      await API.patch("config", payload);
      if (AppState.config) {
        AppState.config.stream = { ...(AppState.config.stream || {}), ...payload.stream };
        AppState.config.webradio = { ...(AppState.config.webradio || {}), ...payload.webradio };
      }
      this.checkSetup(AppState.config || {});
      this.setSaveState("saved");
      if (this._saveStateTimer) clearTimeout(this._saveStateTimer);
      this._saveStateTimer = setTimeout(() => this.setSaveState("hidden"), 1500);
    } catch (e) {
      Toast.show("Failed to save settings", "error");
      this.setSaveState("hidden");
    }
  }
};

const StatusUpdater = {
  statusInterval: null,
  meterInterval: null,
  errorTimer: null,
  lastError: null,
  errorDismissed: false,
  lastStreaming: null,
  lastCommand: null,
  lastInput: null,
  lastStreamError: null,
  lastStreamStderr: null,
  initialized: false,
  async update() {
    try {
      const s = await API.get("status");
      AppState.connected = true;
      const state = s.state || {};
      if (!this.initialized) {
        this.initialized = true;
        if (state.last_error) {
          this.lastError = state.last_error;
          this.errorDismissed = true;
          this.clearError(true);
        }
      }
      if (this.lastStreaming === null) {
        this.lastStreaming = !!state.streaming;
      } else if (this.lastStreaming !== !!state.streaming) {
        Logs.add(state.streaming ? "Stream started" : "Stream stopped");
        this.lastStreaming = !!state.streaming;
        if (state.streaming && s.stream) {
          if (Array.isArray(s.stream.command) && s.stream.command.length) {
            let cmd = s.stream.command.join(" ");
            if (s.stream.output_url) {
              cmd = cmd.replace(/icecast:\/\/[^\s]+/, s.stream.output_url);
            }
            if (cmd !== this.lastCommand) {
              Logs.add("FFmpeg: " + cmd);
              this.lastCommand = cmd;
            }
          }
          if (s.stream.input) {
            const inputLabel = s.stream.input_device !== null && s.stream.input_device !== undefined
              ? s.stream.input + ":" + s.stream.input_device
              : s.stream.input;
            if (inputLabel !== this.lastInput) {
              Logs.add("Input: " + inputLabel);
              this.lastInput = inputLabel;
            }
          }
          if (s.stream.output_url) {
            Logs.add("Output: " + s.stream.output_url);
          }
        }
      }
      StreamControls.update(state.streaming || false, state.streaming_requested || false, state.last_error);
  AppState.streaming = !!state.streaming;
      if (s.device) {
        const btn = document.getElementById("btn-connect");
        const ready = s.device.status === "connected";
        if (!state.streaming && !ready) {
          btn.disabled = true;
          btn.textContent = "No input";
        } else if (!state.streaming && StreamControls.state === "stopped") {
          btn.disabled = false;
          btn.textContent = "Connect";
        }
      }
      if (s.device && typeof s.device.monitor_enabled === "boolean") {
        MonitorControl.setValue(s.device.monitor_enabled);
      }
      // Webradio indicator
      const radioInd = document.getElementById("radio-indicator");
      if (radioInd) {
        radioInd.classList.toggle("inactive", !(s.webradio && s.webradio.playing));
      }
      if (s.device) {
        const meters = document.querySelector(".meters");
        if (meters) {
          meters.classList.toggle("disabled", s.device.status !== "connected");
        }
        const inputStatus = document.getElementById("input-status");
        const inputHint = document.getElementById("input-hint");
        if (inputStatus) {
          inputStatus.classList.remove("ok", "warn", "err");
          const status = s.device.status || "unknown";
          inputStatus.textContent = "Input: " + status;
          if (status === "connected") inputStatus.classList.add("ok");
          else if (status === "reconnecting") inputStatus.classList.add("warn");
          else if (status === "error") inputStatus.classList.add("err");
        }
        if (inputHint) {
          if (s.device.status !== "connected" && s.device.last_error) {
            inputHint.textContent = s.device.last_error;
          } else if (s.device.sample_rate_mismatch && s.device.device_default_rate) {
            inputHint.textContent = "Device rate " + Math.round(s.device.device_default_rate) + " Hz differs from configured " + s.device.sample_rate + " Hz";
          } else if (s.device.last_stream_status) {
            inputHint.textContent = s.device.last_stream_status;
          } else {
            inputHint.textContent = "";
          }
        }
      }
      if (state.started_at) {
        const started = this.parseStartedAt(state.started_at);
        const now = new Date();
        const duration = Math.floor((now - started) / 1000);
        const h = Math.floor(duration / 3600);
        const m = Math.floor((duration % 3600) / 60);
        const sec = Math.floor(duration % 60);
        document.getElementById("stream-duration").textContent =
          h.toString().padStart(2, "0") + ":" + m.toString().padStart(2, "0") + ":" + sec.toString().padStart(2, "0");
      } else {
        document.getElementById("stream-duration").textContent = "--:--:--";
      }
    document.getElementById("retry-count").textContent = state.retry_count || 0;
    document.getElementById("dropout-count").textContent = s.device?.overflow_count || 0;
      // Uplink status
      const uplinkEl = document.getElementById("uplink-status");
      if (state.uplink_ok === true) {
        uplinkEl.textContent = "OK";
        uplinkEl.className = "uplink-ind uplink-ok";
      } else if (state.uplink_ok === false) {
        uplinkEl.textContent = "FAIL";
        uplinkEl.className = "uplink-ind uplink-fail";
      } else {
        uplinkEl.textContent = "--";
        uplinkEl.className = "uplink-ind";
      }
      this.setConnection(true);
      if (state.last_error) {
        if (!this.errorDismissed || state.last_error !== this.lastError) {
          this.setError(state.last_error);
        }
        const retryCount = state.retry_count || 0;
        const stderrKey = (s.stream?.last_stderr || "") + "|" + retryCount;
        if (s.stream && s.stream.last_error && s.stream.last_error !== this.lastStreamError) {
          Logs.add("Stream error: " + s.stream.last_error, "error");
          this.lastStreamError = s.stream.last_error;
        }
        if (s.stream && s.stream.last_stderr && stderrKey !== this.lastStreamStderr) {
          this.lastStreamStderr = stderrKey;
          const lines = s.stream.last_stderr.split("\n");
          for (const line of lines) {
            if (line.trim()) Logs.add("ffmpeg: " + line.trim(), "warn");
          }
        }
      } else {
        this.clearError(true);
      }
    } catch (e) { this.setConnection(false); }
  },
  setError(message) {
    if (message !== this.lastError) {
      Logs.add(message, "error");
      this.lastError = message;
      this.errorDismissed = false;
    }
    if (this.errorDismissed) {
      return;
    }
    document.getElementById("error-message").textContent = message;
    document.getElementById("error-card").classList.remove("hidden");
    if (!this.errorTimer) {
      this.errorTimer = setTimeout(() => this.clearError(), 4000);
    }
  },
  clearError(reset) {
    document.getElementById("error-card").classList.add("hidden");
    if (this.errorTimer) {
      clearTimeout(this.errorTimer);
      this.errorTimer = null;
    }
    if (reset) {
      this.lastError = null;
      this.errorDismissed = false;
    } else {
      this.errorDismissed = true;
    }
  },
  parseStartedAt(value) {
    if (!value) return new Date();
    const hasTz = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value);
    const iso = hasTz ? value : value + "Z";
    return new Date(iso);
  },
  async updateMeters() {
    try {
      const l = await API.get("levels");
      Meters.update(
        l.rms_left || 0, l.peak_left || 0,
        l.rms_right || 0, l.peak_right || 0,
        l.limiter_active || false
      );
      LimiterControl.setActive(l.limiter_active || false);
      InputClipIndicator.setActive(l.input_clip || false);
      // Sync gain from server (for M5Stack or other changes)
      if (typeof l.gain_db === "number") {
        GainControl.setValueDb(l.gain_db);
      }
    } catch (e) { /* ignore meter errors */ }
  },
  setConnection(ok) {
    const overlay = document.getElementById("disconnect-overlay");
    if (ok) {
      overlay.classList.add("hidden");
    } else {
      overlay.classList.remove("hidden");
    }
  },
  start() {
    this.update();
    this.updateMeters();
    this.statusInterval = setInterval(() => this.update(), 2000);
    this.meterInterval = setInterval(() => this.updateMeters(), 80);
  }
};


const Logs = {
  init() { document.getElementById("btn-clear-logs").addEventListener("click", () => this.clear()); },
  add(msg, level) {
    const c = document.getElementById("log-container");
    const e = document.createElement("div");
    e.textContent = "[" + new Date().toLocaleTimeString() + "] " + msg;
    if (level === "error") e.classList.add("log-error");
    else if (level === "warn") e.classList.add("log-warn");
    c.appendChild(e);
    c.scrollTop = c.scrollHeight;
  },
  clear() { document.getElementById("log-container").innerHTML = ""; }
};

async function init() {
  GainControl.init();
  LimiterControl.init();
  MonitorControl.init();
  StreamControls.init();
  ConfigForm.init();
  DeviceSelector.init();
  Logs.init();
  await ConfigForm.load();
  await DeviceSelector.load();
  StatusUpdater.start();
  Logs.add("UI initialized");
}

document.addEventListener("DOMContentLoaded", init);
