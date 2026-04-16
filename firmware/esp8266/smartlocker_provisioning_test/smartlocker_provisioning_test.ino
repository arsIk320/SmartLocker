#include <ArduinoJson.h>
#include <EEPROM.h>
#include <ESP8266HTTPClient.h>
#include <ESP8266WebServer.h>
#include <ESP8266WiFi.h>
#include <WiFiClientSecureBearSSL.h>
#include <time.h>

namespace {
constexpr uint32_t EEPROM_MAGIC = 0x534C4B32;  // SLK2
constexpr size_t EEPROM_SIZE = 1536;
constexpr unsigned long WIFI_CONNECT_TIMEOUT_MS = 15000;
constexpr unsigned long WIFI_RETRY_DELAY_MS = 250;
constexpr unsigned long HTTP_TIMEOUT_MS = 10000;
constexpr unsigned long QR_REFRESH_INTERVAL_MS = 30000;
constexpr unsigned long WIFI_RECONNECT_INTERVAL_MS = 5000;
constexpr unsigned long SERIAL_BAUD = 9600;
constexpr size_t LOG_CAPACITY = 24;
constexpr char PROTOCOL_NAME[] = "smartlocker-provisioning-v1";
constexpr char FIRMWARE_VERSION[] = "0.2.0-unified";
constexpr char DEFAULT_BOARD_UID[] = "TEMP-BOOT";
constexpr char DEFAULT_API_BASE_URL[] = "http://188.130.251.23";

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
  char apiKey[96];
  char apiBaseUrl[160];
};

DeviceConfig g_config{};
String g_serialBuffer;
String g_logs[LOG_CAPACITY];
size_t g_logCount = 0;
size_t g_logCursor = 0;
bool g_wifiConnected = false;
bool g_httpServerStarted = false;
bool g_wifiConnectInProgress = false;
unsigned long g_bootMillis = 0;
unsigned long g_lastQrRefreshAt = 0;
unsigned long g_wifiConnectStartedAt = 0;
unsigned long g_lastWifiAttemptAt = 0;
String g_cachedCode;
String g_cachedDoorUid;
String g_cachedExpiresAt;
ESP8266WebServer g_server(80);

String formatTimestamp();
void appendLog(const String &message);
bool connectToWifi();
void beginWifiConnect();
void serviceWifiConnection();
void serviceBackgroundTasks();
bool fetchQrCodeFromServer();
void ensureWebServerStarted();
void handleIncomingLine(const String &line);
void handlePlainCommand(const String &command);

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

