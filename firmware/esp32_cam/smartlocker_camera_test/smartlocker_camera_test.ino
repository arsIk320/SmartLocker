#include <ArduinoJson.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <esp_camera.h>
#include <time.h>

#define FLASH_PIN 4

// AI Thinker ESP32-CAM pin map.
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22

namespace {
constexpr unsigned long SERIAL_BAUD = 9600;
constexpr unsigned long WIFI_CONNECT_TIMEOUT_MS = 20000;
constexpr unsigned long WIFI_RETRY_DELAY_MS = 500;
constexpr unsigned long WIFI_RECONNECT_INTERVAL_MS = 5000;
constexpr unsigned long POST_CAPTURE_COOLDOWN_MS = 1500;
constexpr unsigned long SOCKET_WRITE_TIMEOUT_MS = 20000;
constexpr unsigned long SOCKET_RESPONSE_TIMEOUT_MS = 60000;
constexpr unsigned long CLIENT_STREAM_TIMEOUT_MS = 60000;
constexpr unsigned long FRAME_FLUSH_DELAY_MS = 80;
constexpr int FRAME_FLUSH_COUNT = 3;
constexpr size_t LOG_CAPACITY = 32;

constexpr char PROTOCOL_NAME[] = "smartlocker-provisioning-v1";
constexpr char FIRMWARE_VERSION[] = "0.2.0-face-cam-uart";
constexpr char DEFAULT_BOARD_UID[] = "ESP32CAM-TEMP";
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
  char apiKey[96];
  char apiBaseUrl[160];
  char bookingCode[64];
};

struct ParsedUrl {
  bool secure;
  String host;
  uint16_t port;
  String path;
};

Preferences g_preferences;
DeviceConfig g_config{};
WebServer g_server(80);

String g_serialBuffer;
String g_logs[LOG_CAPACITY];
size_t g_logCount = 0;
size_t g_logCursor = 0;

bool g_cameraReady = false;
bool g_wifiConnected = false;
bool g_wifiConnectInProgress = false;
bool g_httpServerStarted = false;
bool g_captureInProgress = false;

unsigned long g_bootMillis = 0;
unsigned long g_lastCaptureAt = 0;
unsigned long g_wifiConnectStartedAt = 0;
unsigned long g_lastWifiAttemptAt = 0;

void clearConfig(DeviceConfig &config);
void loadConfig();
void saveConfig();
const char *currentBoardUid();
String currentIpAddress();
String formatTimestamp();
String htmlEscape(const String &value);
String renderLogsHtml();
void appendLog(const String &message);
void reportStatus(const String &message);

bool initCamera();
camera_fb_t *captureFreshFrame();
camera_fb_t *captureWithRetries();

void handleRootPage();
void handleStatusJson();
void handleCapture();
void ensureWebServerStarted();

void beginWiFiConnect();
void serviceWiFiConnection();
bool ensureWiFiConnected(unsigned long timeoutMs = WIFI_CONNECT_TIMEOUT_MS);

String buildVerifyUrl();
bool parseUrl(const String &url, ParsedUrl &parsed);
bool connectClient(Client &client, const ParsedUrl &parsed);
bool streamBody(Client &client, const uint8_t *buffer, size_t length);
bool readHttpResponseRaw(Client &client, String &rawResponse);
bool parseHttpResponse(const String &rawResponse, int &statusCode, String &responseBody);
bool writeImageRequest(Client &client, const ParsedUrl &parsed, camera_fb_t *fb, String &responseBody, int &statusCode);
String jsonValueToString(JsonVariantConst value);
bool parseVerifyDecision(
    const String &responseBody,
    bool &openDoor,
    String &reason,
    String &distance,
    String &confidence,
    String &bookingCode,
    String &errorText);
void sendPhoto(camera_fb_t *fb);
void takePhoto();

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

String formatTimestamp() {
  time_t now = time(nullptr);
  if (now < 100000) {
    unsigned long uptimeSeconds = (millis() - g_bootMillis) / 1000;
    return "uptime " + String(uptimeSeconds) + "s";
  }

  struct tm timeInfo {};
  if (!localtime_r(&now, &timeInfo)) {
    return "time unavailable";
  }

  char buffer[32];
  strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", &timeInfo);
  return String(buffer);
}

