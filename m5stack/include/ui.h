#ifndef UI_H
#define UI_H

#include <M5Unified.h>
#include "config.h"
#include "state.h"

// =============================================================================
// UI Drawing Functions
// =============================================================================

class UI {
public:
    UI() {}
    
    void begin() {
        M5.Display.fillScreen(COLOR_BG);
    }
    
    // -------------------------------------------------------------------------
    // Full Screen Redraw
    // -------------------------------------------------------------------------
    
    void drawFullScreen(AppState& state) {
        M5.Display.fillScreen(COLOR_BG);
        drawHeader(state);
        drawStatus(state);
        drawMeters(state);
        drawClipIndicator(state, true);
        drawLimiterIndicator(state, true);
        drawGain(state);
        drawFooter(state);
        drawHoldProgress(0.0f);
    }
    
    // -------------------------------------------------------------------------
    // Incremental Updates
    // -------------------------------------------------------------------------
    
    void updateMeters(AppState& state) {
        drawMeterBar(METER_Y, state.levels.leftRmsSmooth, state.levels.leftPeakHold, "L");
        drawMeterBar(METER_Y + METER_HEIGHT + METER_SPACING, state.levels.rightRmsSmooth, state.levels.rightPeakHold, "R");
        
        // Update dB readouts
        float leftDb = linearToDb(state.levels.leftRmsSmooth);
        float rightDb = linearToDb(state.levels.rightRmsSmooth);
        drawDbReadout(METER_Y, leftDb);
        drawDbReadout(METER_Y + METER_HEIGHT + METER_SPACING, rightDb);
    }
    
    void updateStatus(AppState& state) {
        // Only redraw if something changed
        bool streamingChanged = (state.status.streaming != _lastStreaming);
        bool durationChanged = (state.status.duration != _lastDuration);
        bool errorChanged = (state.status.error != _lastError);
        bool pendingChanged = (state.pendingAction != _lastPendingAction);
        
        if (!streamingChanged && !durationChanged && !errorChanged && !pendingChanged) {
            return;  // Nothing changed, skip redraw
        }
        
        _lastStreaming = state.status.streaming;
        _lastDuration = state.status.duration;
        _lastError = state.status.error;
        _lastPendingAction = state.pendingAction;
        
        drawStatus(state);
        drawHeader(state);
    }

    void updateHoldProgress(AppState& state) {
        float progress = 0.0f;
        if (state.pendingAction == PENDING_NONE && state.buttonAPressed && state.buttonAPressTime > 0) {
            unsigned long now = millis();
            unsigned long elapsed = now - state.buttonAPressTime;
            if (elapsed < LONG_PRESS_MS) {
                progress = (float)elapsed / (float)LONG_PRESS_MS;
            } else {
                progress = 1.0f;
            }
        }

        if (fabs(progress - _lastHoldProgress) < 0.02f) {
            return;
        }
        _lastHoldProgress = progress;
        drawHoldProgress(progress);
    }
    
    void updateGain(AppState& state) {
        // Only redraw if gain changed
        if (abs(state.gainDb - _lastGainDb) < 0.01f) {
            return;
        }
        _lastGainDb = state.gainDb;
        drawGain(state);
    }
    
    void updateClipIndicator(AppState& state) {
        drawClipIndicator(state, false);
    }
    
    void updateLimiterIndicator(AppState& state) {
        drawLimiterIndicator(state, false);
    }
    
    void showDisconnectOverlay(AppState& state) {
        if (state.overlayShown) return;
        state.overlayShown = true;
        drawDisconnectOverlay();
    }
    
    void hideDisconnectOverlay(AppState& state) {
        if (!state.overlayShown) return;
        state.overlayShown = false;
        state.needsFullRedraw = true;
    }
    
private:
    // Track previous states for partial updates
    bool _lastClipping = false;
    bool _lastLimiting = false;
    bool _lastStreaming = false;
    unsigned long _lastDuration = 0;
    String _lastError = "";
    float _lastGainDb = 0.0f;
    PendingAction _lastPendingAction = PENDING_NONE;
    float _lastHoldProgress = -1.0f;
    
    // -------------------------------------------------------------------------
    // Header
    // -------------------------------------------------------------------------
    