void clearConfig(DeviceConfig &config) {
  memset(&config, 0, sizeof(config));
  config.magic = EEPROM_MAGIC;
  strlcpy(config.chip, "ESP8266", sizeof(config.chip));
  strlcpy(config.boardUid, DEFAULT_BOARD_UID, sizeof(config.boardUid));
  strlcpy(config.apiBaseUrl, DEFAULT_API_BASE_URL, sizeof(config.apiBaseUrl));
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

String currentIpAddress() {
  if (!g_wifiConnected) {
    return "not connected";
  }
  return WiFi.localIP().toString();
}

String buildQrUrl() {
  String baseUrl = String(g_config.apiBaseUrl);
  baseUrl.trim();
  if (baseUrl.length() == 0) {
    return "";
  }
  if (baseUrl.endsWith("/")) {
    baseUrl.remove(baseUrl.length() - 1);
  }
  return baseUrl + "/api/v1/locks/qr/current";
}

template <typename TDocument>
void sendJson(const TDocument &doc) {
  serializeJson(doc, Serial);
  Serial.println();
}

void sendError(const char *message) {
  StaticJsonDocument<192> doc;
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

bool connectToWifi() {
  if (g_config.wifiSsid[0] == '\0') {
    g_wifiConnected = false;
    appendLog("Wi-Fi skipped: SSID is empty");
    return false;
  }

  if (WiFi.status() == WL_CONNECTED) {
    g_wifiConnected = true;
    return true;
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(g_config.wifiSsid, g_config.wifiPassword);
  appendLog("Connecting to Wi-Fi SSID: " + String(g_config.wifiSsid));

  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < WIFI_CONNECT_TIMEOUT_MS) {
    delay(WIFI_RETRY_DELAY_MS);
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

void beginWifiConnect() {
  if (g_config.wifiSsid[0] == '\0') {
    g_wifiConnected = false;
    g_wifiConnectInProgress = false;
    return;
  }
  if (WiFi.status() == WL_CONNECTED) {
    g_wifiConnected = true;
    g_wifiConnectInProgress = false;
    ensureWebServerStarted();
    return;
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(g_config.wifiSsid, g_config.wifiPassword);
  g_wifiConnectStartedAt = millis();
  g_lastWifiAttemptAt = millis();
  g_wifiConnectInProgress = true;
  g_wifiConnected = false;
  appendLog("Connecting to Wi-Fi SSID: " + String(g_config.wifiSsid));
}

void serviceWifiConnection() {
  if (g_config.wifiSsid[0] == '\0') {
    g_wifiConnected = false;
    g_wifiConnectInProgress = false;
    return;
  }

  if (WiFi.status() == WL_CONNECTED) {
    if (!g_wifiConnected) {
      g_wifiConnected = true;
      g_wifiConnectInProgress = false;
      configTime(0, 0, "pool.ntp.org", "time.nist.gov");
      appendLog("Wi-Fi connected, IP: " + WiFi.localIP().toString());
      ensureWebServerStarted();
    }
    return;
  }

  g_wifiConnected = false;
  if (g_wifiConnectInProgress) {
    if (millis() - g_wifiConnectStartedAt >= WIFI_CONNECT_TIMEOUT_MS) {
      g_wifiConnectInProgress = false;
      appendLog("Wi-Fi connection timeout");
    }
    return;
  }

  if (millis() - g_lastWifiAttemptAt >= WIFI_RECONNECT_INTERVAL_MS) {
    beginWifiConnect();
  }
}

void serviceBackgroundTasks() {
  serviceWifiConnection();
  if (g_httpServerStarted) {
    g_server.handleClient();
  }

  if (!g_wifiConnected) {
    return;
  }

  if (g_cachedCode.isEmpty()) {
    fetchQrCodeFromServer();
    return;
  }

  if (millis() - g_lastQrRefreshAt >= QR_REFRESH_INTERVAL_MS) {
    fetchQrCodeFromServer();
  }
}

void handleRootPage() {
  String html;
  html.reserve(4096);
  html += "<!DOCTYPE html><html><head><meta charset='utf-8'>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1'>";
  html += "<title>SmartLocker ESP8266 Unified</title>";
  html += "<style>";
  html += "body{font-family:Segoe UI,Arial,sans-serif;background:#eef3f7;color:#17324a;margin:0;padding:24px;}";
  html += ".card{background:#fff;border:1px solid #d8e3eb;border-radius:18px;padding:20px;margin-bottom:18px;}";
  html += "h1,h2{margin-top:0;} .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;}";
  html += "ul{padding-left:20px;} .muted{color:#5d7285;} code{word-break:break-all;}";
  html += "</style></head><body>";
  html += "<div class='card'><h1>SmartLocker ESP8266 Unified Firmware</h1>";
  html += "<p class='muted'>Provisioning + QR polling in one firmware.</p></div>";
  html += "<div class='card'><h2>Status</h2><div class='grid'>";
  html += "<div><strong>Firmware</strong><br>" + htmlEscape(FIRMWARE_VERSION) + "</div>";
  html += "<div><strong>Protocol</strong><br>" + htmlEscape(PROTOCOL_NAME) + "</div>";
  html += "<div><strong>Board UID</strong><br>" + htmlEscape(currentBoardUid()) + "</div>";
  html += "<div><strong>Lock ID</strong><br>" + htmlEscape(String(g_config.lockId)) + "</div>";
  html += "<div><strong>Device name</strong><br>" + htmlEscape(String(g_config.deviceName)) + "</div>";
  html += "<div><strong>Door UID</strong><br>" + htmlEscape(String(g_config.doorUid)) + "</div>";
  html += "<div><strong>Wi-Fi</strong><br>" + htmlEscape(String(g_config.wifiSsid)) + "</div>";
  html += "<div><strong>API base URL</strong><br><code>" + htmlEscape(String(g_config.apiBaseUrl)) + "</code></div>";
  html += "<div><strong>IP address</strong><br>" + htmlEscape(currentIpAddress()) + "</div>";
  html += "<div><strong>Cached QR</strong><br>" + htmlEscape(g_cachedCode) + "</div>";
  html += "<div><strong>QR expires</strong><br>" + htmlEscape(g_cachedExpiresAt) + "</div>";
  html += "<div><strong>Date / time</strong><br>" + htmlEscape(formatTimestamp()) + "</div>";
  html += "</div></div>";
  html += "<div class='card'><h2>Logs</h2>";
  html += renderLogsHtml();
  html += "</div></body></html>";
  g_server.send(200, "text/html; charset=utf-8", html);
}

void handleStatusJson() {
  StaticJsonDocument<768> doc;
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
  doc["door_uid"] = g_config.doorUid;
  doc["api_base_url"] = g_config.apiBaseUrl;
  doc["cached_code"] = g_cachedCode;
  doc["cached_expires_at"] = g_cachedExpiresAt;
  doc["timestamp"] = formatTimestamp();
  String response;
  serializeJson(doc, response);
  g_server.send(200, "application/json; charset=utf-8", response);
}

void handleRefreshQr() {
  bool ok = fetchQrCodeFromServer();
  StaticJsonDocument<256> doc;
  doc["ok"] = ok;
  doc["cached_code"] = g_cachedCode;
  doc["expires_at"] = g_cachedExpiresAt;
  String response;
  serializeJson(doc, response);
  g_server.send(ok ? 200 : 502, "application/json; charset=utf-8", response);
}

void ensureWebServerStarted() {
  if (g_httpServerStarted || !g_wifiConnected) {
    return;
  }
  g_server.on("/", handleRootPage);
  g_server.on("/status", handleStatusJson);
  g_server.on("/refresh-qr", handleRefreshQr);
  g_server.begin();
  g_httpServerStarted = true;
  appendLog("HTTP server started on http://" + currentIpAddress() + "/");
}

bool fetchQrCodeFromServer() {
  if (g_config.lockId[0] == '\0' || g_config.apiKey[0] == '\0' || g_config.apiBaseUrl[0] == '\0') {
    appendLog("QR refresh skipped: provisioning is incomplete");
    return false;
  }
  if (!connectToWifi()) {
    return false;
  }

  String url = buildQrUrl();
  if (url.length() == 0) {
    appendLog("QR refresh skipped: QR URL is empty");
    return false;
  }

  appendLog("Requesting current QR from " + url);
  HTTPClient http;
  int statusCode = -1;
  String payload;

  if (url.startsWith("https://")) {
    BearSSL::WiFiClientSecure client;
    client.setInsecure();
    if (!http.begin(client, url)) {
      appendLog("HTTP begin failed (TLS)");
      return false;
    }
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.addHeader("X-Lock-Id", g_config.lockId);
    http.addHeader("X-Lock-Api-Key", g_config.apiKey);
    statusCode = http.GET();
    if (statusCode > 0) {
      payload = http.getString();
    }
    http.end();
  } else {
    WiFiClient client;
    if (!http.begin(client, url)) {
      appendLog("HTTP begin failed");
      return false;
    }
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.addHeader("X-Lock-Id", g_config.lockId);
    http.addHeader("X-Lock-Api-Key", g_config.apiKey);
    statusCode = http.GET();
    if (statusCode > 0) {
      payload = http.getString();
    }
    http.end();
  }

  if (statusCode <= 0) {
    appendLog("QR request failed with status " + String(statusCode));
    return false;
  }

  StaticJsonDocument<768> doc;
  DeserializationError error = deserializeJson(doc, payload);
  if (error) {
    appendLog("Failed to parse QR JSON");
    return false;
  }

  const char *code = doc["code"] | "";
  const char *doorUid = doc["door_uid"] | "";
  const char *expiresAt = doc["expires_at"] | "";
  if (code[0] == '\0') {
    appendLog("QR code not found in response");
    return false;
  }

  g_cachedCode = String(code);
  g_cachedDoorUid = String(doorUid);
  g_cachedExpiresAt = String(expiresAt);
  g_lastQrRefreshAt = millis();

  Serial.print("CODE:");
  Serial.println(g_cachedCode);
  Serial.print("DOOR_UID:");
  Serial.println(g_cachedDoorUid);
  Serial.print("EXPIRES_AT:");
  Serial.println(g_cachedExpiresAt);
  appendLog("QR cache updated");
  return true;
}

void sendCachedCode() {
  if (g_cachedCode.isEmpty()) {
    if (!fetchQrCodeFromServer()) {
      Serial.println("ERROR:NO_CODE");
      return;
    }
  }

  Serial.print("CODE:");
  Serial.println(g_cachedCode);
  Serial.print("DOOR_UID:");
  Serial.println(g_cachedDoorUid);
  Serial.print("EXPIRES_AT:");
  Serial.println(g_cachedExpiresAt);
}

void handleIdentify() {
  appendLog("Received identify request over serial");
  StaticJsonDocument<320> doc;
  doc["ok"] = true;
  doc["protocol"] = PROTOCOL_NAME;
  doc["chip"] = "ESP8266";
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["board_uid"] = currentBoardUid();
  doc["lock_id"] = g_config.lockId;
  doc["wifi_connected"] = g_wifiConnected;
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
  if (!copyRequiredString(payload, updated.apiKey, sizeof(updated.apiKey), "api_key")) {
    sendError("api_key is required");
    return;
  }
  if (!copyRequiredString(payload, updated.apiBaseUrl, sizeof(updated.apiBaseUrl), "api_base_url")) {
    sendError("api_base_url is required");
    return;
  }

  const char *ownerEmail = payload["owner_email"] | "";
  const char *doorUid = payload["door_uid"] | "";
  strlcpy(updated.ownerEmail, ownerEmail, sizeof(updated.ownerEmail));
  strlcpy(updated.doorUid, doorUid, sizeof(updated.doorUid));

  g_config = updated;
  saveConfig(g_config);
  g_cachedCode = "";
  g_cachedDoorUid = "";
  g_cachedExpiresAt = "";
  appendLog("Configuration saved for Lock ID " + String(g_config.lockId));
  beginWifiConnect();

  StaticJsonDocument<384> doc;
  doc["ok"] = true;
  doc["status"] = "provisioned";
  doc["restart_required"] = false;
  doc["wifi_connected"] = false;
  doc["qr_ready"] = false;
  doc["board_uid"] = g_config.boardUid;
  doc["ip_address"] = currentIpAddress();
  doc["api_base_url"] = g_config.apiBaseUrl;
  sendJson(doc);

  appendLog("Provisioning saved, Wi-Fi/QR will continue in background");
}

void handlePlainCommand(const String &rawCommand) {
  String cmd = rawCommand;
  cmd.trim();
  if (cmd.isEmpty()) {
    return;
  }

  Serial.print("[ESP8266] CMD: ");
  Serial.println(cmd);

  if (cmd == "ping") {
    Serial.println("PONG");
    return;
  }
  if (cmd == "get-code") {
    sendCachedCode();
    return;
  }
  if (cmd == "refresh-code") {
    if (!fetchQrCodeFromServer()) {
      Serial.println("ERROR:REFRESH_FAILED");
    }
    return;
  }
  if (cmd == "status-json") {
    StaticJsonDocument<320> doc;
    doc["ok"] = true;
    doc["lock_id"] = g_config.lockId;
    doc["door_uid"] = g_config.doorUid;
    doc["wifi_connected"] = g_wifiConnected;
    doc["cached_code"] = g_cachedCode;
    sendJson(doc);
    return;
  }

  Serial.println("ERROR:UNKNOWN_COMMAND");
}

void handleIncomingLine(const String &line) {
  if (!line.startsWith("{")) {
    handlePlainCommand(line);
    return;
  }

  StaticJsonDocument<1024> doc;
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
  Serial.begin(SERIAL_BAUD);
  Serial.setTimeout(50);
  g_bootMillis = millis();
  EEPROM.begin(EEPROM_SIZE);
  loadConfig();
  appendLog("Boot completed");
  WiFi.persistent(false);
  WiFi.mode(WIFI_OFF);
  if (g_config.wifiSsid[0] != '\0') {
    beginWifiConnect();
  }
  appendLog("Ready. Serial supports provisioning JSON plus: ping, get-code, refresh-code, status-json");
}

void loop() {
  serviceBackgroundTasks();

  while (Serial.available() > 0) {
    char ch = static_cast<char>(Serial.read());
    if (ch == '\n') {
      String line = g_serialBuffer;
      g_serialBuffer = "";
      line.trim();
      if (!line.isEmpty()) {
        handleIncomingLine(line);
      }
      continue;
    }
    if (ch != '\r') {
      g_serialBuffer += ch;
    }
  }
}
