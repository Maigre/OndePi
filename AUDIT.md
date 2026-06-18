# OndePi — Architecture & Reliability Audit

**Date:** 2026-06-18
**Repo state at audit:** `main` fast-forwarded `e9531bb → 73bcf20` (local was 8 commits behind `origin/main`).
**Live reference unit:** RPi `ondepi-2` @ `192.168.8.131` (Debian 13 / trixie, kernel 6.12, aarch64), service `ondepi.service` running from `/opt/OndePi`.

---

## 1. Executive summary

OndePi's core data path (ALSA → metering/gain/limiter → ffmpeg → Icecast, plus webradio fallback, web UI, and M5Stack serial control) is reasonable and the recent ring-buffer/in-place-DSP work meaningfully improved the audio thread. The problems the operator feels in the field — **untrustworthy UPLINK/Streaming indicators, clicks, and fragility on weak links** — trace to a small number of structural gaps:

1. **No logging is configured** → field diagnosis is nearly impossible (now fixed, Phase 0).
2. **Status is inferred from local process liveness, never from server truth** → both indicators lie under flaky-network and DNS-failure conditions.
3. **Weak-uplink backpressure drops whole audio chunks** → audible clicks; the "limiter" is a static `tanh` waveshaper, not a limiter.
4. **Operational brittleness** around clock/DNS/Tailscale, device indexing, deployment, and an unauthenticated control API.

The live unit's red uplink was a 4-layer cascading failure (clock → Tailscale → DNS), now remediated (Section 3).

---

## 2. Two structural facts that frame everything

### 2.1 Logging was dead (FIXED in this pass)
There was **no `logging.basicConfig`/`dictConfig` anywhere**; `general.log_level` (someone had bumped it to `"debug"`) was **never wired**. The Pi's journal for an entire boot was **6 lines**, all from uvicorn. Every `logger.info/debug` in `audio/streamer/serial/webradio/api` was discarded (root at WARNING, no handler). This is the meta-reason field issues are hard to diagnose.

### 2.2 `tls = true` is a no-op
`Streamer.build_ffmpeg_command()` always emits `icecast://…` (plain HTTP). The config flag, the web UI checkbox (hard-codes `tls:true`), and the uplink probe (raw TCP) **disagree about whether TLS is in play**. Either wire TLS end-to-end or delete the flag.

---

## 3. Live device: red uplink root cause + remediation (DONE)

**Root cause chain (proven):**
1. **No RTC, no time sync** — `RTC time: n/a`, `System clock synchronized: no`. The Pi booted ~20 days slow (thought it was May 29; real date Jun 18).
2. **Tailscale logged out** — with the stale clock its control-plane TLS cert read as *"not yet valid"* (`current time 2026-05-29 … is before 2026-06-04`).
3. **Tailscale still owned `/etc/resolv.conf`** (`nameserver 100.100.100.100`, MagicDNS) which was dead because Tailscale was down → **all DNS failed**.
4. OndePi's uplink check `socket.create_connection(("stream.ondezero.net", 8005))` failed at name resolution → **UPLINK RED**, even though `eth0` had full internet (proved: `1.1.1.1:443` open; `stream.ondezero.net → 45.13.107.13` via `1.1.1.1`).

The loop was self-reinforcing: `systemd-timesyncd` couldn't fix the clock because it couldn't resolve its NTP pool (DNS dead) → clock stayed wrong → Tailscale stayed down → DNS stayed dead.

**Remediation applied to the live unit:**
- Set the clock from a known-good UTC source; **`uplink_ok` recovered to `True`**.
- Installed `/etc/systemd/timesyncd.conf.d/ondepi-ntp.conf` with **NTP servers by IP** (`162.159.200.123`, `162.159.200.1`, `216.239.35.0/4`, fallback `1.1.1.1`) so the clock self-heals on boot **even when DNS is broken** — this breaks the deadlock permanently.
- `tailscale down` so it no longer hijacks `resolv.conf` (reverted to working `1.1.1.1/1.0.0.1`). To restore the tailnet later, run `tailscale up` once (the cert validates now that the clock is correct).

**Recommended durable hardening for the fleet:** add an RTC HAT or `fake-hwclock`; ship a fallback DNS (`FallbackDNS=` or static `resolv.conf`); ship IP-based NTP by default; don't let Tailscale own DNS while logged out.