    void drawHeader(AppState& state) {
        M5.Display.fillRect(0, HEADER_Y, SCREEN_WIDTH, HEADER_HEIGHT, COLOR_HEADER_BG);
        M5.Display.setTextColor(COLOR_TEXT, COLOR_HEADER_BG);
        M5.Display.setTextSize(2);
        M5.Display.setTextDatum(ML_DATUM);  // Middle-Left
        M5.Display.drawString("OndePi", 10, HEADER_Y + HEADER_HEIGHT / 2);

        String statusText;
        uint16_t statusColor = COLOR_TEXT;
        if (state.pendingAction == PENDING_START) {
            statusText = "STARTING";
            statusColor = COLOR_METER_MID;
        } else if (state.pendingAction == PENDING_STOP) {
            statusText = "STOPPING";
            statusColor = COLOR_METER_MID;
        } else {
            statusText = state.status.streaming ? "STREAMING" : "STOPPED";
        }
        M5.Display.setTextDatum(MR_DATUM);  // Middle-Right
        M5.Display.setTextColor(statusColor, COLOR_HEADER_BG);
        M5.Display.drawString(statusText, SCREEN_WIDTH - 10, HEADER_Y + HEADER_HEIGHT / 2);
    }
    
    // -------------------------------------------------------------------------
    // Status Area
    // -------------------------------------------------------------------------
    
    void drawStatus(AppState& state) {
        // Clear status area
        M5.Display.fillRect(0, STATUS_Y, SCREEN_WIDTH, STATUS_HEIGHT, COLOR_BG);
        
        // Status dot
        uint16_t dotColor = COLOR_STOPPED;
        if (state.pendingAction != PENDING_NONE) {
            dotColor = COLOR_METER_MID;
        } else if (state.status.streaming) {
            dotColor = COLOR_STREAMING;
        }
        
        int dotX = 15;
        int dotY = STATUS_Y + STATUS_HEIGHT / 2;
        M5.Display.fillCircle(dotX, dotY, 6, dotColor);
        
        // Duration or error (right aligned)
        M5.Display.setTextDatum(MR_DATUM);
        if (!state.status.error.isEmpty()) {
            // Show error in red, truncated if needed
            M5.Display.setTextColor(COLOR_ERROR, COLOR_BG);
            String err = state.status.error;
            if (err.length() > 12) err = err.substring(0, 11) + "~";
            M5.Display.drawString(err, SCREEN_WIDTH - 10, dotY);
        } else if (state.status.streaming || state.status.duration > 0) {
            // Show duration
            M5.Display.setTextColor(COLOR_TEXT_DIM, COLOR_BG);
            String duration = formatDuration(state.status.duration);
            M5.Display.drawString(duration, SCREEN_WIDTH - 10, dotY);
        }
    }

    void drawHoldProgress(float progress) {
        const int barWidth = 80;
        const int barHeight = 4;
        const int barX = (SCREEN_WIDTH - barWidth) / 2;
        const int barY = HEADER_Y + HEADER_HEIGHT - barHeight - 2;

        // Background track
        M5.Display.fillRect(barX, barY, barWidth, barHeight, COLOR_TEXT_DIM);

        int filled = (int)(barWidth * min(max(progress, 0.0f), 1.0f));
        if (filled > 0) {
            M5.Display.fillRect(barX, barY, filled, barHeight, COLOR_ACCENT);
        }
    }
    
    // -------------------------------------------------------------------------
    // VU Meters
    // -------------------------------------------------------------------------
    
    void drawMeterBar(int y, float level, float peakHold, const char* label) {
        // Clear meter area
        M5.Display.fillRect(METER_X, y, METER_WIDTH, METER_HEIGHT, COLOR_METER_BG);
        
        // Draw label
        M5.Display.setTextSize(1);
        M5.Display.setTextDatum(ML_DATUM);
        M5.Display.setTextColor(COLOR_TEXT_DIM, COLOR_BG);
        M5.Display.drawString(label, METER_LABEL_X, y + METER_HEIGHT / 2);
        
        // Convert to dB and then to position
        float levelDb = linearToDb(level);
        float position = dbToMeterPosition(levelDb);
        int barWidth = (int)(position * METER_WIDTH);
        
        if (barWidth > 0) {
            // Draw gradient meter bar
            drawGradientBar(METER_X, y, barWidth, METER_HEIGHT);
        }
        
        // Draw peak hold marker
        float peakDb = linearToDb(peakHold);
        float peakPosition = dbToMeterPosition(peakDb);
        int peakX = METER_X + (int)(peakPosition * METER_WIDTH);
        if (peakX > METER_X && peakX < METER_X + METER_WIDTH) {
            M5.Display.drawFastVLine(peakX, y, METER_HEIGHT, COLOR_METER_PEAK);
            M5.Display.drawFastVLine(peakX + 1, y, METER_HEIGHT, COLOR_METER_PEAK);
        }
    }
    
