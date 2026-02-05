#ifndef STATE_H
#define STATE_H

#include <Arduino.h>
#include "config.h"

// =============================================================================
// Application State
// =============================================================================

struct AudioLevels {
    float leftRms = 0.0f;
    float rightRms = 0.0f;
    float leftPeak = 0.0f;
    float rightPeak = 0.0f;
    
    // Smoothed values for display
    float leftRmsSmooth = 0.0f;
    float rightRmsSmooth = 0.0f;
    float leftPeakSmooth = 0.0f;
    float rightPeakSmooth = 0.0f;
    
    // Peak hold
    float leftPeakHold = 0.0f;
    float rightPeakHold = 0.0f;
    unsigned long leftPeakHoldTime = 0;
    unsigned long rightPeakHoldTime = 0;
    
    // Indicators
    bool clipping = false;
    bool limiting = false;
};

struct StreamStatus {
    bool streaming = false;
    bool connected = false;
    String error = "";
    unsigned long startTime = 0;  // millis() when streaming started
    unsigned long duration = 0;   // Duration in seconds from server
};

enum PendingAction : uint8_t {
    PENDING_NONE = 0,
    PENDING_START = 1,
    PENDING_STOP = 2,
};

struct AppState {
    AudioLevels levels;
    StreamStatus status;
    float gainDb = GAIN_DEFAULT_DB;
    
    // UI state
    bool needsFullRedraw = true;
    bool overlayShown = false;
    bool buttonAPressed = false;
    unsigned long buttonAPressTime = 0;
    unsigned long lastGainRepeatB = 0;
    unsigned long lastGainRepeatC = 0;
    PendingAction pendingAction = PENDING_NONE;
    unsigned long pendingSince = 0;
    unsigned long lastCommandAt = 0;
    
    // Communication
    unsigned long lastHeartbeat = 0;
    unsigned long lastLevelsReceived = 0;
};

// =============================================================================
// State Update Functions
// =============================================================================

inline float linearToDb(float linear) {
    if (linear <= 0.0001f) return METER_DB_MIN;
    float db = 20.0f * log10f(linear);
    return max(METER_DB_MIN, min(METER_DB_MAX, db));
}

inline float dbToLinear(float db) {
    return powf(10.0f, db / 20.0f);
}

inline float dbToMeterPosition(float db) {
    // Map dB to 0.0-1.0 range
    return (db - METER_DB_MIN) / (METER_DB_MAX - METER_DB_MIN);
}

inline void updateSmoothedLevels(AudioLevels& levels, float dt) {
    unsigned long now = millis();
    
    // Smooth RMS with different attack/release
    auto smooth = [](float current, float target, float attack, float release) {
        float factor = (target > current) ? attack : release;
        return current + (target - current) * (1.0f - factor);
    };
    
    levels.leftRmsSmooth = smooth(levels.leftRmsSmooth, levels.leftRms, METER_ATTACK, METER_RELEASE);
    levels.rightRmsSmooth = smooth(levels.rightRmsSmooth, levels.rightRms, METER_ATTACK, METER_RELEASE);
    levels.leftPeakSmooth = smooth(levels.leftPeakSmooth, levels.leftPeak, METER_ATTACK, METER_RELEASE);
    levels.rightPeakSmooth = smooth(levels.rightPeakSmooth, levels.rightPeak, METER_ATTACK, METER_RELEASE);
    
    // Peak hold logic for left channel
    if (levels.leftPeak > levels.leftPeakHold) {
        levels.leftPeakHold = levels.leftPeak;
        levels.leftPeakHoldTime = now;
    } else if (now - levels.leftPeakHoldTime > PEAK_HOLD_MS) {
        levels.leftPeakHold -= PEAK_DECAY_RATE;
        if (levels.leftPeakHold < 0) levels.leftPeakHold = 0;
    }
    
    // Peak hold logic for right channel
    if (levels.rightPeak > levels.rightPeakHold) {
        levels.rightPeakHold = levels.rightPeak;
        levels.rightPeakHoldTime = now;
    } else if (now - levels.rightPeakHoldTime > PEAK_HOLD_MS) {
        levels.rightPeakHold -= PEAK_DECAY_RATE;
        if (levels.rightPeakHold < 0) levels.rightPeakHold = 0;
    }
}

inline String formatDuration(unsigned long seconds) {
    unsigned long h = seconds / 3600;
    unsigned long m = (seconds % 3600) / 60;
    unsigned long s = seconds % 60;
    
    char buf[16];
    snprintf(buf, sizeof(buf), "%02lu:%02lu:%02lu", h, m, s);
    return String(buf);
}

inline String formatGain(float db) {
    char buf[16];
    if (db >= 0) {
        snprintf(buf, sizeof(buf), "+%.1f dB", db);
    } else {
        snprintf(buf, sizeof(buf), "%.1f dB", db);
    }
    return String(buf);
}

inline String formatDb(float db) {
    if (db <= METER_DB_MIN + 1) {
        return "-inf";
    }
    char buf[8];
    snprintf(buf, sizeof(buf), "%.0f", db);
    return String(buf);
}

#endif // STATE_H