String htmlEscape(const String &value) {
  String escaped = value;
  escaped.replace("&", "&amp;");
  escaped.replace("<", "&lt;");
  escaped.replace(">", "&gt;");
  escaped.replace("\"", "&quot;");
  return escaped;
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

void appendLog(const String &message) {
  String entry = formatTimestamp() + " | " + message;
  g_logs[g_logCursor] = entry;
  g_logCursor = (g_logCursor + 1) % LOG_CAPACITY;
  if (g_logCount < LOG_CAPACITY) {
    ++g_logCount;
  }
}

void reportStatus(const String &message) {
  appendLog(message);
  Serial.print("STATUS:");
  Serial.println(message);
}

bool initCamera() {
  camera_config_t config{};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 8000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = psramFound() ? FRAMESIZE_UXGA : FRAMESIZE_SVGA;
  config.jpeg_quality = psramFound() ? 10 : 12;
  config.fb_count = 1;
  config.grab_mode = CAMERA_GRAB_LATEST;
  config.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    appendLog("Camera init failed, err=" + String(static_cast<int>(err)));
    return false;
  }

  sensor_t *sensor = esp_camera_sensor_get();
  if (sensor != nullptr) {
    sensor->set_vflip(sensor, 1);
    sensor->set_brightness(sensor, 0);
    sensor->set_contrast(sensor, 0);
    sensor->set_saturation(sensor, 0);
  }

  appendLog("Camera initialized");
  return true;
}

camera_fb_t *captureFreshFrame() {
  camera_fb_t *fb = nullptr;

  for (int i = 0; i < FRAME_FLUSH_COUNT; ++i) {
    fb = esp_camera_fb_get();
    if (fb != nullptr) {
      esp_camera_fb_return(fb);
      fb = nullptr;
    }
    delay(FRAME_FLUSH_DELAY_MS);
  }

  return esp_camera_fb_get();
}

camera_fb_t *captureWithRetries() {
  for (int attempt = 0; attempt < 3; ++attempt) {
    camera_fb_t *fb = captureFreshFrame();
    if (fb != nullptr) {
      return fb;
    }
    reportStatus("Camera frame retry " + String(attempt + 1));
    delay(120);
  }
  return nullptr;
}

void handleRootPage() {
  String html;
  html.reserve(4600);
  html += "<!DOCTYPE html><html><head><meta charset='utf-8'>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1'>";
  html += "<title>SmartLocker ESP32-CAM</title>";
  html += "<style>";
  html += "body{font-family:Segoe UI,Arial,sans-serif;background:#10202d;color:#eaf2f8;margin:0;padding:24px;}";
  html += ".card{background:#182c3b;border:1px solid #2c485c;border-radius:18px;padding:20px;margin-bottom:18px;}";
  html += "h1,h2{margin-top:0;} .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;}";
  html += "img{max-width:100%;border-radius:12px;border:1px solid #2c485c;} code{word-break:break-all;} a{color:#7fd4ff;}";
  html += "</style></head><body>";
  html += "<div class='card'><h1>SmartLocker ESP32-CAM</h1>";
  html += "<p>Camera node for UART trigger, face verification and diagnostics.</p></div>";
  html += "<div class='card'><h2>Status</h2><div class='grid'>";
  html += "<div><strong>Firmware</strong><br>" + htmlEscape(FIRMWARE_VERSION) + "</div>";
  html += "<div><strong>Protocol</strong><br>" + htmlEscape(PROTOCOL_NAME) + "</div>";
  html += "<div><strong>Board UID</strong><br>" + htmlEscape(currentBoardUid()) + "</div>";
  html += "<div><strong>Lock ID</strong><br>" + htmlEscape(String(g_config.lockId)) + "</div>";
  html += "<div><strong>Camera</strong><br>" + String(g_cameraReady ? "ready" : "not ready") + "</div>";
  html += "<div><strong>Capture</strong><br>" + String(g_captureInProgress ? "in progress" : "idle") + "</div>";
  html += "<div><strong>Wi-Fi</strong><br>" + htmlEscape(String(g_config.wifiSsid)) + "</div>";
  html += "<div><strong>IP address</strong><br>" + htmlEscape(currentIpAddress()) + "</div>";
  html += "<div><strong>API base URL</strong><br><code>" + htmlEscape(String(g_config.apiBaseUrl)) + "</code></div>";
  html += "<div><strong>Date / time</strong><br>" + htmlEscape(formatTimestamp()) + "</div>";
  html += "</div></div>";
  html += "<div class='card'><h2>Preview</h2>";
  if (g_cameraReady) {
    html += "<p><a href='/capture.jpg' target='_blank'>Open latest JPEG frame</a></p>";
    html += "<img src='/capture.jpg' alt='camera preview'>";
  } else {
    html += "<p>Camera is not initialized yet.</p>";
  }
  html += "</div>";
  html += "<div class='card'><h2>Logs</h2>" + renderLogsHtml() + "</div>";
  html += "</body></html>";
  g_server.send(200, "text/html; charset=utf-8", html);
}

