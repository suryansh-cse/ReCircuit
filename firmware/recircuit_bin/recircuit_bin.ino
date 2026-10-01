/* ============================================================================
 * RE-CIRCUIT Smart Bin Firmware (ESP32) — Day 4
 * Sends fill level + weight + temperature to:  POST /api/telemetry/
 * Payload: {"device_id":"ECO-BIN-001","fill_level":82,"weight":18.4,"temperature":29.5}
 *
 * BOARD: ESP32 DevKit (Arduino-ESP32 core). Open this file in Arduino IDE.
 *
 * LIBRARIES (Arduino IDE → Sketch → Include Library → Manage Libraries):
 *   1. "HX711 Arduino Library" by bogde        (load cell + HX711 amplifier)
 *   2. "DallasTemperature" by Miles Burton     (DS18B20 temperature sensor)
 *   3. "OneWire" by Jim Studt                 (required by DallasTemperature)
 * WiFi + HTTPClient are built into the ESP32 core — nothing to install.
 *
 * WIRING:
 *   HC-SR04 ultrasonic (fill level, mounted on bin lid facing down):
 *     VCC → VIN(5V), GND → GND, TRIG → GPIO 5, ECHO → GPIO 18 (via 1k/2k divider!)
 *   HX711 load cell amplifier (weight, under bin platform):
 *     VCC → 3V3(!), GND → GND, DT → GPIO 16, SCK → GPIO 4
 *   DS18B20 temperature (waterproof probe inside bin, 4.7k pull-up DQ→3V3):
 *     VDD → 3V3, GND → GND, DQ → GPIO 15
 *   Onboard LED (GPIO 2) blinks on every successful POST.
 *
 * CALIBRATION (do once, then hard-code below):
 *   HX711_CALIBRATION: put a known weight on the platform, read the raw value
 *     from Serial Monitor, set factor = raw / known_kg.
 *   BIN_EMPTY_CM: distance (cm) from sensor to empty bin floor.
 *   BIN_FULL_CM:  distance (cm) from sensor to full level (~5 cm below lid).
 *
 * BACKEND SETUP:
 *   1. Register this DEVICE_ID in Django admin → SmartBins (else API returns 404).
 *   2. SERVER_URL must be reachable from the ESP32 (your PC's LAN IP, NOT localhost):
 *      e.g. "http://192.168.1.50:8000/api/telemetry/"
 *   3. Run Django with:  python manage.py runserver 0.0.0.0:8000
 * ========================================================================== */

#include <WiFi.h>
#include <HTTPClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include "HX711.h"

// ---------------- CONFIG — EDIT THESE ----------------
const char* WIFI_SSID     = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL    = "http://192.168.1.50:8000/api/telemetry/";  // Django, LAN IP!
const char* DEVICE_ID     = "ECO-BIN-001";   // must match SmartBin.bin_id in admin

const int   TRIG_PIN = 5;    // HC-SR04 TRIG
const int   ECHO_PIN = 18;   // HC-SR04 ECHO (use voltage divider, ESP32 is 3.3V!)
const int   HX_DT    = 16;   // HX711 DT
const int   HX_SCK   = 4;    // HX711 SCK
const int   TEMP_PIN = 15;   // DS18B20 data
const int   LED_PIN  = 2;    // onboard LED

const float BIN_EMPTY_CM = 60.0;  // sensor→floor when bin is empty
const float BIN_FULL_CM  = 8.0;   // sensor→waste when bin is full
const float HX711_CALIBRATION = 2280.0;  // raw units per kg — calibrate!

const unsigned long POST_INTERVAL_MS = 60000;  // send every 60 s
// ------------------------------------------------------

OneWire oneWire(TEMP_PIN);
DallasTemperature tempSensor(&oneWire);
HX711 scale;
unsigned long lastPost = 0;

float readFillPercent() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  long micros = pulseIn(ECHO_PIN, HIGH, 30000);  // 30 ms timeout
  if (micros == 0) return -1;                    // no echo → sensor fault
  float distCm = micros * 0.0343 / 2.0;
  float fill = (BIN_EMPTY_CM - distCm) / (BIN_EMPTY_CM - BIN_FULL_CM) * 100.0;
  if (fill < 0) fill = 0;
  if (fill > 100) fill = 100;
  return fill;
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.print("WiFi connecting to ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 40) {
    delay(500);
    Serial.print(".");
    tries++;
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? "\nWiFi connected." : "\nWiFi FAILED.");
}

void postTelemetry(float fill, float weight, float tempC) {
  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");

  // Manual JSON (no extra library needed). temperature may be omitted if sensor fails.
  String body = String("{\"device_id\":\"") + DEVICE_ID + "\""
              + ",\"fill_level\":" + String(fill, 1)
              + ",\"weight\":" + String(weight, 1);
  if (tempC > -100) body += ",\"temperature\":" + String(tempC, 1);
  body += "}";

  Serial.print("POST ");
  Serial.println(body);
  int code = http.POST(body);
  Serial.print("HTTP ");
  Serial.println(code);
  if (code > 0) Serial.println(http.getString());  // backend echo / error details
  http.end();

  if (code == 201) {
    digitalWrite(LED_PIN, HIGH);
    delay(200);
    digitalWrite(LED_PIN, LOW);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);
  tempSensor.begin();
  scale.begin(HX_DT, HX_SCK);
  scale.set_scale(HX711_CALIBRATION);
  scale.tare();  // zero with empty platform
  connectWiFi();
  Serial.println("ReCircuit bin ready.");
}

void loop() {
  connectWiFi();
  if (millis() - lastPost >= POST_INTERVAL_MS) {
    lastPost = millis();

    float fill = readFillPercent();
    float weight = scale.get_units(5);   // average of 5 readings
    if (weight < 0) weight = 0;
    tempSensor.requestTemperatures();
    float tempC = tempSensor.getTempCByIndex(0);
    if (tempC == DEVICE_DISCONNECTED_C) tempC = -999;  // omitted from JSON

    Serial.printf("fill=%.1f%% weight=%.1fkg temp=%.1fC\n", fill, weight, tempC);
    if (fill < 0) {
      Serial.println("Ultrasonic fault — skipping POST.");
      return;
    }
    if (WiFi.status() == WL_CONNECTED) {
      postTelemetry(fill, weight, tempC);
    } else {
      Serial.println("Offline — reading dropped (no local queue in Day 4 build).");
    }
  }
}
