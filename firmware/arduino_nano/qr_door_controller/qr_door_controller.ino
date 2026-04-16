#include <ArduinoJson.h>
#include <memory>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WiFiClient.h>
#include "esp_camera.h"

#define FLASH_PIN 4

// ===== CAMERA PINS (AI Thinker ESP32-CAM) =====
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
constexpr char PROTOCOL_NAME[] = "smartlocker-provisioning-v1";
constexpr char FIRMWARE_VERSION[] = "0.1.0-face-cam";
constexpr char DEFAULT_BOARD_UID[] = "ESP32CAM-TEMP";
constexpr char DEFAULT_API_BASE_URL[] = "http://188.130.251.23";

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

Preferences g_preferences;
DeviceConfig g_config{};
String g_serialBuffer;
bool g_captureInProgress = false;
unsigned long g_lastCaptureAt = 0;
bool g_wifiConnected = false;
bool g_wifiConnectInProgress = false;
unsigned long g_wifiConnectStartedAt = 0;
unsigned long g_lastWifiAttemptAt = 0;

struct ParsedUrl {
  bool secure;
  String host;
  uint16_t port;
  String path;
};

void reportStatus(const String &message);
bool streamBody(Client &client, const uint8_t *buffer, size_t length);

bool connectClient(Client &client, const ParsedUrl &parsed) {
  reportStatus("Connecting to " + parsed.host + ":" + String(parsed.port));
  IPAddress ip;
  if (ip.fromString(parsed.host)) {
    return client.connect(ip, parsed.port);
  }
  return client.connect(parsed.host.c_str(), parsed.port);
}

void clearConfig(DeviceConfig &config) {
  memset(&config, 0, sizeof(config));
  strlcpy(config.chip, "ESP32", sizeof(config.chip));
  strlcpy(config.boardUid, DEFAULT_BOARD_UID, sizeof(config.boardUid));
  strlcpy(config.apiBaseUrl, DEFAULT_API_BASE_URL, sizeof(config.apiBaseUrl));
}

void loadConfig() {
  clearConfig(g_config);
  g_preferences.begin("smartlocker", true);
  String chip = g_preferences.getString("chip", "ESP32");
  String lockId = g_preferences.getString("lock_id", "");
  String boardUid = g_preferences.getString("board_uid", DEFAULT_BOARD_UID);
  String deviceName = g_preferences.getString("device_name", "");
  String wifiSsid = g_preferences.getString("wifi_ssid", "");
  String wifiPassword = g_preferences.getString("wifi_password", "");
  String ownerEmail = g_preferences.getString("owner_email", "");
  String doorUid = g_preferences.getString("door_uid", "");
  String apiKey = g_preferences.getString("api_key", "");
  String apiBaseUrl = g_preferences.getString("api_base_url", DEFAULT_API_BASE_URL);
  String bookingCode = g_preferences.getString("booking_code", "");
  g_preferences.end();

  strlcpy(g_config.chip, chip.c_str(), sizeof(g_config.chip));
  strlcpy(g_config.lockId, lockId.c_str(), sizeof(g_config.lockId));
  strlcpy(g_config.boardUid, boardUid.c_str(), sizeof(g_config.boardUid));
  strlcpy(g_config.deviceName, deviceName.c_str(), sizeof(g_config.deviceName));
  strlcpy(g_config.wifiSsid, wifiSsid.c_str(), sizeof(g_config.wifiSsid));
  strlcpy(g_config.wifiPassword, wifiPassword.c_str(), sizeof(g_config.wifiPassword));
  strlcpy(g_config.ownerEmail, ownerEmail.c_str(), sizeof(g_config.ownerEmail));
  strlcpy(g_config.doorUid, doorUid.c_str(), sizeof(g_config.doorUid));
  strlcpy(g_config.apiKey, apiKey.c_str(), sizeof(g_config.apiKey));
  strlcpy(g_config.apiBaseUrl, apiBaseUrl.c_str(), sizeof(g_config.apiBaseUrl));
  strlcpy(g_config.bookingCode, bookingCode.c_str(), sizeof(g_config.bookingCode));
}