void handleStatusJson() {
  StaticJsonDocument<768> doc;
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
  doc["capture_in_progress"] = g_captureInProgress;
  doc["door_uid"] = g_config.doorUid;
  doc["api_base_url"] = g_config.apiBaseUrl;
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

  camera_fb_t *frame = captureFreshFrame();
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

void beginWiFiConnect() {
  if (g_config.wifiSsid[0] == '\0') {
    g_wifiConnected = false;
    g_wifiConnectInProgress = false;
    reportStatus("Wi-Fi SSID is empty");
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
  reportStatus("Connecting to Wi-Fi");
}

void serviceWiFiConnection() {
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
      reportStatus("Wi-Fi connected: " + WiFi.localIP().toString());
      ensureWebServerStarted();
    }
    return;
  }

  g_wifiConnected = false;
  if (g_wifiConnectInProgress) {
    if (millis() - g_wifiConnectStartedAt >= WIFI_CONNECT_TIMEOUT_MS) {
      g_wifiConnectInProgress = false;
      reportStatus("Wi-Fi timeout");
    }
    return;
  }

  if (millis() - g_lastWifiAttemptAt >= WIFI_RECONNECT_INTERVAL_MS) {
    beginWiFiConnect();
  }
}

bool ensureWiFiConnected(unsigned long timeoutMs) {
  if (WiFi.status() != WL_CONNECTED && !g_wifiConnectInProgress) {
    beginWiFiConnect();
  }

  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < timeoutMs) {
    serviceWiFiConnection();
    delay(WIFI_RETRY_DELAY_MS);
  }

  if (WiFi.status() == WL_CONNECTED) {
    g_wifiConnected = true;
    ensureWebServerStarted();
    return true;
  }

  reportStatus("Wi-Fi unavailable");
  return false;
}

String buildVerifyUrl() {
  String baseUrl = String(g_config.apiBaseUrl);
  baseUrl.trim();
  if (baseUrl.length() == 0) {
    return "";
  }
  if (baseUrl.endsWith("/")) {
    baseUrl.remove(baseUrl.length() - 1);
  }
  return baseUrl + "/api/v1/locks/face/verify";
}

bool parseUrl(const String &url, ParsedUrl &parsed) {
  parsed = ParsedUrl{false, "", 0, "/"};

  int schemeSeparator = url.indexOf("://");
  if (schemeSeparator <= 0) {
    return false;
  }

  String scheme = url.substring(0, schemeSeparator);
  parsed.secure = scheme == "https";
  int hostStart = schemeSeparator + 3;
  int pathStart = url.indexOf('/', hostStart);
  String hostPort = pathStart == -1 ? url.substring(hostStart) : url.substring(hostStart, pathStart);
  parsed.path = pathStart == -1 ? "/" : url.substring(pathStart);

  int colonPos = hostPort.indexOf(':');
  if (colonPos >= 0) {
    parsed.host = hostPort.substring(0, colonPos);
    parsed.port = static_cast<uint16_t>(hostPort.substring(colonPos + 1).toInt());
  } else {
    parsed.host = hostPort;
    parsed.port = parsed.secure ? 443 : 80;
  }

  parsed.host.trim();
  return parsed.host.length() > 0 && parsed.port > 0;
}

