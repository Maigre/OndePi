// =============================================================================
// OndePi M5Stack Core Interface
// =============================================================================
// Hardware control interface for OndePi streaming server
// Communicates via USB serial using JSON-line protocol
// =============================================================================

#include <M5Unified.h>
#include "config.h"
#include "state.h"
#include "protocol.h"
#include "ui.h"

// -----------------------------------------------------------------------------
// Globals
// -----------------------------------------------------------------------------

AppState state;
Protocol protocol(Serial);
UI ui;

unsigned long lastUiUpdate = 0;
unsigned long lastSerialPoll = 0;

// -----------------------------------------------------------------------------
// Button Handling
// -----------------------------------------------------------------------------

void handleButtons() {
    unsigned long now = millis();
    bool disconnected = (now - state.lastLevelsReceived > DISCONNECT_TIMEOUT_MS);
    
    // -------------------------------------------------------------------------
    // Button A - Gain Decrease (with auto-repeat)
    // -------------------------------------------------------------------------
    if (M5.BtnA.isPressed()) {
        if (now - state.lastGainRepeatB >= GAIN_REPEAT_MS) {
            state.gainDb -= GAIN_STEP_DB;
            if (state.gainDb < GAIN_MIN_DB) state.gainDb = GAIN_MIN_DB;
            protocol.sendGain(state.gainDb);
            ui.updateGain(state);
            state.lastGainRepeatB = now;
        }
    } else {
        state.lastGainRepeatB = 0;  // Reset for immediate response on next press
    }
    
    // -------------------------------------------------------------------------
    // Button B - Long press to Start/Stop
    // -------------------------------------------------------------------------
    if (M5.BtnB.isPressed()) {
        if (!state.buttonAPressed) {
            // Button just pressed
            state.buttonAPressed = true;
            state.buttonAPressTime = now;
        } else if (state.buttonAPressTime > 0 && now - state.buttonAPressTime >= LONG_PRESS_MS) {
            // Long press detected - send command once
            bool cooldownActive = (now - state.lastCommandAt < COMMAND_COOLDOWN_MS);
            if (!disconnected && !cooldownActive && state.pendingAction == PENDING_NONE) {
                if (state.status.streaming) {
                    protocol.sendStop();
                    state.pendingAction = PENDING_STOP;
                } else {
                    protocol.sendStart();
                    state.pendingAction = PENDING_START;
                }
                state.pendingSince = now;
                state.lastCommandAt = now;
                state.needsFullRedraw = true;
            }
            // Disable further triggers until button is released
            state.buttonAPressTime = 0;  // Mark as already triggered
        }
    } else {
        state.buttonAPressed = false;
        // Don't reset buttonAPressTime here - it stays 0 until next press
    }
    
    // -------------------------------------------------------------------------
    // Button C - Gain Increase (with auto-repeat)
    // -------------------------------------------------------------------------
    if (M5.BtnC.isPressed()) {
        if (now - state.lastGainRepeatC >= GAIN_REPEAT_MS) {
            state.gainDb += GAIN_STEP_DB;
            if (state.gainDb > GAIN_MAX_DB) state.gainDb = GAIN_MAX_DB;
            protocol.sendGain(state.gainDb);
            ui.updateGain(state);
            state.lastGainRepeatC = now;
        }
    } else {
        state.lastGainRepeatC = 0;
    }
}

// -----------------------------------------------------------------------------
// Main Loop Tasks
// -----------------------------------------------------------------------------

void updateUI() {
    unsigned long now = millis();
    
    if (now - lastUiUpdate < UI_UPDATE_MS) return;
    lastUiUpdate = now;
    
    // Clear pending status if no update arrives in time
    if (state.pendingAction != PENDING_NONE && now - state.pendingSince > PENDING_TIMEOUT_MS) {
        state.pendingAction = PENDING_NONE;
        state.needsFullRedraw = true;
    }

    // Update smoothed meter values
    updateSmoothedLevels(state.levels, UI_UPDATE_MS / 1000.0f);
    
    // Check if we should show/hide disconnect overlay
    bool disconnected = (now - state.lastLevelsReceived > DISCONNECT_TIMEOUT_MS);
    
    if (disconnected) {
        ui.showDisconnectOverlay(state);
        return;  // Don't update meters etc. while overlay is shown
    } else {
        ui.hideDisconnectOverlay(state);  // Will trigger full redraw if overlay was shown
    }
    
    // Full redraw if needed
    if (state.needsFullRedraw) {
        ui.drawFullScreen(state);
        state.needsFullRedraw = false;
        return;
    }
    
    // Incremental updates
    ui.updateMeters(state);
    ui.updateClipIndicator(state);
    ui.updateLimiterIndicator(state);
    ui.updateStatus(state);
    ui.updateGain(state);
    ui.updateHoldProgress(state);
}

void pollSerial() {
    unsigned long now = millis();
    
    if (now - lastSerialPoll < SERIAL_POLL_MS) return;
    lastSerialPoll = now;
    
    // Process all available messages
    while (protocol.poll(state)) {
        // Data received — mark as connected
        state.status.connected = true;
    }
    
    // Send heartbeat periodically
    if (now - state.lastHeartbeat >= HEARTBEAT_MS) {
        protocol.sendPing();
        state.lastHeartbeat = now;
    }
}

// -----------------------------------------------------------------------------
// Setup & Loop
// -----------------------------------------------------------------------------

void setup() {
    // Initialize M5Unified
    auto cfg = M5.config();
    cfg.serial_baudrate = 0;  // We handle serial ourselves in protocol
    cfg.clear_display = true;
    cfg.output_power = false;
    cfg.internal_imu = false;
    cfg.internal_rtc = false;
    cfg.internal_spk = false;
    cfg.internal_mic = false;
    M5.begin(cfg);
    
    // Set LCD brightness
    M5.Display.setBrightness(80);
    
    // Initialize protocol
    protocol.begin();
    
    // Initialize UI
    ui.begin();
    state.needsFullRedraw = true;
    
    // Initial state — overlay will show until server connects
    state.lastLevelsReceived = 0;
}

void loop() {
    // Update M5Stack button states
    M5.update();
    
    // Handle button inputs
    handleButtons();
    
    // Poll serial for incoming data
    pollSerial();
    
    // Update display
    updateUI();
    
    // Small delay to prevent tight loop
    delay(1);
}
