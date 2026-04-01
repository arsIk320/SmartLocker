#include <SoftwareSerial.h>

namespace {
constexpr int SCANNER_RX = 4;
constexpr int SCANNER_TX = 5;
constexpr long SERIAL_BAUD = 115200;
constexpr long SCANNER_BAUD = 9600;
constexpr unsigned long PACKET_IDLE_MS = 250;
constexpr unsigned long DUPLICATE_SUPPRESS_MS = 1500;

SoftwareSerial g_scannerSerial(SCANNER_RX, SCANNER_TX);

String g_asciiBuffer;
String g_digitsBuffer;
String g_hexBuffer;
String g_lastPacket;
unsigned long g_lastByteAt = 0;
unsigned long g_lastPacketAt = 0;

String byteToHex(uint8_t value) {
  char buffer[4];
  snprintf(buffer, sizeof(buffer), "%02X", value);
  return String(buffer);
}

void resetBuffers() {
  g_asciiBuffer = "";
  g_digitsBuffer = "";
  g_hexBuffer = "";
}

void flushPacket(const char *reason) {
  if (g_asciiBuffer.length() == 0 && g_hexBuffer.length() == 0) {
    return;
  }

  if (g_asciiBuffer == g_lastPacket && millis() - g_lastPacketAt < DUPLICATE_SUPPRESS_MS) {
    resetBuffers();
    return;
  }

  Serial.println();
  Serial.println("=== SCAN PACKET ===");
  Serial.print("[REASON] ");
  Serial.println(reason);
  Serial.print("[ASCII] ");
  Serial.println(g_asciiBuffer);
  Serial.print("[DIGITS] ");
  Serial.println(g_digitsBuffer.length() > 0 ? g_digitsBuffer : "<none>");
  Serial.print("[LEN] ");
  Serial.println(g_asciiBuffer.length());
  Serial.print("[HEX] ");
  Serial.println(g_hexBuffer);
  Serial.println("--------------------");

  g_lastPacket = g_asciiBuffer;
  g_lastPacketAt = millis();
  resetBuffers();
}
}  // namespace

void setup() {
  Serial.begin(SERIAL_BAUD);
  while (!Serial) {
  }

  g_scannerSerial.begin(SCANNER_BAUD);

  Serial.println("Maikrt scanner packet test ready");
  Serial.println("Scanner fixed at 9600 baud");
  Serial.println("Connect scanner TX -> D4, scanner RX -> D5, common GND");
  Serial.println("The sketch prints one assembled packet per scan after a quiet pause.");
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
      char ch = static_cast<char>(value);
      g_asciiBuffer += ch;
      if (ch >= '0' && ch <= '9') {
        g_digitsBuffer += ch;
      }
    } else if (value == '\r') {
      g_asciiBuffer += "\\r";
    } else if (value == '\n') {
      g_asciiBuffer += "\\n";
    } else {
      g_asciiBuffer += '.';
    }
  }

  if ((g_asciiBuffer.length() > 0 || g_hexBuffer.length() > 0) &&
      millis() - g_lastByteAt >= PACKET_IDLE_MS) {
    flushPacket("idle");
  }
}