bool connectClient(Client &client, const ParsedUrl &parsed) {
  reportStatus("Connecting to " + parsed.host + ":" + String(parsed.port));
  IPAddress ip;
  if (ip.fromString(parsed.host)) {
    return client.connect(ip, parsed.port);
  }
  return client.connect(parsed.host.c_str(), parsed.port);
}

bool streamBody(Client &client, const uint8_t *buffer, size_t length) {
  size_t offset = 0;
  unsigned long lastProgressAt = millis();
  while (offset < length) {
    if (!client.connected()) {
      return false;
    }
    if (millis() - lastProgressAt >= SOCKET_WRITE_TIMEOUT_MS) {
      return false;
    }

    size_t chunk = min(static_cast<size_t>(128), length - offset);
    size_t written = client.write(buffer + offset, chunk);
    if (written == 0) {
      delay(4);
      continue;
    }
    offset += written;
    lastProgressAt = millis();
    delay(1);
  }
  return true;
}

bool readHttpResponseRaw(Client &client, String &rawResponse) {
  unsigned long lastDataAt = millis();
  while (!client.available() && client.connected() && millis() - lastDataAt < SOCKET_RESPONSE_TIMEOUT_MS) {
    delay(10);
  }

  if (!client.available()) {
    reportStatus("No HTTP response received");
    return false;
  }

  while (client.connected() || client.available()) {
    while (client.available()) {
      char c = static_cast<char>(client.read());
      rawResponse += c;
      lastDataAt = millis();
    }
    if (!client.connected() && !client.available()) {
      break;
    }
    if (millis() - lastDataAt >= SOCKET_RESPONSE_TIMEOUT_MS) {
      reportStatus("HTTP response read timeout");
      break;
    }
    delay(1);
  }

  return rawResponse.length() > 0;
}

bool parseHttpResponse(const String &rawResponse, int &statusCode, String &responseBody) {
  int statusPos = rawResponse.indexOf("HTTP/1.");
  if (statusPos < 0) {
    reportStatus("Invalid HTTP response");
    return false;
  }

  int lineEnd = rawResponse.indexOf("\r\n", statusPos);
  if (lineEnd < 0) {
    lineEnd = rawResponse.indexOf('\n', statusPos);
  }
  if (lineEnd < 0) {
    reportStatus("Invalid HTTP status line");
    return false;
  }

  String statusLine = rawResponse.substring(statusPos, lineEnd);
  int firstSpace = statusLine.indexOf(' ');
  int secondSpace = statusLine.indexOf(' ', firstSpace + 1);
  String codeText = secondSpace == -1 ? statusLine.substring(firstSpace + 1) : statusLine.substring(firstSpace + 1, secondSpace);
  statusCode = codeText.toInt();
  if (statusCode <= 0) {
    reportStatus("Invalid HTTP status code");
    return false;
  }

  int bodyStart = rawResponse.indexOf("\r\n\r\n", statusPos);
  int separatorLen = 4;
  if (bodyStart < 0) {
    bodyStart = rawResponse.indexOf("\n\n", statusPos);
    separatorLen = 2;
  }
  responseBody = bodyStart >= 0 ? rawResponse.substring(bodyStart + separatorLen) : "";
  return true;
}

bool writeImageRequest(Client &client, const ParsedUrl &parsed, camera_fb_t *fb, String &responseBody, int &statusCode) {
  client.print(String("POST ") + parsed.path + " HTTP/1.1\r\n");
  client.print(String("Host: ") + parsed.host + "\r\n");
  client.print("Connection: close\r\n");
  client.print(String("X-Lock-Id: ") + g_config.lockId + "\r\n");
  client.print(String("X-Lock-Api-Key: ") + g_config.apiKey + "\r\n");
  if (g_config.bookingCode[0] != '\0') {
    client.print(String("X-Booking-Code: ") + g_config.bookingCode + "\r\n");
  }
  client.print("Content-Type: image/jpeg\r\n");
  client.print(String("Content-Length: ") + fb->len + "\r\n\r\n");

  if (!streamBody(client, fb->buf, fb->len)) {
    reportStatus("Failed to stream JPEG body");
    return false;
  }
  client.flush();

  String rawResponse;
  if (!readHttpResponseRaw(client, rawResponse) || !parseHttpResponse(rawResponse, statusCode, responseBody)) {
    reportStatus("HTTP response read failed");
    return false;
  }

  reportStatus("HTTP " + String(statusCode));
  return statusCode >= 200 && statusCode < 300;
}

