#include <ArduinoJson.h>
#include <EEPROM.h>

namespace {
constexpr uint16_t EEPROM_MAGIC = 0x534C;
constexpr int RELAY_PIN = 7;
constexpr int STATUS_LED_PIN = LED_BUILTIN;
constexpr unsigned long RELAY_PULSE_MS = 1200;
constexpr char PROTOCOL_NAME[] = "smartlocker-provisioning-v1";
constexpr char FIRMWARE_VERSION[] = "0.1.0-relay-a";
constexpr char DEFAULT_BOARD_UID[] = "TEMP-BOOT";
constexpr char DEFAULT_ROLE[] = "relay_a";

struct DeviceConfig {
  uint16_t magic;
  char chip[16];
  char lockId[32];
  char boardUid[32];
  char deviceName[48];
  char relayRole[16];
};

DeviceConfig g_config{};
String g_serialBuffer;
bool g_isProvisioned = false;
unsigned long g_bootMillis = 0;

void clearConfig(DeviceConfig &config) {
  memset(&config, 0, sizeof(config));
  config.magic = EEPROM_MAGIC;
  strlcpy(config.chip, "ARDUINO_NANO", sizeof(config.chip));
  strlcpy(config.boardUid, DEFAULT_BOARD_UID, sizeof(config.boardUid));
  strlcpy(config.relayRole, DEFAULT_ROLE, sizeof(config.relayRole));
}

void saveConfig(const DeviceConfig &config) {
  EEPROM.put(0, config);
}

void loadConfig() {
  EEPROM.get(0, g_config);
  if (g_config.magic != EEPROM_MAGIC) {
    clearConfig(g_config);
    saveConfig(g_config);
  }
  g_isProvisioned = g_config.lockId[0] != '\0';
}

const char *currentBoardUid() {
  if (g_config.boardUid[0] == '\0') {
    return DEFAULT_BOARD_UID;
  }
  return g_config.boardUid;
}

void sendJson(const JsonDocument &doc) {
  serializeJson(doc, Serial);
  Serial.println();
}

void sendError(const char *message) {
  StaticJsonDocument<160> doc;
  doc["ok"] = false;
  doc["error"] = message;
  sendJson(doc);
}

bool copyRequiredString(JsonVariantConst source, char *target, size_t targetSize, const char *fieldName) {
  const char *value = source[fieldName];
  if (value == nullptr || value[0] == '\0') {
    return false;
  }
  strlcpy(target, value, targetSize);
  return true;
}

void pulseRelay(unsigned long pulseMs) {
  digitalWrite(RELAY_PIN, HIGH);
  digitalWrite(STATUS_LED_PIN, LOW);
  delay(pulseMs);
  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(STATUS_LED_PIN, HIGH);
}

void handleIdentify() {
  StaticJsonDocument<256> doc;
  doc["ok"] = true;
  doc["protocol"] = PROTOCOL_NAME;
  doc["chip"] = "ARDUINO_NANO";
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["board_uid"] = currentBoardUid();
  doc["relay_role"] = g_config.relayRole;
  doc["provisioned"] = g_isProvisioned;
  sendJson(doc);
}

void handleProvision(JsonVariantConst payload) {
  DeviceConfig updated = g_config;
  updated.magic = EEPROM_MAGIC;

  if (!copyRequiredString(payload, updated.chip, sizeof(updated.chip), "chip")) {
    sendError("chip is required");
    return;
  }
  if (strcmp(updated.chip, "ARDUINO_NANO") != 0) {
    sendError("chip must be ARDUINO_NANO for this firmware");
    return;
  }
  if (!copyRequiredString(payload, updated.lockId, sizeof(updated.lockId), "lock_id")) {
    sendError("lock_id is required");
    return;
  }
  if (!copyRequiredString(payload, updated.boardUid, sizeof(updated.boardUid), "board_uid")) {
    sendError("board_uid is required");
    return;
  }
  if (!copyRequiredString(payload, updated.deviceName, sizeof(updated.deviceName), "device_name")) {
    sendError("device_name is required");
    return;
  }

  const char *relayRole = payload["relay_role"] | DEFAULT_ROLE;
  strlcpy(updated.relayRole, relayRole, sizeof(updated.relayRole));
  g_config = updated;
  saveConfig(g_config);
  g_isProvisioned = true;

  StaticJsonDocument<224> doc;
  doc["ok"] = true;
  doc["status"] = "provisioned";
  doc["board_uid"] = g_config.boardUid;
  doc["relay_role"] = g_config.relayRole;
  sendJson(doc);
}

void handleStatus() {
  StaticJsonDocument<256> doc;
  doc["ok"] = true;
  doc["chip"] = "ARDUINO_NANO";
  doc["board_uid"] = currentBoardUid();
  doc["lock_id"] = g_config.lockId;
  doc["device_name"] = g_config.deviceName;
  doc["relay_role"] = g_config.relayRole;
  doc["provisioned"] = g_isProvisioned;
  doc["uptime_ms"] = millis() - g_bootMillis;
  sendJson(doc);
}

void handlePulse(JsonVariantConst payload) {
  if (!g_isProvisioned) {
    sendError("device is not provisioned");
    return;
  }

  unsigned long pulseMs = payload["pulse_ms"] | RELAY_PULSE_MS;
  pulseRelay(pulseMs);

  StaticJsonDocument<224> doc;
  doc["ok"] = true;
  doc["status"] = "relay_pulsed";
  doc["board_uid"] = g_config.boardUid;
  doc["relay_role"] = g_config.relayRole;
  doc["pulse_ms"] = pulseMs;
  sendJson(doc);
}

void handleIncomingMessage(const String &line) {
  StaticJsonDocument<512> doc;
  DeserializationError error = deserializeJson(doc, line);
  if (error) {
    sendError("invalid json");
    return;
  }

  const char *protocol = doc["protocol"] | "";
  if (strcmp(protocol, PROTOCOL_NAME) != 0) {
    sendError("unsupported protocol");
    return;
  }

  const char *action = doc["action"] | "";
  if (strcmp(action, "identify") == 0) {
    handleIdentify();
    return;
  }
  if (strcmp(action, "provision") == 0) {
    JsonVariantConst payload = doc["payload"];
    if (payload.isNull()) {
      sendError("payload is required");
      return;
    }
    handleProvision(payload);
    return;
  }
  if (strcmp(action, "status") == 0) {
    handleStatus();
    return;
  }
  if (strcmp(action, "relay_pulse") == 0) {
    JsonVariantConst payload = doc["payload"];
    handlePulse(payload);
    return;
  }

  sendError("unsupported action");
}
}  // namespace

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(50);
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(STATUS_LED_PIN, HIGH);
  g_bootMillis = millis();
  loadConfig();
}

void loop() {
  while (Serial.available() > 0) {
    char ch = static_cast<char>(Serial.read());
    if (ch == '\n') {
      String line = g_serialBuffer;
      g_serialBuffer = "";
      line.trim();
      if (!line.isEmpty()) {
        handleIncomingMessage(line);
      }
      continue;
    }
    if (ch != '\r') {
      g_serialBuffer += ch;
    }
  }
}
