#include <SoftwareSerial.h>

namespace {
constexpr int SCANNER_RX = 4;
constexpr int SCANNER_TX = 5;
constexpr long SERIAL_BAUD = 115200;
constexpr long SCANNER_BAUD_RATES[] = {9600, 19200, 38400, 57600, 115200, 4800};
constexpr size_t SCANNER_BAUD_COUNT = sizeof(SCANNER_BAUD_RATES) / sizeof(SCANNER_BAUD_RATES[0]);
constexpr unsigned long BAUD_SWITCH_INTERVAL_MS = 5000;
constexpr unsigned long QUIET_FLUSH_MS = 40;

SoftwareSerial g_scannerSerial(SCANNER_RX, SCANNER_TX);
String g_asciiBuffer;
String g_hexBuffer;
unsigned long g_lastByteAt = 0;
unsigned long g_lastSwitchAt = 0;
size_t g_baudIndex = 0;

void beginScannerAt(size_t index) {
  g_baudIndex = index % SCANNER_BAUD_COUNT;
  g_scannerSerial.begin(SCANNER_BAUD_RATES[g_baudIndex]);
  g_asciiBuffer = "";
  g_hexBuffer = "";
  Serial.println();
  Serial.print("=== SCANNER BAUD ");
  Serial.print(SCANNER_BAUD_RATES[g_baudIndex]);
  Serial.println(" ===");
}

String byteToHex(uint8_t value) {
  char buffer[4];
  snprintf(buffer, sizeof(buffer), "%02X", value);
  return String(buffer);
}

void flushBuffers(const char *reason) {
  if (g_asciiBuffer.length() == 0 && g_hexBuffer.length() == 0) {
    return;
  }

  Serial.print("[BAUD] ");
  Serial.println(SCANNER_BAUD_RATES[g_baudIndex]);
  Serial.print("[REASON] ");
  Serial.println(reason);
  if (g_asciiBuffer.length() > 0) {
    Serial.print("[ASCII] ");
    Serial.println(g_asciiBuffer);
  }
  if (g_hexBuffer.length() > 0) {
    Serial.print("[HEX] ");
    Serial.println(g_hexBuffer);
  }
  Serial.println("--------------------");
  g_asciiBuffer = "";
  g_hexBuffer = "";
}
}  // namespace

void setup() {
  Serial.begin(SERIAL_BAUD);
  while (!Serial) {
  }

  Serial.println("Maikrt scanner diagnostic ready");
  Serial.println("Connect scanner TX -> D4 (Arduino RX), scanner RX -> D5, common GND");
  Serial.println("The sketch rotates baud rates and prints ASCII + HEX payloads.");
  beginScannerAt(0);
  g_lastSwitchAt = millis();
}

void loop() {
  while (g_scannerSerial.available()) {
    uint8_t value = static_cast<uint8_t>(g_scannerSerial.read());
    g_lastByteAt = millis();

    if (g_hexBuffer.length() > 0) {
      g_hexBuffer += ' ';
    }
    g_hexBuffer += byteToHex(value);

    if (value >= 32 && value <= 126) {
      g_asciiBuffer += static_cast<char>(value);
    } else if (value == '\r') {
      g_asciiBuffer += "\\r";
    } else if (value == '\n') {
      g_asciiBuffer += "\\n";
      flushBuffers("newline");
    } else {
      g_asciiBuffer += '.';
    }
  }

  if ((g_asciiBuffer.length() > 0 || g_hexBuffer.length() > 0) && millis() - g_lastByteAt >= QUIET_FLUSH_MS) {
    flushBuffers("idle");
  }

  if (millis() - g_lastSwitchAt >= BAUD_SWITCH_INTERVAL_MS) {
    flushBuffers("baud switch");
    beginScannerAt((g_baudIndex + 1) % SCANNER_BAUD_COUNT);
    g_lastSwitchAt = millis();
  }
}