String jsonValueToString(JsonVariantConst value) {
  if (value.isNull()) {
    return "";
  }
  if (value.is<const char *>()) {
    return String(value.as<const char *>());
  }
  if (value.is<bool>()) {
    return value.as<bool>() ? "true" : "false";
  }

  String text;
  serializeJson(value, text);
  return text;
}

bool parseVerifyDecision(
    const String &responseBody,
    bool &openDoor,
    String &reason,
    String &distance,
    String &confidence,
    String &bookingCode,
    String &errorText) {
  StaticJsonDocument<1024> doc;
  DeserializationError error = deserializeJson(doc, responseBody);
  if (error) {
    reportStatus("Failed to parse verify JSON");
    return false;
  }

  openDoor = doc["open_door"] | false;
  reason = jsonValueToString(doc["reason"]);
  distance = jsonValueToString(doc["distance"]);
  confidence = jsonValueToString(doc["confidence"]);
  bookingCode = jsonValueToString(doc["booking_code"]);
  if (bookingCode.length() == 0) {
    bookingCode = jsonValueToString(doc["reservation_external_id"]);
  }
  errorText = jsonValueToString(doc["error"]);
  return true;
}

void sendPhoto(camera_fb_t *fb) {
  if (fb == nullptr) {
    Serial.println("ACCESS_DENIED");
    return;
  }

  reportStatus("JPEG size=" + String(fb->len));
  if (!ensureWiFiConnected(5000)) {
    reportStatus("Wi-Fi unavailable after capture");
    Serial.println("ACCESS_DENIED");
    return;
  }

  String url = buildVerifyUrl();
  if (url.length() == 0 || String(g_config.lockId).length() == 0 || String(g_config.apiKey).length() == 0) {
    reportStatus("Provisioning is incomplete");
    Serial.println("ACCESS_DENIED");
    return;
  }

  ParsedUrl parsed;
  if (!parseUrl(url, parsed)) {
    reportStatus("Invalid API URL");
    Serial.println("ACCESS_DENIED");
    return;
  }

  String response;
  int statusCode = 0;
  bool ok = false;

  if (parsed.secure) {
    WiFiClientSecure client;
    client.setInsecure();
    client.setTimeout(CLIENT_STREAM_TIMEOUT_MS);
    client.setNoDelay(true);
    if (connectClient(client, parsed)) {
      ok = writeImageRequest(client, parsed, fb, response, statusCode);
      client.stop();
    } else {
      reportStatus("HTTPS connect failed");
    }
  } else {
    WiFiClient client;
    client.setTimeout(CLIENT_STREAM_TIMEOUT_MS);
    client.setNoDelay(true);
    if (connectClient(client, parsed)) {
      ok = writeImageRequest(client, parsed, fb, response, statusCode);
      client.stop();
    } else {
      reportStatus("HTTP connect failed");
    }
  }

  if (!ok) {
    reportStatus("Face verify request failed");
    Serial.println("ACCESS_DENIED");
    return;
  }

  bool openDoor = false;
  String reason;
  String distance;
  String confidence;
  String bookingCode;
  String errorText;
  if (!parseVerifyDecision(response, openDoor, reason, distance, confidence, bookingCode, errorText)) {
    Serial.println("ACCESS_DENIED");
    return;
  }

  reportStatus("Reason=" + reason + ", distance=" + distance + ", confidence=" + confidence);
  if (bookingCode.length() > 0) {
    reportStatus("Booking=" + bookingCode);
  }
  if (errorText.length() > 0) {
    reportStatus("Error=" + errorText);
  }

  Serial.println(openDoor ? "ACCESS_GRANTED" : "ACCESS_DENIED");
}

