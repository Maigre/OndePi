#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <Arduino.h>
#include <ArduinoJson.h>
#include "config.h"
#include "state.h"

// =============================================================================
// Serial Protocol Handler
// =============================================================================

class Protocol {
public:
    Protocol(HardwareSerial& serial) : _serial(serial) {}
    
    void begin() {
        _serial.begin(SERIAL_BAUD);
        _serial.setTimeout(SERIAL_TIMEOUT_MS);
    }
    
    // -------------------------------------------------------------------------
    // Send Commands
    // -------------------------------------------------------------------------
    
    void sendStart() {
        JsonDocument doc;
        doc["action"] = "start";
        sendJson(doc);
    }
    
    void sendStop() {
        JsonDocument doc;
        doc["action"] = "stop";
        sendJson(doc);
    }
    
    void sendGain(float db) {
        JsonDocument doc;
        doc["action"] = "gain";
        doc["value"] = db;
        sendJson(doc);
    }
    
    void sendPing() {
        JsonDocument doc;
        doc["action"] = "ping";
        sendJson(doc);
    }
    
    // -------------------------------------------------------------------------
    // Receive Events
    // -------------------------------------------------------------------------
    
    bool poll(AppState& state) {
        if (!_serial.available()) return false;
        
        String line = _serial.readStringUntil('\n');
        line.trim();
        if (line.isEmpty()) return false;
        
        JsonDocument doc;
        DeserializationError error = deserializeJson(doc, line);
        if (error) {
            return false;
        }
        
        const char* type = doc["type"] | "";
        
        if (strcmp(type, "levels") == 0) {
            handleLevels(doc, state);
            return true;
        }
        else if (strcmp(type, "status") == 0) {
            handleStatus(doc, state);
            return true;
        }
        else if (strcmp(type, "gain") == 0) {
            handleGain(doc, state);
            return true;
        }
        
        return false;
    }
    
private:
    HardwareSerial& _serial;
    
    void sendJson(JsonDocument& doc) {
        String output;
        serializeJson(doc, output);
        _serial.println(output);
    }
    
    void handleLevels(JsonDocument& doc, AppState& state) {
        state.lastLevelsReceived = millis();
        
        // Stereo levels
        state.levels.leftRms = doc["left_rms"] | 0.0f;
        state.levels.rightRms = doc["right_rms"] | 0.0f;
        state.levels.leftPeak = doc["left_peak"] | 0.0f;
        state.levels.rightPeak = doc["right_peak"] | 0.0f;
        
        // Fallback for mono (legacy)
        if (!doc["left_rms"].is<float>() && doc["rms"].is<float>()) {
            float rms = doc["rms"] | 0.0f;
            float peak = doc["peak"] | 0.0f;
            state.levels.leftRms = rms;
            state.levels.rightRms = rms;
            state.levels.leftPeak = peak;
            state.levels.rightPeak = peak;
        }
        
        // Indicators
        state.levels.clipping = doc["clipping"] | false;
        state.levels.limiting = doc["limiting"] | false;
    }
    
    void handleStatus(JsonDocument& doc, AppState& state) {
        bool wasStreaming = state.status.streaming;
        bool newStreaming = doc["streaming"] | false;
        
        // Handle duration from server
        unsigned long newDuration = state.status.duration;
        if (doc["duration"].is<unsigned long>()) {
            newDuration = doc["duration"] | 0;
        }
        
        // Error message
        String newError = "";
        if (doc["error"].is<const char*>()) {
            newError = doc["error"].as<String>();
        }
        
        // Ignore errors that were already dismissed (server keeps re-sending)
        if (!newError.isEmpty() && newError == state.status.dismissedError) {
            newError = "";
        }
        // A genuinely new error clears the dismissed memory
        if (!newError.isEmpty() && newError != state.status.dismissedError) {
            state.status.dismissedError = "";
        }
        
        // Only trigger full redraw if something visually changed
        bool changed = (newStreaming != wasStreaming);
        if (newError != state.status.error) changed = true;
        
        // Timestamp new errors for auto-clear (before overwriting state)
        if (!newError.isEmpty() && newError != state.status.error) {
            state.status.errorReceivedAt = millis();
        } else if (newError.isEmpty()) {
            state.status.errorReceivedAt = 0;
        }

        state.status.streaming = newStreaming;
        state.status.connected = true;
        state.status.duration = newDuration;
        state.status.error = newError;

        // Resolve pending command when status updates or error arrives
        if (state.pendingAction != PENDING_NONE) {
            bool resolved = (state.status.error.length() > 0);
            if (state.pendingAction == PENDING_START && newStreaming) resolved = true;
            if (state.pendingAction == PENDING_STOP && !newStreaming) resolved = true;
            if (resolved) {
                state.pendingAction = PENDING_NONE;
                state.needsFullRedraw = true;
            }
        }
        
        // Track streaming start locally as backup
        if (state.status.streaming && !wasStreaming) {
            state.status.startTime = millis();
        }
        
        if (changed) {
            state.needsFullRedraw = true;
        }
    }
    
    void handleGain(JsonDocument& doc, AppState& state) {
        state.gainDb = doc["value"] | state.gainDb;
    }
};

#endif // PROTOCOL_H