    void drawGradientBar(int x, int y, int width, int height) {
        // Draw segmented color bar (green -> yellow -> orange -> red)
        // -60 to -12 dB: green
        // -12 to -6 dB: yellow  
        // -6 to -3 dB: orange
        // -3 to 0 dB: red
        
        int greenEnd = (int)(METER_WIDTH * 0.8f);    // -60 to -12 dB (80%)
        int yellowEnd = (int)(METER_WIDTH * 0.9f);   // -12 to -6 dB (10%)
        int orangeEnd = (int)(METER_WIDTH * 0.95f);  // -6 to -3 dB (5%)
        // Rest is red                                // -3 to 0 dB (5%)
        
        // Green section
        int greenWidth = min(width, greenEnd);
        if (greenWidth > 0) {
            M5.Display.fillRect(x, y, greenWidth, height, COLOR_METER_LOW);
        }
        
        // Yellow section
        if (width > greenEnd) {
            int yellowWidth = min(width - greenEnd, yellowEnd - greenEnd);
            if (yellowWidth > 0) {
                M5.Display.fillRect(x + greenEnd, y, yellowWidth, height, COLOR_METER_MID);
            }
        }
        
        // Orange section
        if (width > yellowEnd) {
            int orangeWidth = min(width - yellowEnd, orangeEnd - yellowEnd);
            if (orangeWidth > 0) {
                M5.Display.fillRect(x + yellowEnd, y, orangeWidth, height, COLOR_METER_HIGH);
            }
        }
        
        // Red section
        if (width > orangeEnd) {
            int redWidth = width - orangeEnd;
            M5.Display.fillRect(x + orangeEnd, y, redWidth, height, COLOR_METER_CLIP);
        }
    }
    
    void drawDbReadout(int y, float db) {
        M5.Display.fillRect(METER_DB_X, y, 40, METER_HEIGHT, COLOR_BG);
        M5.Display.setTextSize(1);
        M5.Display.setTextDatum(ML_DATUM);
        M5.Display.setTextColor(COLOR_TEXT_DIM, COLOR_BG);
        M5.Display.drawString(formatDb(db), METER_DB_X, y + METER_HEIGHT / 2);
    }
    
    void drawMeters(AppState& state) {
        drawMeterBar(METER_Y, state.levels.leftRmsSmooth, state.levels.leftPeakHold, "L");
        drawMeterBar(METER_Y + METER_HEIGHT + METER_SPACING, state.levels.rightRmsSmooth, state.levels.rightPeakHold, "R");
        
        float leftDb = linearToDb(state.levels.leftRmsSmooth);
        float rightDb = linearToDb(state.levels.rightRmsSmooth);
        drawDbReadout(METER_Y, leftDb);
        drawDbReadout(METER_Y + METER_HEIGHT + METER_SPACING, rightDb);
    }
    
    // -------------------------------------------------------------------------
    // Indicators
    // -------------------------------------------------------------------------
    
    void drawClipIndicator(AppState& state, bool force) {
        if (!force && state.levels.clipping == _lastClipping) return;
        _lastClipping = state.levels.clipping;
        
        int indWidth = 80;
        int indHeight = 16;
        int indX = METER_X + (METER_WIDTH - indWidth) / 2;
        
        if (state.levels.clipping) {
            M5.Display.fillRoundRect(indX, CLIP_IND_Y, indWidth, indHeight, 3, COLOR_CLIP_BG);
            M5.Display.setTextColor(COLOR_CLIP_TEXT);
            M5.Display.setTextSize(1);
            M5.Display.setTextDatum(MC_DATUM);
            M5.Display.drawString("INPUT CLIP", indX + indWidth / 2, CLIP_IND_Y + indHeight / 2);
        } else {
            M5.Display.fillRect(indX, CLIP_IND_Y, indWidth, indHeight, COLOR_BG);
        }
    }
    
