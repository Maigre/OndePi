// OndePi M5Stack stub (draft)
// This is a placeholder sketch illustrating the serial protocol.

#include <M5Stack.h>

void setup() {
  M5.begin();
  Serial.begin(115200);
  M5.Lcd.println("OndePi stub");
}

void loop() {
  if (M5.BtnA.wasPressed()) {
    Serial.println("{\"action\":\"start\"}");
  }
  if (M5.BtnB.wasPressed()) {
    Serial.println("{\"action\":\"stop\"}");
  }
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    M5.Lcd.println(line);
  }
  M5.update();
  delay(50);
}
