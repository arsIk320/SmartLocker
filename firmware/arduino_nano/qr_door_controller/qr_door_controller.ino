#include <SoftwareSerial.h>

namespace {
constexpr int SCANNER_RX = 4;
constexpr int SCANNER_TX = 5;
constexpr int ESP_RX = 12;
constexpr int ESP_TX = 11;
constexpr int FIRST_RX = 8;
constexpr int FIRST_TX = 7;
constexpr int LOCK_PIN = 3;

constexpr int CODE_LEN = 11;
constexpr unsigned long ESP_INTERVAL_MS = 15000;
constexpr unsigned long ESP_LISTEN_TIME_MS = 5000;
constexpr unsigned long LOCK_OPEN_TIME_MS = 2500;
constexpr unsigned long SCANNER_ACCUMULATION_MS = 250;
constexpr unsigned long SCAN_COOLDOWN_MS = 1500;
constexpr unsigned long FIRST_POLL_INTERVAL_MS = 25;
constexpr long SCANNER_BAUD = 9600;

SoftwareSerial g_scannerSerial(SCANNER_RX, SCANNER_TX);
SoftwareSerial g_espSerial(ESP_RX, ESP_TX);
SoftwareSerial g_firstSerial(FIRST_RX, FIRST_TX);

String g_serverCode;
String g_scannerCode;
String g_scannerRawBuffer;
String g_firstBuffer;
String g_lastHandledCode;
String g_lastHandledPacket;
unsigned long g_lastEspCheck = 0;
unsigned long g_lockStart = 0;
unsigned long g_lastScannerByteAt = 0;
unsigned long g_lastHandledAt = 0;
unsigned long g_lastFirstPollAt = 0;
bool g_lockActive = false;
bool g_scannerPacketReady = false;

void resetScannerBuffers() {
  g_scannerCode = "";
  g_scannerRawBuffer = "";
  g_scannerPacketReady = false;
}

void openLock() {
  Serial.println("[LOCK] Opening relay");
  digitalWrite(LOCK_PIN, HIGH);
  g_lockStart = millis();
  g_lockActive = true;
}

void closeLockIfNeeded() {
  if (g_lockActive && millis() - g_lockStart >= LOCK_OPEN_TIME_MS) {
    digitalWrite(LOCK_PIN, LOW);
    g_lockActive = false;
    Serial.println("[LOCK] Relay closed");
  }
}

void requestCodeFromEsp(bool forceRefresh) {
  g_espSerial.listen();
  delay(3);
  g_espSerial.println(forceRefresh ? "refresh-code" : "get-code");

  unsigned long started = millis();
  while (millis() - started < ESP_LISTEN_TIME_MS) {
    if (!g_espSerial.available()) {
      continue;
    }

    String line = g_espSerial.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) {
      continue;
    }

    Serial.print("[ESP8266 RAW] ");
    Serial.println(line);

    if (line.startsWith("CODE:")) {
      g_serverCode = line.substring(5);
      g_serverCode.trim();
      Serial.print("[ESP8266] Stored code: ");
      Serial.println(g_serverCode);
      return;
    }

    if (line.startsWith("ERROR:")) {
      Serial.print("[ESP8266] ");
      Serial.println(line);
      return;
    }
  }

  Serial.println("[ESP8266] No code received");
}

void handleFirstCommand(const String &cmd) {
  Serial.print("[FIRST] Received: ");
  Serial.println(cmd);

  if (cmd == "D" || cmd == "5" || cmd == "OPEN") {
    openLock();
  }
}

void readFromFirstArduino() {
  g_firstSerial.listen();
  delay(2);

  while (g_firstSerial.available()) {
    char ch = static_cast<char>(g_firstSerial.read());
    if (ch == '\n' || ch == '\r') {
      if (g_firstBuffer.length() > 0) {
        g_firstBuffer.trim();
        handleFirstCommand(g_firstBuffer);
        g_firstBuffer = "";
      }
    } else if (ch >= 32 && ch <= 126) {
      g_firstBuffer += ch;
    }
  }
}

void readFromScanner() {
  g_scannerSerial.listen();

  while (g_scannerSerial.available()) {
    char ch = static_cast<char>(g_scannerSerial.read());
    g_lastScannerByteAt = millis();
    if (ch != '\r' && ch != '\n') {
      g_scannerRawBuffer += ch;
    }
    if (ch >= '0' && ch <= '9') {
      g_scannerCode += ch;
      if (g_scannerCode.length() > CODE_LEN) {
        g_scannerCode.remove(0, g_scannerCode.length() - CODE_LEN);
      }
    } else if (ch == '\n' || ch == '\r') {
      break;
    }
  }

  if (!g_scannerPacketReady && g_scannerRawBuffer.length() > 0 &&
      millis() - g_lastScannerByteAt >= SCANNER_ACCUMULATION_MS) {
    g_scannerPacketReady = true;
    Serial.print("[SCANNER RAW] ");
    Serial.println(g_scannerRawBuffer);

    if (g_scannerCode.length() == CODE_LEN) {
      Serial.print("[QR] Read: ");
      Serial.println(g_scannerCode);
      Serial.print("[QR] Forward code: ");
      Serial.println(g_scannerCode);
    }
  }
}

bool scannerIsBusy() {
  if (g_scannerPacketReady) {
    return true;
  }

  if (g_scannerRawBuffer.length() == 0) {
    return false;
  }

  return millis() - g_lastScannerByteAt < SCANNER_ACCUMULATION_MS;
}

void compareQrAndOpenIfValid() {
  if (!g_scannerPacketReady) {
    return;
  }

  if (g_scannerCode.length() != CODE_LEN || g_serverCode.length() != CODE_LEN) {
    resetScannerBuffers();
    return;
  }

  if ((g_scannerCode == g_lastHandledCode || g_scannerRawBuffer == g_lastHandledPacket) &&
      millis() - g_lastHandledAt < SCAN_COOLDOWN_MS) {
    resetScannerBuffers();
    return;
  }

  Serial.print("[CHECK] QR:  ");
  Serial.println(g_scannerCode);
  Serial.print("[CHECK] API: ");
  Serial.println(g_serverCode);

  if (g_scannerCode == g_serverCode) {
    Serial.println("[RESULT] ACCESS GRANTED");
    openLock();
  } else {
    Serial.println("[RESULT] ACCESS DENIED");
  }

  Serial.println("--------------------");
  g_lastHandledCode = g_scannerCode;
  g_lastHandledPacket = g_scannerRawBuffer;
  g_lastHandledAt = millis();
  resetScannerBuffers();
}
}  // namespace

void setup() {
  Serial.begin(9600);
  g_scannerSerial.begin(SCANNER_BAUD);
  g_espSerial.begin(9600);
  g_firstSerial.begin(9600);

  pinMode(LOCK_PIN, OUTPUT);
  digitalWrite(LOCK_PIN, LOW);

  Serial.println("QR door controller ready");
  Serial.println("Scanner fixed at 9600 baud");
  requestCodeFromEsp(true);
  g_lastEspCheck = millis();
}

void loop() {
  readFromScanner();
  compareQrAndOpenIfValid();

  if (!scannerIsBusy() && millis() - g_lastEspCheck >= ESP_INTERVAL_MS) {
    requestCodeFromEsp(true);
    g_lastEspCheck = millis();
  }

  if (!scannerIsBusy() && millis() - g_lastFirstPollAt >= FIRST_POLL_INTERVAL_MS) {
    readFromFirstArduino();
    g_lastFirstPollAt = millis();
  }

  closeLockIfNeeded();
}
