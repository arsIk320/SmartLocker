#include <ArduinoJson.h>
#include <EEPROM.h>
#include <ESP8266WebServer.h>
#include <ESP8266WiFi.h>
#include <time.h>

namespace {
constexpr uint32_t EEPROM_MAGIC = 0x534C4B31;  // SLK1
constexpr size_t EEPROM_SIZE = 1024;
constexpr unsigned long WIFI_CONNECT_TIMEOUT_MS = 15000;
constexpr size_t LOG_CAPACITY = 20;
constexpr char PROTOCOL_NAME[] = "smartlocker-provisioning-v1";
constexpr char FIRMWARE_VERSION[] = "0.1.0-test";
constexpr char DEFAULT_BOARD_UID[] = "TEMP-BOOT";

struct DeviceConfig {
  uint32_t magic;
  char chip[16];
  char lockId[32];
  char boardUid[32];
  char deviceName[64];
  char wifiSsid[64];
  char wifiPassword[64];
  char ownerEmail[96];
  char doorUid[32];
};

DeviceConfig g_config{};
String g_serialBuffer;
String g_logs[LOG_CAPACITY];
size_t g_logCount = 0;
size_t g_logCursor = 0;
bool g_wifiConnected = false;
bool g_httpServerStarted = false;
unsigned long g_bootMillis = 0;
ESP8266WebServer g_server(80);

const char *currentBoardUid();
String currentIpAddress();
String formatTimestamp();
String htmlEscape(const String &value);
String renderLogsHtml();
void appendLog(const String &message);
void handleRootPage();
void handleStatusJson();
void ensureWebServerStarted();

String htmlEscape(const String &value) {
  String escaped = value;
  escaped.replace("&", "&amp;");
  escaped.replace("<", "&lt;");
  escaped.replace(">", "&gt;");
  escaped.replace("\"", "&quot;");
  return escaped;
}

String formatTimestamp() {
  time_t now = time(nullptr);
  if (now < 100000) {
    unsigned long uptimeSeconds = (millis() - g_bootMillis) / 1000;
    unsigned long hours = uptimeSeconds / 3600;
    unsigned long minutes = (uptimeSeconds % 3600) / 60;
    unsigned long seconds = uptimeSeconds % 60;
    return "uptime " + String(hours) + "h " + String(minutes) + "m " + String(seconds) + "s";
  }

  struct tm *info = localtime(&now);
  if (info == nullptr) {
    return "time unavailable";
  }

  char buffer[32];
  strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", info);
  return String(buffer);
}

void appendLog(const String &message) {
  String entry = formatTimestamp() + " | " + message;
  g_logs[g_logCursor] = entry;
  g_logCursor = (g_logCursor + 1) % LOG_CAPACITY;
  if (g_logCount < LOG_CAPACITY) {
    ++g_logCount;
  }
  Serial.println(entry);
}

String renderLogsHtml() {
  String html;
  html.reserve(2048);
  html += "<ul>";
  for (size_t index = 0; index < g_logCount; ++index) {
    size_t actualIndex = (g_logCursor + LOG_CAPACITY - g_logCount + index) % LOG_CAPACITY;
    html += "<li>";
    html += htmlEscape(g_logs[actualIndex]);
    html += "</li>";
  }
  html += "</ul>";
  return html;
}

String currentIpAddress() {
  if (!g_wifiConnected) {
    return "not connected";
  }
  return WiFi.localIP().toString();
}

void handleRootPage() {
  String html;
  html.reserve(4096);
  html += "<!DOCTYPE html><html><head><meta charset='utf-8'>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1'>";
  html += "<title>SmartLocker ESP8266 Test</title>";
  html += "<style>";
  html += "body{font-family:Segoe UI,Arial,sans-serif;background:#eef3f7;color:#17324a;margin:0;padding:24px;}";
  html += ".card{background:#fff;border:1px solid #d8e3eb;border-radius:18px;padding:20px;margin-bottom:18px;}";
  html += "h1,h2{margin-top:0;} .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;}";
  html += "ul{padding-left:20px;} .muted{color:#5d7285;}";
  html += "</style></head><body>";
  html += "<div class='card'><h1>SmartLocker ESP8266 Test Node</h1>";
  html += "<p class='muted'>Basic Wi-Fi test page for provisioning and diagnostics.</p></div>";
  html += "<div class='card'><h2>Status</h2><div class='grid'>";
  html += "<div><strong>Firmware</strong><br>" + htmlEscape(FIRMWARE_VERSION) + "</div>";
  html += "<div><strong>Protocol</strong><br>" + htmlEscape(PROTOCOL_NAME) + "</div>";
  html += "<div><strong>Board UID</strong><br>" + htmlEscape(currentBoardUid()) + "</div>";
  html += "<div><strong>Lock ID</strong><br>" + htmlEscape(String(g_config.lockId)) + "</div>";
  html += "<div><strong>Device name</strong><br>" + htmlEscape(String(g_config.deviceName)) + "</div>";
  html += "<div><strong>Wi-Fi</strong><br>" + htmlEscape(String(g_config.wifiSsid)) + "</div>";
  html += "<div><strong>IP address</strong><br>" + htmlEscape(currentIpAddress()) + "</div>";
  html += "<div><strong>Date / time</strong><br>" + htmlEscape(formatTimestamp()) + "</div>";
  html += "</div></div>";
  html += "<div class='card'><h2>Logs</h2>";
  html += renderLogsHtml();
  html += "</div></body></html>";
  g_server.send(200, "text/html; charset=utf-8", html);
}

void handleStatusJson() {
  StaticJsonDocument<512> doc;
  doc["ok"] = true;
  doc["chip"] = "ESP8266";
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["protocol"] = PROTOCOL_NAME;
  doc["board_uid"] = currentBoardUid();
  doc["lock_id"] = g_config.lockId;
  doc["device_name"] = g_config.deviceName;
  doc["wifi_ssid"] = g_config.wifiSsid;
  doc["wifi_connected"] = g_wifiConnected;
  doc["ip_address"] = currentIpAddress();
  doc["timestamp"] = formatTimestamp();
  String response;
  serializeJson(doc, response);
  g_server.send(200, "application/json; charset=utf-8", response);
}

void ensureWebServerStarted() {
  if (g_httpServerStarted || !g_wifiConnected) {
    return;
  }
  g_server.on("/", handleRootPage);
  g_server.on("/status", handleStatusJson);
  g_server.begin();
  g_httpServerStarted = true;
  appendLog("HTTP server started on http://" + currentIpAddress() + "/");
}

void clearConfig(DeviceConfig &config) {
  memset(&config, 0, sizeof(config));
  config.magic = EEPROM_MAGIC;
  strlcpy(config.chip, "ESP8266", sizeof(config.chip));
  strlcpy(config.boardUid, DEFAULT_BOARD_UID, sizeof(config.boardUid));
}

void saveConfig(const DeviceConfig &config) {
  EEPROM.put(0, config);
  EEPROM.commit();
}

void loadConfig() {
  EEPROM.get(0, g_config);
  if (g_config.magic != EEPROM_MAGIC) {
    clearConfig(g_config);
    saveConfig(g_config);
  }
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

bool connectToWifi() {
  if (g_config.wifiSsid[0] == '\0') {
    g_wifiConnected = false;
    appendLog("Wi-Fi connect skipped: SSID is empty");
    return false;
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(g_config.wifiSsid, g_config.wifiPassword);
  appendLog("Connecting to Wi-Fi SSID: " + String(g_config.wifiSsid));

  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < WIFI_CONNECT_TIMEOUT_MS) {
    delay(250);
  }

  g_wifiConnected = WiFi.status() == WL_CONNECTED;
  if (g_wifiConnected) {
    configTime(0, 0, "pool.ntp.org", "time.nist.gov");
    appendLog("Wi-Fi connected, IP: " + WiFi.localIP().toString());
    ensureWebServerStarted();
  } else {
    appendLog("Wi-Fi connection failed");
  }

  return g_wifiConnected;
}

bool copyRequiredString(JsonVariantConst source, char *target, size_t targetSize, const char *fieldName) {
  const char *value = source[fieldName];
  if (value == nullptr || value[0] == '\0') {
    return false;
  }
  strlcpy(target, value, targetSize);
  return true;
}

void handleIdentify() {
  appendLog("Received identify request over serial");
  StaticJsonDocument<256> doc;
  doc["ok"] = true;
  doc["protocol"] = PROTOCOL_NAME;
  doc["chip"] = "ESP8266";
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["board_uid"] = currentBoardUid();
  sendJson(doc);
}

void handleProvision(JsonVariantConst payload) {
  appendLog("Received provision request over serial");
  DeviceConfig updated = g_config;
  updated.magic = EEPROM_MAGIC;

  if (!copyRequiredString(payload, updated.chip, sizeof(updated.chip), "chip")) {
    sendError("chip is required");
    return;
  }
  if (strcmp(updated.chip, "ESP8266") != 0) {
    sendError("chip must be ESP8266 for this firmware");
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
  if (!copyRequiredString(payload, updated.wifiSsid, sizeof(updated.wifiSsid), "wifi_ssid")) {
    sendError("wifi_ssid is required");
    return;
  }
  if (!copyRequiredString(payload, updated.wifiPassword, sizeof(updated.wifiPassword), "wifi_password")) {
    sendError("wifi_password is required");
    return;
  }

  const char *ownerEmail = payload["owner_email"] | "";
  const char *doorUid = payload["door_uid"] | "";
  strlcpy(updated.ownerEmail, ownerEmail, sizeof(updated.ownerEmail));
  strlcpy(updated.doorUid, doorUid, sizeof(updated.doorUid));

  g_config = updated;
  saveConfig(g_config);
  appendLog("Configuration saved to EEPROM for Lock ID " + String(g_config.lockId));
  bool wifiOk = connectToWifi();

  StaticJsonDocument<256> doc;
  doc["ok"] = true;
  doc["status"] = "provisioned";
  doc["restart_required"] = true;
  doc["wifi_connected"] = wifiOk;
  doc["board_uid"] = g_config.boardUid;
  doc["ip_address"] = currentIpAddress();
  sendJson(doc);

  appendLog("Provisioning completed, reboot scheduled");
  delay(500);
  ESP.restart();
}

void handleIncomingMessage(const String &line) {
  StaticJsonDocument<768> doc;
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

  sendError("unsupported action");
}
}  // namespace

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(50);
  g_bootMillis = millis();
  EEPROM.begin(EEPROM_SIZE);
  loadConfig();
  appendLog("Boot completed");
  WiFi.persistent(false);
  WiFi.mode(WIFI_OFF);
  if (g_config.wifiSsid[0] != '\0') {
    connectToWifi();
  }
}

void loop() {
  if (g_httpServerStarted) {
    g_server.handleClient();
  }
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