    void drawLimiterIndicator(AppState& state, bool force) {
        if (!force && state.levels.limiting == _lastLimiting) return;
        _lastLimiting = state.levels.limiting;
        
        int indWidth = 70;
        int indHeight = 16;
        int indX = METER_X + (METER_WIDTH - indWidth) / 2;
        
        if (state.levels.limiting) {
            M5.Display.fillRoundRect(indX, LIMITER_IND_Y, indWidth, indHeight, 3, COLOR_LIMITER_BG);
            M5.Display.setTextColor(COLOR_LIMITER_TEXT);
            M5.Display.setTextSize(1);
            M5.Display.setTextDatum(MC_DATUM);
            M5.Display.drawString("LIMITING", indX + indWidth / 2, LIMITER_IND_Y + indHeight / 2);
        } else {
            M5.Display.fillRect(indX, LIMITER_IND_Y, indWidth, indHeight, COLOR_BG);
        }
    }
    
    // -------------------------------------------------------------------------
    // Gain Display
    // -------------------------------------------------------------------------
    
    void drawGain(AppState& state) {
        M5.Display.fillRect(0, GAIN_Y, SCREEN_WIDTH, GAIN_HEIGHT, COLOR_BG);
        
        M5.Display.setTextSize(2);
        M5.Display.setTextDatum(MC_DATUM);
        M5.Display.setTextColor(COLOR_ACCENT, COLOR_BG);
        
        String gainText = "Gain: " + formatGain(state.gainDb);
        M5.Display.drawString(gainText, SCREEN_WIDTH / 2, GAIN_Y + GAIN_HEIGHT / 2);
        
        // Draw +/- indicators
        M5.Display.setTextColor(COLOR_TEXT_DIM, COLOR_BG);
        M5.Display.setTextSize(2);
        M5.Display.setTextDatum(ML_DATUM);
        M5.Display.drawString("-", 40, GAIN_Y + GAIN_HEIGHT / 2);
        M5.Display.setTextDatum(MR_DATUM);
        M5.Display.drawString("+", SCREEN_WIDTH - 40, GAIN_Y + GAIN_HEIGHT / 2);
    }
    
    // -------------------------------------------------------------------------
    // Footer (Button Hints)
    // -------------------------------------------------------------------------
    
    void drawFooter(AppState& state) {
        M5.Display.fillRect(0, FOOTER_Y, SCREEN_WIDTH, FOOTER_HEIGHT, COLOR_HEADER_BG);
        
        M5.Display.setTextSize(1);
        M5.Display.setTextDatum(MC_DATUM);
        M5.Display.setTextColor(COLOR_BTN_HINT);
        
        // Button A (left) - Gain down
        M5.Display.drawString("GAIN -", 53, FOOTER_Y + FOOTER_HEIGHT / 2);
        
        // Button B (center) - Start/Stop toggle
        String btnBText;
        if (state.pendingAction != PENDING_NONE) {
            btnBText = "WAIT...";
        } else {
            btnBText = state.status.streaming ? "HOLD:STOP" : "HOLD:START";
        }
        M5.Display.drawString(btnBText, 160, FOOTER_Y + FOOTER_HEIGHT / 2);
        
        // Button C (right) - Gain up
        M5.Display.drawString("GAIN +", 266, FOOTER_Y + FOOTER_HEIGHT / 2);
    }
    
    // -------------------------------------------------------------------------
    // Disconnect Overlay
    // -------------------------------------------------------------------------
    
    void drawDisconnectOverlay() {
        // Darken the screen with a filled rectangle
        int boxW = 240;
        int boxH = 100;
        int boxX = (SCREEN_WIDTH - boxW) / 2;
        int boxY = (SCREEN_HEIGHT - boxH) / 2 - 10;
        
        // Draw shadow/border
        M5.Display.fillRoundRect(boxX - 2, boxY - 2, boxW + 4, boxH + 4, 8, COLOR_OVERLAY_BORDER);
        // Draw background
        M5.Display.fillRoundRect(boxX, boxY, boxW, boxH, 6, COLOR_OVERLAY_BG);
        
        // Title
        M5.Display.setTextSize(2);
        M5.Display.setTextDatum(MC_DATUM);
        M5.Display.setTextColor(COLOR_OVERLAY_TEXT, COLOR_OVERLAY_BG);
        M5.Display.drawString("Disconnected", boxX + boxW / 2, boxY + 30);
        
        // Subtitle
        M5.Display.setTextSize(1);
        M5.Display.setTextColor(COLOR_OVERLAY_SUB, COLOR_OVERLAY_BG);
        M5.Display.drawString("Waiting for OndePi server...", boxX + boxW / 2, boxY + 58);
        
        // Animated dots hint
        M5.Display.setTextColor(COLOR_ACCENT, COLOR_OVERLAY_BG);
        M5.Display.drawString("Check USB connection", boxX + boxW / 2, boxY + 78);
    }
};

#endif // UI_H
