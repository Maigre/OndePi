#ifndef CONFIG_H
#define CONFIG_H

// =============================================================================
// OndePi M5Stack Configuration
// =============================================================================

// -- Serial Protocol ----------------------------------------------------------
#define SERIAL_BAUD         115200
#define SERIAL_TIMEOUT_MS   100

// -- Display Layout (320x240) -------------------------------------------------
#define SCREEN_WIDTH        320
#define SCREEN_HEIGHT       240

// Header
#define HEADER_HEIGHT       30
#define HEADER_Y            0

// Status area
#define STATUS_Y            35
#define STATUS_HEIGHT       25

// VU Meter area
#define METER_Y             70
#define METER_HEIGHT        20
#define METER_SPACING       8
#define METER_X             30
#define METER_WIDTH         240
#define METER_LABEL_X       10
#define METER_DB_X          280

// Indicators
#define CLIP_IND_Y          (METER_Y - 18)
#define LIMITER_IND_Y       (METER_Y + METER_HEIGHT * 2 + METER_SPACING + 5)

// Error message (centered between limiter indicator and gain)
#define ERROR_MSG_Y         140
#define ERROR_MSG_HEIGHT    16
#define ERROR_TIMEOUT_MS    5000    // Auto-clear error after 5 seconds

// Gain display
#define GAIN_Y              160
#define GAIN_HEIGHT         30

// Footer / button hints
#define FOOTER_Y            210
#define FOOTER_HEIGHT       30

// -- VU Meter Settings --------------------------------------------------------
// Smoothing factor (0.0 = no smoothing, 1.0 = frozen)
// Lower = faster response, higher = smoother
#define METER_ATTACK        0.3f    // Fast attack for transients
#define METER_RELEASE       0.85f   // Slower release for readability

// Peak hold time in milliseconds
#define PEAK_HOLD_MS        1500
#define PEAK_DECAY_RATE     0.02f   // Per frame decay after hold

// dB range for meter display
#define METER_DB_MIN        -60.0f
#define METER_DB_MAX        0.0f

// Clip threshold (linear, where 1.0 = 0dB)
#define CLIP_THRESHOLD      0.99f

// -- Gain Settings ------------------------------------------------------------
#define GAIN_MIN_DB         -12.0f
#define GAIN_MAX_DB         24.0f
#define GAIN_STEP_DB        0.5f
#define GAIN_DEFAULT_DB     0.0f

// -- Button Timing ------------------------------------------------------------
#define LONG_PRESS_MS       800     // Hold time for long press
#define BUTTON_DEBOUNCE_MS  50
#define GAIN_REPEAT_MS      150     // Auto-repeat for gain buttons
// Start/Stop UX
#define COMMAND_COOLDOWN_MS 1200    // Minimum time between start/stop commands
#define PENDING_TIMEOUT_MS  5000    // Clear pending status if no update (ms)

// -- Update Rates -------------------------------------------------------------
#define UI_UPDATE_MS        33      // ~30 FPS for smooth meters
#define SERIAL_POLL_MS      10      // Check serial frequently
#define HEARTBEAT_MS        5000    // Send ping every 5s
#define DISCONNECT_TIMEOUT_MS 3000  // Show overlay after 3s without data

// -- Colors (RGB565) ----------------------------------------------------------
#define COLOR_BG            TFT_BLACK
#define COLOR_HEADER_BG     0x1082  // Dark blue-gray
#define COLOR_TEXT          TFT_WHITE
#define COLOR_TEXT_DIM      TFT_DARKGREY
#define COLOR_ACCENT        0x07FF  // Cyan

// Status colors
#define COLOR_STOPPED       TFT_DARKGREY
#define COLOR_STREAMING     0x07E0  // Green
#define COLOR_ERROR         TFT_RED

// Meter colors (gradient from green to red)
#define COLOR_METER_LOW     0x07E0  // Green
#define COLOR_METER_MID     0xFFE0  // Yellow
#define COLOR_METER_HIGH    0xFD20  // Orange
#define COLOR_METER_CLIP    0xF800  // Red
#define COLOR_METER_BG      0x2104  // Dark gray
#define COLOR_METER_PEAK    TFT_WHITE

// Indicator colors
#define COLOR_CLIP_BG       TFT_RED
#define COLOR_CLIP_TEXT     TFT_WHITE
#define COLOR_LIMITER_BG    0xFD20  // Orange
#define COLOR_LIMITER_TEXT  TFT_BLACK

// Button hint colors
#define COLOR_BTN_HINT      TFT_DARKGREY

// Overlay colors
#define COLOR_OVERLAY_BG    0x2104  // Dark gray, semi-opaque effect
#define COLOR_OVERLAY_TEXT  TFT_WHITE
#define COLOR_OVERLAY_SUB   TFT_DARKGREY
#define COLOR_OVERLAY_BORDER 0x4A49 // Medium gray

#endif // CONFIG_H