void saveConfig(const DeviceConfig &config) {
  g_preferences.begin("smartlocker", false);
  g_preferences.putString("chip", config.chip);
  g_preferences.putString("lock_id", config.lockId);
  g_preferences.putString("board_uid", config.boardUid);
  g_preferences.putString("device_name", config.deviceName);
  g_preferences.putString("wifi_ssid", config.wifiSsid);
  g_preferences.putString("wifi_password", config.wifiPassword);
  g_preferences.putString("owner_email", config.ownerEmail);
  g_preferences.putString("door_uid", config.doorUid);
  g_preferences.putString("api_key", config.apiKey);
  g_preferences.putString("api_base_url", config.apiBaseUrl);
  g_preferences.putString("booking_code", config.bookingCode);
  g_preferences.end();
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

String getValue(const String &json, const String &key) {
  String pattern = "\"" + key + "\":";
  int i = json.indexOf(pattern);
  if (i == -1) {
    return "";
  }

  i += pattern.length();
  while (i < static_cast<int>(json.length()) &&
         (json[i] == ' ' || json[i] == '\n' || json[i] == '\r')) {
    i++;
  }

  if (i >= static_cast<int>(json.length())) {
    return "";
  }

  if (json[i] == '"') {
    int end = json.indexOf("\"", i + 1);
    if (end == -1) {
      return "";
    }
    return json.substring(i + 1, end);
  }

  int endComma = json.indexOf(",", i);
  int endBrace = json.indexOf("}", i);
  int end = -1;
  if (endComma == -1) {
    end = endBrace;
  } else if (endBrace == -1) {
    end = endComma;
  } else {
    end = min(endComma, endBrace);
  }

  if (end == -1) {
    return "";
  }

  String value = json.substring(i, end);
  value.trim();
  return value;
}

void reportStatus(const String &message) {
  Serial.print("STATUS:");
  Serial.println(message);
}

String verifyUrl() {
  String baseUrl = String(g_config.apiBaseUrl);
  baseUrl.trim();
  if (baseUrl.endsWith("/")) {
    baseUrl.remove(baseUrl.length() - 1);
  }
  return baseUrl + "/api/v1/locks/face/verify";
}

String healthUrl() {
  String baseUrl = String(g_config.apiBaseUrl);
  baseUrl.trim();
  if (baseUrl.endsWith("/")) {
    baseUrl.remove(baseUrl.length() - 1);
  }
  return baseUrl + "/health";
}

String debugUploadUrl() {
  String baseUrl = String(g_config.apiBaseUrl);
  baseUrl.trim();
  if (baseUrl.endsWith("/")) {
    baseUrl.remove(baseUrl.length() - 1);
  }
  return baseUrl + "/api/v1/locks/debug/upload";
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
      reportStatus("Wi-Fi connected: " + WiFi.localIP().toString());
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

bool ensureWiFiConnected(unsigned long timeoutMs = WIFI_CONNECT_TIMEOUT_MS) {
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
    return true;
  }

  reportStatus("Wi-Fi unavailable");
  return false;
}

bool setupCamera() {
  camera_config_t config;
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
    reportStatus("Camera init failed");
    return false;
  }

  sensor_t *s = esp_camera_sensor_get();
  if (s != nullptr) {
    s->set_vflip(s, 1);
    s->set_brightness(s, 0);
    s->set_contrast(s, 0);
    s->set_saturation(s, 0);
  }
  return true;
}

