#include <ArduinoJson.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>
#include <esp_camera.h>
#include <time.h>

namespace {
constexpr unsigned long WIFI_CONNECT_TIMEOUT_MS = 15000;
constexpr size_t LOG_CAPACITY = 20;
constexpr char PROTOCOL_NAME[] = "smartlocker-provisioning-v1";
constexpr char FIRMWARE_VERSION[] = "0.1.0-cam-test";
constexpr char DEFAULT_BOARD_UID[] = "TEMP-BOOT";
constexpr char PREFERENCES_NS[] = "smartlocker";

struct DeviceConfig {
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
Preferences g_preferences;
WebServer g_server(80);
String g_serialBuffer;
String g_logs[LOG_CAPACITY];
size_t g_logCount = 0;
size_t g_logCursor = 0;
bool g_wifiConnected = false;
bool g_httpServerStarted = false;
bool g_cameraReady = false;
unsigned long g_bootMillis = 0;

const char *currentBoardUid();
String currentIpAddress();
String formatTimestamp();
String htmlEscape(const String &value);
String renderLogsHtml();
void appendLog(const String &message);
void handleRootPage();
void handleStatusJson();
void handleCapture();
void ensureWebServerStarted();

void clearConfig(DeviceConfig &config) {
  memset(&config, 0, sizeof(config));
  strlcpy(config.chip, "ESP32-CAM", sizeof(config.chip));
  strlcpy(config.boardUid, DEFAULT_BOARD_UID, sizeof(config.boardUid));
}

void saveConfig() {
  g_preferences.begin(PREFERENCES_NS, false);
  g_preferences.putBytes("config", &g_config, sizeof(g_config));
  g_preferences.end();
}

void loadConfig() {
  clearConfig(g_config);
  g_preferences.begin(PREFERENCES_NS, true);
  size_t read = g_preferences.getBytes("config", &g_config, sizeof(g_config));
  g_preferences.end();
  if (read != sizeof(g_config) || g_config.chip[0] == '\0') {
    clearConfig(g_config);
    saveConfig();
  }
}

bool initCamera() {
  camera_config_t config{};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = 5;
  config.pin_d1 = 18;
  config.pin_d2 = 19;
  config.pin_d3 = 21;
  config.pin_d4 = 36;
  config.pin_d5 = 39;
  config.pin_d6 = 34;
  config.pin_d7 = 35;
  config.pin_xclk = 0;
  config.pin_pclk = 22;
  config.pin_vsync = 25;
  config.pin_href = 23;
  config.pin_sccb_sda = 26;
  config.pin_sccb_scl = 27;
  config.pin_pwdn = 32;
  config.pin_reset = -1;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_QVGA;
  config.jpeg_quality = 12;
  config.fb_count = 1;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    appendLog("Camera init failed, err=" + String(static_cast<int>(err)));
    return false;
  }

  appendLog("Camera initialized");
  return true;
}

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
    return "uptime " + String(uptimeSeconds) + "s";
  }

  struct tm timeInfo{};
  if (!localtime_r(&now, &timeInfo)) {
    return "time unavailable";
  }

  char buffer[32];
  strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", &timeInfo);
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
  String html = "<ul>";
  for (size_t index = 0; index < g_logCount; ++index) {
    size_t actualIndex = (g_logCursor + LOG_CAPACITY - g_logCount + index) % LOG_CAPACITY;
    html += "<li>" + htmlEscape(g_logs[actualIndex]) + "</li>";
  }
  html += "</ul>";
  return html;
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