---

## 4. The three field observations, root-caused

### 4.1 "Streaming shows ON while the server sees nothing"
`Streamer._monitor_process()` sets `streaming = True` after a **5s grace window** that only scans ffmpeg stderr for error keywords; after grace it calls `process.wait()` and **never consults the error signal again**. So:
- ffmpeg pushing into a black-holed TCP socket (flaky wifi/tethering/Starlink) won't error until the OS retransmit timeout (15–60s+) — `streaming=True` the whole time with zero bytes reaching Icecast.
- A half-open socket makes `process.wait()` block indefinitely → indicator stuck ON.
- Status reflects **local process liveness, never server acknowledgment**; the mount is never confirmed live/fed.

**Fix direction:** "ffmpeg alive" = *connecting/local-ok*; promote to *LIVE* only via **server-side confirmation** (poll AzuraCast `/api/nowplaying` or Icecast `status-json.xsl`) plus an outbound-bytes heartbeat. Force fast reconnect on stall (ffmpeg `-rw_timeout`/socket timeout) instead of waiting for TCP timeout.

### 4.2 "Uplink indicator unreliable"
`UplinkChecker` does a bare TCP connect to `server:port` every 10s — wrong in both directions:
- **False red:** one blip (or dead DNS) flips it red for up to 10s while an established stream is fine; DNS failures can also stall the thread (`getaddrinfo` isn't fully bounded by the 5s connect timeout).
- **False green:** "something accepts TCP on 8005" says nothing about auth, mount availability, or TLS.
- The probe and the real stream path share **no code and no truth** — they can't agree.

**Fix direction:** a layered **connectivity doctor** reporting each rung separately — link up → gateway reachable → **DNS resolves** → server TCP → source auth/mount OK. That panel would have shown "DNS broken / clock wrong" instantly.

### 4.3 "Clicks, probably at the limiter / internal processing"
In likely order:
1. **Dropped audio on weak uplink = clicks.** When the network stalls, ffmpeg stdin backs up → writer thread blocks on `os.write` → ring buffer fills → `put_nowait` **drops whole chunks** → raw splice = click. "Clicks on weak uplink" and "clicks at limits" are the same mechanism. Make loss graceful (insert silence / short crossfade) instead of hard splice.
2. **Allocations in the RT callback** (`indata.copy()`, possible `np.repeat`, `np.ascontiguousarray`, metering temporaries) every callback → nondeterministic malloc/GC latency → xruns. Pre-allocate scratch; meter on decimated/off-thread data.
3. **Blocking `output_stream.write()` inside the input callback** (monitor) can block on a full output buffer → xrun. Route monitor through its own ring buffer/output callback.
4. **Un-ramped gain = zipper clicks** — `gain_db` is read fresh each callback; ramp it across the block.
5. **The "limiter" is a static `tanh` waveshaper** (no lookahead/release). At `drive=1.5` it distorts even below clipping (permanent coloration), not limiting. Replace with a look-ahead peak limiter or honest soft-knee + release; engage only near threshold.

### 4.4 Weak-uplink robustness
- Icecast output has no native reconnect; any drop kills ffmpeg → full reconnect + 5s grace each time → repeated multi-second dropouts on flaky links; fast reconnect races the old connection for the mount.
- Every reconnect **re-resolves DNS** → extra failure mode when DNS is shaky. Pin a resolved IP or run a local caching resolver.
- Old TODO note "*breaking 4g tethering while streaming put everything down*" is the same family: interface churn isn't handled distinctly from ffmpeg crashes.

---

## 5. Findings by area (severity P0 highest → P3 lowest)

### Reliability / observability
- **[P0]** No logging configuration; `log_level` unused. **(Fixed — Section 8.)**
- **[P1]** Streaming/uplink status are local proxies, not server truth (§4.1/§4.2).
- **[P2]** `journald` is volatile-only on the unit (`/var/log/journal` absent) → logs vanish on reboot. Enable bounded persistent journal once logging is live.

### Audio pipeline
- **[P1]** RT-thread allocations + blocking monitor write + chunk drops (§4.3).
- **[P2]** `tanh` mislabeled as limiter; no gain ramping (§4.3).
- **[P2]** Device selected by **numeric PortAudio index** (`alsa_device = 1`); indexes reshuffle across reboot/USB re-enum → "wrong device after reboot." Pin by name / ALSA hw id.
- **[P2]** `/api/test-input` opens the device via `sd.rec` while the always-on `AudioEngine` already holds it (exclusive `hw:`) → usually fails "device busy"; also forces `device=None` when the configured device is a string. Effectively broken.

### Networking / time (ops)
- **[P0 on this unit]** clock/Tailscale/DNS deadlock (§3) — affects any field unit without RTC.
- **[P2]** No fallback DNS, no IP-based NTP by default; Tailscale allowed to own `resolv.conf` while logged out.

### Security
- **[P1]** Web UI binds `0.0.0.0:8090` with **no auth, no TLS**; `GET /api/config` returns the Icecast **password in cleartext**. On tethering/public-wifi/Starlink this is an open control plane. Add auth (token/basic), a bind option, and secret masking in GET.
- **[P3]** `/api/listen` spawns one ffmpeg mp3 encoder **per client** with no concurrency cap (CPU exhaustion on a Pi); it also only carries input audio when *monitor* is enabled (output consumers gated by `_monitor_enabled`), making the feature confusingly silent.

### Deployment / packaging
- **[P1]** `StaticFiles(directory="web")` is a **relative path** (works only if CWD is the repo). The committed unit sets `WorkingDirectory=/opt/OndePi`, **but `install.sh` regenerates the unit *without* `WorkingDirectory`** → fresh installs serve a broken web UI. Resolve `web/` relative to the package.
- **[P2]** The generated `ondepi.service` is both committed and regenerated by `install.sh` ("do not edit") → guaranteed drift (already drifted: `RestartSec` 2 vs 10, paths). Template it or stop committing it.
- **[P2]** Deploy model is "advance a git checkout in `/opt` by hand"; no versioned releases or documented update path.
- **[P3]** Config save rewrites TOML via `tomli_w`, **discarding all comments** from `config.example.toml` after the first UI save.

### Code quality
- **[P2]** `StreamState` is shared across audio callback / API / serial / streamer threads with **no locking** (relies on GIL + whole-object rebinds; works today, fragile tomorrow).
- **[P3]** Deprecated `datetime.utcnow()` and FastAPI `on_event` startup/shutdown (use `lifespan`). API/serial reach into privates (`self._audio_engine._clipper.enabled`).
- **[P3]** Pervasive bare `except Exception: pass` hides faults (compounded by the dead logging).

### Hardware / serial
- **[P2]** On any M5Stack USB re-enumeration, `serial_bridge` deliberately `os._exit(0)` to dodge ALSA/PortAudio corruption → **hot-plugging the controller kills the live stream**. Worth a cleaner boundary (isolate audio from USB events, or run audio in a separate supervised process).
- **[P3]** Protocol doc says levels @ ~30 Hz; bridge sends ~10 Hz. No protocol versioning despite TODO.

### Web UI
- **[P3]** `StreamControls` state machine shows "Streaming" purely from the unreliable `streaming` flag (inherits any backend-truth fix). Password field round-trips cleartext (see Security).

### Testing / docs
- **[P2]** ~180 lines of tests; **none** for API endpoints, the monitor/retry state machine, config round-trip, or the audio callback — exactly the field-failure surfaces.
- **[P3]** `docs/architecture.md` predates the ring buffer, webradio, `/api/listen`, monitor, and uplink subsystems.

---

## 6. Prioritized action plan

**Phase 0 — Stop flying blind (DONE / in progress)**
1. ✅ Wire real logging (`logging_setup.py` + `main.py`), level from `general.log_level`.
2. Enable bounded persistent journal on units.
3. ✅ Fix the live unit's clock/DNS and add IP-NTP self-heal (Section 3).

**Phase 1 — Make indicators tell the truth (IMPLEMENTED in working tree)**
4. ✅ Connectivity doctor (internet anchor → DNS → server TCP) in `/api/status` + UI, replacing the binary uplink probe; reports *why* it's red.
5. ✅ Honest streaming state: `-rw_timeout` on the ffmpeg output, post-grace error handling, stall detection (buffer-backed-up + no drain), and a `stream_phase` lifecycle (stopped/connecting/live/stalled/error) surfaced to the UI.
5b. ⏳ *Server-confirmed* LIVE deferred: the reference server is **Liquidsoap harbor**, which has no generic Icecast `status-json.xsl`; true server confirmation needs per-deployment config (e.g. AzuraCast nowplaying API). Hook left for a follow-up.

**Phase 2 — Kill the clicks (instrumented + root-caused by measurement)**

**Box role:** full-duplex box. It **always** plays webradio → audio-interface
**output** → hardware **FM transmitter**, *and* (when live) captures the input →
server `/input`. The two ffmpegs are by design; webradio must keep running
during a live stream (an earlier attempt to gate it off was **reverted** — it
would cut the FM feed).

The clicks are **input overflow** — the ALSA capture buffer overflowing because
the PortAudio callback isn't serviced in time, dropping captured samples
(inaudible when quiet, a loud click when hot; "worse at higher level"). The
`tanh` limiter (memoryless/continuous) was ruled out.

Method: with logging fixed, `_overflow_count` became a hard metric. Measured on
the Pi 3B+ (20 s windows):

| config | input overflow |
| --- | --- |
| `blocksize=2048`, `latency="high"` | **7.2 / s** |
| `blocksize=0` (auto), `latency="high"` (≈34 ms) | **0 / s** (idle) |
| `blocksize=0`, `latency=0.3` (300 ms) | **0 / s** |

Findings:
- **Forcing `blocksize` is harmful** — `2048` *caused* 7.2 overflows/s; auto
  (`0`) lets PortAudio size buffers for the latency target. (This corrected an
  earlier wrong guess of mine that recommended a large fixed blocksize.)
- `latency="high"` resolves to only **~34 ms** on this device — too small to
  absorb scheduling/GIL jitter under load. Default raised to **0.3 s**.
- Webradio is **not** the cause: input-only (webradio off) overflowed at the
  same rate — so it's capture starvation, not full-duplex clock drift.
- `LimitRTPRIO`/`LimitMEMLOCK` were granted but PortAudio did **not** auto-
  elevate the callback thread to `SCHED_FIFO` (threads stayed `TS`); kept for a
  future explicit-RT attempt. The latency buffer is the actual fix.

Shipped:
6. ✅ RT-callback hygiene: no logging in `_callback`; a non-RT watcher logs
   input overflows (timestamped, deduped); `last_overflow_at` + `actual_latency`
   in `/api/status`; web UI labels glitches **"input xrun"** vs **"buffer drop"**.
7. ✅ `input.blocksize` (default 0) and `input.latency` (default **0.3 s**)
   configurable; device set to `blocksize=0, latency=0.3` → measured **0 / s**.

To verify (needs a real on-air stream): the idle metric is now 0/s; confirm it
stays ~0 under live load and that the clicks are gone. If overflows return under
load, raise `latency` to 0.5 and (next) attempt explicit `SCHED_FIFO` on the
PortAudio thread; longer term a single full-duplex `sd.Stream` removes the
blocking monitor write-in-callback. Remaining audio polish: gain ramping; a real
look-ahead limiter.

**Phase 3 — Harden weak uplink (DONE)**
9. ✅ Jittered reconnect backoff (±20%) to avoid lock-step reconnect storms.
10. ✅ Removed the dead `tls` flag end-to-end (it was a no-op; the source push is
    plain Icecast to a Liquidsoap harbor). Config loading is now **tolerant of
    unknown keys** (warns + drops) so removing a field — or a stale key on a
    deployed unit — never bricks startup.
11. ✅ Reconnect is coupled to the connectivity doctor: when the uplink is down
    (`uplink_ok is False`) the streamer holds the reconnect instead of burning it
    into a dead network, and fires immediately when the link returns (capped at
    60 s so a stuck doctor can't block forever). Combined with Phase 1's
    `-rw_timeout`, interface churn (tethering/Starlink drop) now recovers fast
    without a full teardown, rather than eating connect timeouts.

Deferred (lower value here): pinned-IP/local caching resolver — the doctor
coupling + bounded DNS already cover the failure we actually saw.

**Phase 4 — Security & packaging (PARTIAL — no-auth by choice)**
12. ✅ Password no longer leaks: masked in `GET /api/config` (with
    blank-save-keeps-current so there's no retyping friction), and redacted from
    `/api/status` (ffmpeg `command` + `last_stderr`) and from logs. `/api/listen`
    capped at 3 concurrent encoders so it can't exhaust a Pi.
    ⏭ Auth **intentionally skipped** — LAN is trusted; revisit (token/basic +
    bind-to-localhost) only if units routinely sit on untrusted networks.
13. `web/` `WorkingDirectory` already fixed (install.sh). Remaining: stop
    committing a generated systemd unit; versioned releases + update path.

**Phase 5 — Robustness polish**
14. Pin audio device by name; fix/guard `test_input`; revisit the M5Stack `os._exit` hammer.
15. Tests for API + retry/monitor state machine + config round-trip; refresh `docs/architecture.md`.

---

## 7. Advanced config / "teach it a new Wi-Fi from a phone"

The unit already uses **NetworkManager** (profiles: `interweb`, `gz-catering`, `kxkm-wifi`, `shireen`…), a clean substrate. Options by increasing effort:
- **In-app Network tab** driving `nmcli` (scan, add/forget, signal, priority) — fits the existing web UI, no extra hardware.
- **AP-fallback captive portal** (Comitup / RaspAP / wifi-connect): when no uplink for N seconds, raise an `OndePi-setup` hotspot + captive page to enter Wi-Fi from a phone — the canonical field-provisioning UX.
- **BLE provisioning** (phone app / web-bluetooth) — robust with no network at all; more work.
- **Offline config drop-file on USB** — dead-simple fallback for crews without an app.
- Tie any of these to the **connectivity doctor** so the same panel that shows "DNS broken" offers "Add Wi-Fi" — turning silent failure into guided recovery.

---

## 8. Changes made in this pass (Phase 0)

- **`src/ondepi/logging_setup.py`** (new): stdlib-only `configure_logging(level)` — single idempotent stderr handler (journald-friendly), `ondepi` package at configured level, third-party libs kept at WARNING. Verified: `ondepi.*` INFO/DEBUG emit per level; third-party INFO suppressed; one handler on repeat calls.
- **`src/ondepi/main.py`**: calls `configure_logging(config.general.log_level)` at startup and logs a start banner.
- **`tests/test_logging_setup.py`** (new): level mapping, idempotency, and emission behavior.
- **Live unit** `192.168.8.131`: clock fixed, IP-NTP self-heal drop-in installed, Tailscale DNS hijack released — `uplink_ok` now `True`. **Phase 0 logging deployed + service restarted** — the journal now shows real OndePi module logs (`OndePi starting … log_level=INFO`, `Audio device '1' connected`, `M5Stack on /dev/ttyACM0`, `Webradio playing …`).

### Phase 1 (implemented in working tree — not yet deployed to the unit)
- **`src/ondepi/net_probe.py`** (new, stdlib-only, unit-tested): `resolve_host` (timeout-bounded), `tcp_connect` (+latency), `check_internet` (by-IP anchors), `classify_uplink`.
- **`src/ondepi/uplink.py`**: rewritten as a layered connectivity doctor publishing a structured `UplinkState` (internet/dns/server + reason + resolved IP + latency); logs reason changes.
- **`src/ondepi/state.py`**: `UplinkState` dataclass + `stream_phase`; both exposed via `as_dict()` (back-compat `uplink_ok` retained).
- **`src/ondepi/streamer.py`**: `-rw_timeout` on the Icecast output; post-grace error handling; stall detection (`_watch_live`/`_is_stalled`, drain-progress tracking); `stream_phase` lifecycle.
- **`web/app.js`**: stream dot driven by `stream_phase` (adds "Reconnecting…"); uplink chip shows reason (NO NET / DNS / SERVER) + latency + tooltip.
- **Tests**: `tests/test_net_probe.py` (verified passing here) and streamer stall/`-rw_timeout` tests (CI).

> Note: all code changes are in the working tree only — **not committed/pushed**. Phase 0 (logging) and the clock/DNS remediation are live on the unit; **Phase 1 is not deployed** (the unit still runs `73bcf20` + the Phase 0 logging files).