camera_fb_t *captureFreshFrame() {
  camera_fb_t *fb = nullptr;

  for (int i = 0; i < FRAME_FLUSH_COUNT; i++) {
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

bool sendSimpleRequest(
    const ParsedUrl &parsed,
    const char *requestLine,
    const char *extraHeaders,
    const uint8_t *body,
    size_t bodyLength,
    String &responseBody,
    int &statusCode) {
  std::unique_ptr<Client> clientHolder;
  if (parsed.secure) {
    auto *secureClient = new WiFiClientSecure();
    secureClient->setInsecure();
    secureClient->setTimeout(CLIENT_STREAM_TIMEOUT_MS);
    secureClient->setNoDelay(true);
    clientHolder.reset(secureClient);
  } else {
    auto *plainClient = new WiFiClient();
    plainClient->setTimeout(CLIENT_STREAM_TIMEOUT_MS);
    plainClient->setNoDelay(true);
    clientHolder.reset(plainClient);
  }

  Client &client = *clientHolder;
  if (!connectClient(client, parsed)) {
    reportStatus(parsed.secure ? "HTTPS connect failed" : "HTTP connect failed");
    return false;
  }

  client.print(requestLine);
  client.print("\r\nHost: ");
  client.print(parsed.host);
  client.print("\r\nConnection: close\r\n");
  if (extraHeaders != nullptr && strlen(extraHeaders) > 0) {
    client.print(extraHeaders);
  }
  client.print("\r\n");

  if (bodyLength > 0 && !streamBody(client, body, bodyLength)) {
    reportStatus("Failed to stream request body");
    client.stop();
    return false;
  }

  client.flush();
  String rawResponse;
  bool ok = readHttpResponseRaw(client, rawResponse) && parseHttpResponse(rawResponse, statusCode, responseBody);
  client.stop();
  return ok;
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

bool writeImageRequest(Client &client, const ParsedUrl &parsed, camera_fb_t *fb, String &responseBody, int &statusCode) {
  client.print(String("POST ") + parsed.path + " HTTP/1.1\r\n");
  client.print(String("Host: ") + parsed.host + "\r\n");
  client.print("Connection: close\r\n");
  client.print(String("X-Lock-Id: ") + g_config.lockId + "\r\n");
  client.print(String("X-Lock-Api-Key: ") + g_config.apiKey + "\r\n");
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

void runNetworkSelfTest() {
  if (!ensureWiFiConnected()) {
    reportStatus("Wi-Fi unavailable");
    return;
  }

  ParsedUrl parsed;
  if (!parseUrl(healthUrl(), parsed)) {
    reportStatus("Invalid health URL");
    return;
  }

  String response;
  int statusCode = 0;
  if (sendSimpleRequest(parsed, "GET /health HTTP/1.1", "", nullptr, 0, response, statusCode)) {
    reportStatus("NET_TEST HTTP " + String(statusCode));
    Serial.println(response);
  } else {
    reportStatus("NET_TEST failed");
  }
}

void runDebugUploadTest() {
  if (!ensureWiFiConnected()) {
    reportStatus("Wi-Fi unavailable");
    return;
  }

  camera_fb_t *fb = captureWithRetries();
  if (fb == nullptr) {
    reportStatus("Camera capture failed");
    return;
  }

  reportStatus("JPEG size=" + String(fb->len));
  if (!ensureWiFiConnected(5000)) {
    reportStatus("Wi-Fi unavailable after capture");
    esp_camera_fb_return(fb);
    return;
  }

  ParsedUrl parsed;
  if (!parseUrl(debugUploadUrl(), parsed)) {
    reportStatus("Invalid debug upload URL");
    esp_camera_fb_return(fb);
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
      client.print(String("POST ") + parsed.path + " HTTP/1.1\r\n");
      client.print(String("Host: ") + parsed.host + "\r\n");
      client.print("Connection: close\r\n");
      client.print("Content-Type: image/jpeg\r\n");
      client.print(String("Content-Length: ") + fb->len + "\r\n\r\n");
      if (!streamBody(client, fb->buf, fb->len)) {
        reportStatus("Failed to stream JPEG body");
      } else {
        client.flush();
        String rawResponse;
        ok = readHttpResponseRaw(client, rawResponse) && parseHttpResponse(rawResponse, statusCode, response);
      }
      client.stop();
    } else {
      reportStatus("HTTPS connect failed");
    }
  } else {
    WiFiClient client;
    client.setTimeout(CLIENT_STREAM_TIMEOUT_MS);
    client.setNoDelay(true);
    if (connectClient(client, parsed)) {
      client.print(String("POST ") + parsed.path + " HTTP/1.1\r\n");
      client.print(String("Host: ") + parsed.host + "\r\n");
      client.print("Connection: close\r\n");
      client.print("Content-Type: image/jpeg\r\n");
      client.print(String("Content-Length: ") + fb->len + "\r\n\r\n");
      if (!streamBody(client, fb->buf, fb->len)) {
        reportStatus("Failed to stream JPEG body");
      } else {
        client.flush();
        String rawResponse;
        ok = readHttpResponseRaw(client, rawResponse) && parseHttpResponse(rawResponse, statusCode, response);
      }
      client.stop();
    } else {
      reportStatus("HTTP connect failed");
    }
  }

  esp_camera_fb_return(fb);
  if (ok) {
    reportStatus("DEBUG_UPLOAD HTTP " + String(statusCode));
    Serial.println(response);
  } else {
    reportStatus("DEBUG_UPLOAD failed");
  }
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

  if (!ensureWiFiConnected()) {
    Serial.println("ACCESS_DENIED");
    return;
  }

  String url = verifyUrl();
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

  String openDoor = getValue(response, "open_door");
  String reason = getValue(response, "reason");
  String distance = getValue(response, "distance");
  String confidence = getValue(response, "confidence");
  String bookingCode = getValue(response, "booking_code");
  String error = getValue(response, "error");

  reportStatus("Reason=" + reason + ", distance=" + distance + ", confidence=" + confidence);
  if (bookingCode.length() > 0) {
    reportStatus("Booking=" + bookingCode);
  }
  if (error.length() > 0) {
    reportStatus("Error=" + error);
  }
  if (openDoor == "true") {
    Serial.println("ACCESS_GRANTED");
  } else {
    Serial.println("ACCESS_DENIED");
  }
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
  doc["chip"] = "ESP32";
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["board_uid"] = g_config.boardUid[0] == '\0' ? DEFAULT_BOARD_UID : g_config.boardUid;
  doc["lock_id"] = g_config.lockId;
  doc["wifi_connected"] = WiFi.status() == WL_CONNECTED;
  sendJson(doc);
}

void handleProvision(JsonVariantConst payload) {
  DeviceConfig updated = g_config;

  if (!copyRequiredString(payload, updated.chip, sizeof(updated.chip), "chip")) {
    sendError("chip is required");
    return;
  }
  if (strcmp(updated.chip, "ESP32") != 0) {
    sendError("chip must be ESP32 for this firmware");
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
  const char *bookingCode = payload["booking_code"] | "";
  strlcpy(updated.ownerEmail, ownerEmail, sizeof(updated.ownerEmail));
  strlcpy(updated.doorUid, doorUid, sizeof(updated.doorUid));
  strlcpy(updated.bookingCode, bookingCode, sizeof(updated.bookingCode));

  g_config = updated;
  saveConfig(g_config);
  WiFi.disconnect(false, false);
  g_wifiConnected = false;
  g_wifiConnectInProgress = false;

  StaticJsonDocument<384> doc;
  doc["ok"] = true;
  doc["status"] = "provisioned";
  doc["restart_required"] = false;
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

  if (cmd == "status-json") {
    StaticJsonDocument<320> doc;
    doc["ok"] = true;
    doc["lock_id"] = g_config.lockId;
    doc["door_uid"] = g_config.doorUid;
    doc["wifi_connected"] = WiFi.status() == WL_CONNECTED;
    doc["api_base_url"] = g_config.apiBaseUrl;
    sendJson(doc);
    return;
  }

  if (cmd == "net-test") {
    runNetworkSelfTest();
    return;
  }

  if (cmd == "debug-upload") {
    runDebugUploadTest();
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

  pinMode(FLASH_PIN, OUTPUT);
  digitalWrite(FLASH_PIN, LOW);

  loadConfig();
  WiFi.persistent(false);
  WiFi.mode(WIFI_OFF);
  WiFi.setSleep(false);

  if (!setupCamera()) {
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