void handleRootPage() {
  String html;
  html.reserve(4096);
  html += "<!DOCTYPE html><html><head><meta charset='utf-8'>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1'>";
  html += "<title>SmartLocker ESP32-CAM Test</title>";
  html += "<style>body{font-family:Segoe UI,Arial,sans-serif;background:#0e1820;color:#e8f1f8;margin:0;padding:24px;}";
  html += ".card{background:#172734;border:1px solid #29465a;border-radius:18px;padding:20px;margin-bottom:18px;}";
  html += "h1,h2{margin-top:0;} .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;}";
  html += "img{max-width:100%;border-radius:12px;border:1px solid #29465a;} a{color:#7fd4ff;}</style></head><body>";
  html += "<div class='card'><h1>SmartLocker ESP32-CAM Test Node</h1><p>Provisioning, camera preview and Wi-Fi diagnostics.</p></div>";
  html += "<div class='card'><h2>Status</h2><div class='grid'>";
  html += "<div><strong>Firmware</strong><br>" + htmlEscape(FIRMWARE_VERSION) + "</div>";
  html += "<div><strong>Protocol</strong><br>" + htmlEscape(PROTOCOL_NAME) + "</div>";
  html += "<div><strong>Board UID</strong><br>" + htmlEscape(currentBoardUid()) + "</div>";
  html += "<div><strong>Lock ID</strong><br>" + htmlEscape(String(g_config.lockId)) + "</div>";
  html += "<div><strong>Camera</strong><br>" + String(g_cameraReady ? "ready" : "not ready") + "</div>";
  html += "<div><strong>Wi-Fi</strong><br>" + htmlEscape(String(g_config.wifiSsid)) + "</div>";
  html += "<div><strong>IP address</strong><br>" + htmlEscape(currentIpAddress()) + "</div>";
  html += "<div><strong>Date / time</strong><br>" + htmlEscape(formatTimestamp()) + "</div>";
  html += "</div></div>";
  html += "<div class='card'><h2>Preview</h2>";
  if (g_cameraReady) {
    html += "<p><a href='/capture.jpg' target='_blank'>Open latest JPEG frame</a></p>";
    html += "<img src='/capture.jpg' alt='camera preview'>";
  } else {
    html += "<p>Camera is not initialized yet.</p>";
  }
  html += "</div><div class='card'><h2>Logs</h2>" + renderLogsHtml() + "</div></body></html>";
  g_server.send(200, "text/html; charset=utf-8", html);
}

void handleStatusJson() {
  StaticJsonDocument<512> doc;
  doc["ok"] = true;
  doc["chip"] = "ESP32-CAM";
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["protocol"] = PROTOCOL_NAME;
  doc["board_uid"] = currentBoardUid();
  doc["lock_id"] = g_config.lockId;
  doc["device_name"] = g_config.deviceName;
  doc["wifi_ssid"] = g_config.wifiSsid;
  doc["wifi_connected"] = g_wifiConnected;
  doc["camera_ready"] = g_cameraReady;
  doc["ip_address"] = currentIpAddress();
  doc["timestamp"] = formatTimestamp();
  String response;
  serializeJson(doc, response);
  g_server.send(200, "application/json; charset=utf-8", response);
}

void handleCapture() {
  if (!g_cameraReady) {
    g_server.send(503, "text/plain", "camera not ready");
    return;
  }

  camera_fb_t *frame = esp_camera_fb_get();
  if (frame == nullptr) {
    appendLog("Frame capture failed");
    g_server.send(500, "text/plain", "capture failed");
    return;
  }

  WiFiClient client = g_server.client();
  g_server.setContentLength(frame->len);
  g_server.send(200, "image/jpeg", "");
  client.write(frame->buf, frame->len);
  esp_camera_fb_return(frame);
}

void ensureWebServerStarted() {
  if (g_httpServerStarted || !g_wifiConnected) {
    return;
  }
  g_server.on("/", handleRootPage);
  g_server.on("/status", handleStatusJson);
  g_server.on("/capture.jpg", handleCapture);
  g_server.begin();
  g_httpServerStarted = true;
  appendLog("HTTP server started on http://" + currentIpAddress() + "/");
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
  doc["chip"] = "ESP32-CAM";
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["board_uid"] = currentBoardUid();
  doc["camera_ready"] = g_cameraReady;
  sendJson(doc);
}

void handleProvision(JsonVariantConst payload) {
  appendLog("Received provision request over serial");
  DeviceConfig updated = g_config;

  if (!copyRequiredString(payload, updated.chip, sizeof(updated.chip), "chip")) {
    sendError("chip is required");
    return;
  }
  if (strcmp(updated.chip, "ESP32-CAM") != 0) {
    sendError("chip must be ESP32-CAM for this firmware");
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
  saveConfig();
  appendLog("Configuration saved to NVS for Lock ID " + String(g_config.lockId));
  bool wifiOk = connectToWifi();

  StaticJsonDocument<256> doc;
  doc["ok"] = true;
  doc["status"] = "provisioned";
  doc["restart_required"] = true;
  doc["wifi_connected"] = wifiOk;
  doc["camera_ready"] = g_cameraReady;
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
  loadConfig();
  appendLog("Boot completed");
  g_cameraReady = initCamera();
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