void takePhoto() {
  if (g_captureInProgress) {
    reportStatus("Capture already in progress");
    return;
  }

  if (millis() - g_lastCaptureAt < POST_CAPTURE_COOLDOWN_MS) {
    reportStatus("Capture cooldown active");
    return;
  }

  g_captureInProgress = true;
  reportStatus("Capturing face");
  digitalWrite(FLASH_PIN, HIGH);
  delay(220);
  camera_fb_t *fb = captureWithRetries();
  digitalWrite(FLASH_PIN, LOW);

  if (fb == nullptr) {
    reportStatus("Camera capture failed");
    Serial.println("ACCESS_DENIED");
    g_captureInProgress = false;
    return;
  }

  sendPhoto(fb);
  esp_camera_fb_return(fb);
  g_lastCaptureAt = millis();
  delay(250);
  g_captureInProgress = false;
}

void handleIdentify() {
  StaticJsonDocument<320> doc;
  doc["ok"] = true;
  doc["protocol"] = PROTOCOL_NAME;
  doc["chip"] = "ESP32-CAM";
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["board_uid"] = currentBoardUid();
  doc["lock_id"] = g_config.lockId;
  doc["wifi_connected"] = WiFi.status() == WL_CONNECTED;
  doc["camera_ready"] = g_cameraReady;
  sendJson(doc);
}

void handleProvision(JsonVariantConst payload) {
  DeviceConfig updated = g_config;

  const char *chip = payload["chip"] | "";
  String normalizedChip = String(chip);
  normalizedChip.trim();
  normalizedChip.toUpperCase();
  if (normalizedChip != "ESP32" && normalizedChip != "ESP32-CAM") {
    sendError("chip must be ESP32-CAM for this firmware");
    return;
  }
  strlcpy(updated.chip, "ESP32-CAM", sizeof(updated.chip));

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
  const char *bookingCode = payload["booking_code"] | "";
  strlcpy(updated.ownerEmail, ownerEmail, sizeof(updated.ownerEmail));
  strlcpy(updated.doorUid, doorUid, sizeof(updated.doorUid));
  strlcpy(updated.bookingCode, bookingCode, sizeof(updated.bookingCode));

  g_config = updated;
  saveConfig();

  WiFi.disconnect(false, false);
  g_wifiConnected = false;
  g_wifiConnectInProgress = false;

  StaticJsonDocument<384> doc;
  doc["ok"] = true;
  doc["status"] = "provisioned";
  doc["restart_required"] = false;
  doc["wifi_connected"] = false;
  doc["camera_ready"] = g_cameraReady;
  doc["board_uid"] = g_config.boardUid;
  doc["api_base_url"] = g_config.apiBaseUrl;
  sendJson(doc);

  reportStatus("Provisioning saved");
  beginWiFiConnect();
}

void handlePlainCommand(const String &rawCommand) {
  String cmd = rawCommand;
  cmd.trim();
  if (cmd.isEmpty()) {
    return;
  }

  if (cmd == "ping") {
    Serial.println("PONG");
    return;
  }

  if (cmd == "capture-now") {
    takePhoto();
    return;
  }

  if (cmd == "status-json") {
    StaticJsonDocument<384> doc;
    doc["ok"] = true;
    doc["chip"] = "ESP32-CAM";
    doc["lock_id"] = g_config.lockId;
    doc["door_uid"] = g_config.doorUid;
    doc["wifi_connected"] = WiFi.status() == WL_CONNECTED;
    doc["camera_ready"] = g_cameraReady;
    doc["capture_in_progress"] = g_captureInProgress;
    doc["api_base_url"] = g_config.apiBaseUrl;
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
  delay(1000);

  g_bootMillis = millis();
  pinMode(FLASH_PIN, OUTPUT);
  digitalWrite(FLASH_PIN, LOW);

  loadConfig();
  WiFi.persistent(false);
  WiFi.mode(WIFI_OFF);
  WiFi.setSleep(false);

  g_cameraReady = initCamera();
  if (!g_cameraReady) {
    reportStatus("Camera init failed");
    while (true) {
      delay(1000);
    }
  }

  if (g_config.wifiSsid[0] != '\0') {
    beginWiFiConnect();
  }
  reportStatus("Face camera ready");
}

void loop() {
  serviceWiFiConnection();
  if (g_httpServerStarted) {
    g_server.handleClient();
  }

  while (Serial.available() > 0) {
    char ch = static_cast<char>(Serial.read());

    if (ch == '1' && g_serialBuffer.length() == 0) {
      takePhoto();
      continue;
    }

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

  delay(10);
}
