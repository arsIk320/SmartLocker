#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <time.h>

#if __has_include(<LiquidCrystal_I2C.h>)
#include <LiquidCrystal_I2C.h>
#define SMARTLOCKER_LCD_ENABLED 1
#else
#define SMARTLOCKER_LCD_ENABLED 0
#endif

SET_LOOP_TASK_STACK_SIZE(16 * 1024);

namespace {
constexpr uint32_t CONFIG_MAGIC = 0x534C4B34;  // SLK4

constexpr unsigned long SERIAL_BAUD = 9600;
constexpr unsigned long SCANNER_BAUD = 9600;
constexpr unsigned long AUX_CONTROLLER_BAUD = 9600;

// Default pin map for ESP32 DevKit/WROOM boards.
constexpr int RELAY_PIN = 23;
constexpr int SCANNER_RX_PIN = 33;
constexpr int SCANNER_TX_PIN = 32;
constexpr int AUX_CONTROLLER_RX_PIN = 17;
constexpr int AUX_CONTROLLER_TX_PIN = 16;
constexpr int TRIGGER_PIN = 5;

constexpr size_t CODE_LEN = 11;
constexpr unsigned long LOCK_OPEN_TIME_MS = 2500;
constexpr unsigned long TRIGGER_INTERVAL_MS = 3000;
constexpr unsigned long CAMERA_RESPONSE_TIMEOUT_MS = 15000;
constexpr unsigned long WIFI_CONNECT_TIMEOUT_MS = 15000;
constexpr unsigned long WIFI_RETRY_DELAY_MS = 250;
constexpr unsigned long HTTP_TIMEOUT_MS = 10000;
constexpr unsigned long QR_REFRESH_INTERVAL_MS = 30000;
constexpr unsigned long QR_RETRY_INTERVAL_MS = 7000;
constexpr unsigned long WIFI_RECONNECT_INTERVAL_MS = 5000;
constexpr unsigned long LCD_MESSAGE_HOLD_MS = 2500;
constexpr bool SCANNER_DEBUG_LOG = false;

constexpr size_t LOG_CAPACITY = 32;
constexpr uint16_t CONTROL_TASK_STACK = 8192;
constexpr UBaseType_t CONTROL_TASK_PRIORITY = 1;
constexpr BaseType_t CONTROL_TASK_CORE = 0;

constexpr char PROTOCOL_NAME[] = "smartlocker-provisioning-v1";
constexpr char FIRMWARE_VERSION[] = "0.4.0-esp32-dual-core-lock";
constexpr char DEFAULT_BOARD_UID[] = "TEMP-BOOT";
constexpr char DEFAULT_API_BASE_URL[] = "http://188.130.251.23";
constexpr char PREFS_NAMESPACE[] = "smartlocker";
constexpr char PREFS_KEY_CONFIG[] = "config";
constexpr uint8_t LCD_COLUMNS = 16;
constexpr uint8_t LCD_ROWS = 2;
constexpr int LCD_SDA_PIN = 21;
constexpr int LCD_SCL_PIN = 22;

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

Preferences g_preferences;
DeviceConfig g_config{};
WebServer g_server(80);
HardwareSerial g_scannerSerial(2);
HardwareSerial g_auxControllerSerial(1);
DynamicJsonDocument g_qrResponseDoc(1024);

SemaphoreHandle_t g_stateMutex = nullptr;
SemaphoreHandle_t g_logMutex = nullptr;

#if SMARTLOCKER_LCD_ENABLED
LiquidCrystal_I2C *g_lcd = nullptr;
#endif

String g_serialBuffer;
String g_scannerCode;
String g_auxBuffer;
String g_logs[LOG_CAPACITY];
size_t g_logCount = 0;
size_t g_logCursor = 0;

bool g_httpServerStarted = false;
bool g_wifiConnectInProgress = false;
bool g_wifiConnected = false;
bool g_cachedQrReady = false;
bool g_lockActive = false;
bool g_lcdReady = false;

unsigned long g_bootMillis = 0;
unsigned long g_lastQrRefreshAt = 0;
unsigned long g_lastQrAttemptAt = 0;
unsigned long g_wifiConnectStartedAt = 0;
unsigned long g_lastWifiAttemptAt = 0;
unsigned long g_lockOpenedAt = 0;
unsigned long g_lcdMessageUntil = 0;
unsigned long g_lastTriggerAt = 0;
unsigned long g_cameraResponseDeadlineAt = 0;

bool g_presenceDetected = false;
bool g_presenceHandled = false;
bool g_cameraAwaitingResult = false;

char g_cachedCode[32] = {0};
char g_cachedDoorUid[32] = {0};
char g_cachedExpiresAt[48] = {0};
char g_lcdLine1[17] = {0};
char g_lcdLine2[17] = {0};
char g_localNetworkStatus[17] = "ESP: booting";
char g_auxNetworkStatus[17] = "CAM: unknown";

TaskHandle_t g_controlTaskHandle = nullptr;
bool g_networkLoopLogged = false;

String formatTimestamp();
void appendLog(const String &message);
void clearConfig(DeviceConfig &config);
void saveConfig(const DeviceConfig &config);
void loadConfig();
const char *currentBoardUid();
String currentIpAddress();
String buildQrUrl();
void beginWifiConnect();
void serviceWifiConnection();
bool fetchQrCodeFromServer();
void ensureWebServerStarted();
void resetWifiStation();
void serviceSerialCommands();
void handleIncomingLine(const String &line);
void handlePlainCommand(const String &command);
void handleIdentify();
void handleProvision(JsonVariantConst payload);
void sendCachedCode();
void readFromScanner();
void readFromAuxController();
void serviceTriggerInput();
void checkScannerCode(const String &candidateCode);
void handleAuxCommand(const String &command);
void openLock(const String &source);
void closeLockIfNeeded();
void controlTask(void *parameter);
void serviceNetworkLoop();
void initLcd();
void setLcdMessage(const String &line1, const String &line2, bool sticky = false);
void renderDefaultLcdState();
String fitLcdText(const String &value);
void setCompactStatus(char *target, size_t targetSize, const String &value);
void setLocalNetworkStatus(const String &value);
void setAuxNetworkStatus(const String &value);
void updateAuxNetworkStatusFromMessage(const String &message);
uint8_t detectLcdAddress();

bool takeMutex(SemaphoreHandle_t mutex, TickType_t timeout = pdMS_TO_TICKS(50)) {
  if (mutex == nullptr) {
    return false;
  }
  return xSemaphoreTake(mutex, timeout) == pdTRUE;
}

void releaseMutex(SemaphoreHandle_t mutex) {
  if (mutex != nullptr) {
    xSemaphoreGive(mutex);
  }
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
    unsigned long hours = uptimeSeconds / 3600;
    unsigned long minutes = (uptimeSeconds % 3600) / 60;
    unsigned long seconds = uptimeSeconds % 60;
    return "uptime " + String(hours) + "h " + String(minutes) + "m " + String(seconds) + "s";
  }

  struct tm info;
  if (!localtime_r(&now, &info)) {
    return "time unavailable";
  }

  char buffer[32];
  strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", &info);
  return String(buffer);
}

void appendLog(const String &message) {
  const String entry = formatTimestamp() + " | " + message;
  if (takeMutex(g_logMutex)) {
    g_logs[g_logCursor] = entry;
    g_logCursor = (g_logCursor + 1) % LOG_CAPACITY;
    if (g_logCount < LOG_CAPACITY) {
      ++g_logCount;
    }
    releaseMutex(g_logMutex);
  }
  Serial.println(entry);
}

String renderLogsHtml() {
  String html;
  html.reserve(2048);
  html += "<ul>";

  if (takeMutex(g_logMutex)) {
    for (size_t index = 0; index < g_logCount; ++index) {
      size_t actualIndex = (g_logCursor + LOG_CAPACITY - g_logCount + index) % LOG_CAPACITY;
      html += "<li>";
      html += htmlEscape(g_logs[actualIndex]);
      html += "</li>";
    }
    releaseMutex(g_logMutex);
  }

  html += "</ul>";
  return html;
}

String fitLcdText(const String &value) {
  String normalized = value;
  normalized.replace("\r", " ");
  normalized.replace("\n", " ");
  if (normalized.length() > LCD_COLUMNS) {
    normalized.remove(LCD_COLUMNS);
  }
  while (normalized.length() < LCD_COLUMNS) {
    normalized += ' ';
  }
  return normalized;
}

void setCompactStatus(char *target, size_t targetSize, const String &value) {
  String normalized = value;
  normalized.replace("\r", " ");
  normalized.replace("\n", " ");
  if (normalized.length() > LCD_COLUMNS) {
    normalized.remove(LCD_COLUMNS);
  }
  strlcpy(target, normalized.c_str(), targetSize);
}

void setLocalNetworkStatus(const String &value) {
  setCompactStatus(g_localNetworkStatus, sizeof(g_localNetworkStatus), value);
}

void setAuxNetworkStatus(const String &value) {
  setCompactStatus(g_auxNetworkStatus, sizeof(g_auxNetworkStatus), value);
}

void updateAuxNetworkStatusFromMessage(const String &message) {
  if (message.startsWith("STATUS:")) {
    const String payload = message.substring(7);
    if (payload.startsWith("Connecting to Wi-Fi")) {
      setAuxNetworkStatus("CAM: connect...");
    } else if (payload.startsWith("Wi-Fi connected")) {
      setAuxNetworkStatus("CAM: online");
    } else if (payload.startsWith("Wi-Fi timeout")) {
      setAuxNetworkStatus("CAM: timeout");
    } else if (payload.startsWith("Wi-Fi unavailable")) {
      setAuxNetworkStatus("CAM: offline");
    }
  }
}

uint8_t detectLcdAddress() {
  const uint8_t candidateAddresses[] = {0x27, 0x3F};
  for (uint8_t address : candidateAddresses) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      return address;
    }
  }
  return 0;
}

void initLcd() {
#if SMARTLOCKER_LCD_ENABLED
  Wire.begin(LCD_SDA_PIN, LCD_SCL_PIN);
  const uint8_t lcdAddress = detectLcdAddress();
  if (lcdAddress == 0) {
    g_lcdReady = false;
    appendLog("LCD not found on I2C");
    return;
  }

  g_lcd = new LiquidCrystal_I2C(lcdAddress, LCD_COLUMNS, LCD_ROWS);
  if (g_lcd == nullptr) {
    g_lcdReady = false;
    appendLog("LCD allocation failed");
    return;
  }

  g_lcd->init();
  g_lcd->backlight();
  g_lcd->clear();
  g_lcdReady = true;
  appendLog("LCD connected at 0x" + String(lcdAddress, HEX));
  setLcdMessage("SmartLocker", "Booting...", true);
#else
  g_lcdReady = false;
#endif
}

void setLcdMessage(const String &line1, const String &line2, bool sticky) {
  strlcpy(g_lcdLine1, fitLcdText(line1).c_str(), sizeof(g_lcdLine1));
  strlcpy(g_lcdLine2, fitLcdText(line2).c_str(), sizeof(g_lcdLine2));
  g_lcdMessageUntil = sticky ? 0 : millis() + LCD_MESSAGE_HOLD_MS;

#if SMARTLOCKER_LCD_ENABLED
  if (!g_lcdReady || g_lcd == nullptr) {
    return;
  }
  g_lcd->setCursor(0, 0);
  g_lcd->print(g_lcdLine1);
  g_lcd->setCursor(0, 1);
  g_lcd->print(g_lcdLine2);
#endif
}

void renderDefaultLcdState() {
  if (!g_lcdReady) {
    return;
  }
  if (g_lcdMessageUntil != 0 && millis() < g_lcdMessageUntil) {
    return;
  }

  String line1 = String(g_localNetworkStatus);
  String line2 = String(g_auxNetworkStatus);
  setLcdMessage(line1, line2, true);
}

void clearConfig(DeviceConfig &config) {
  memset(&config, 0, sizeof(config));
  config.magic = CONFIG_MAGIC;
  strlcpy(config.chip, "ESP32", sizeof(config.chip));
  strlcpy(config.boardUid, DEFAULT_BOARD_UID, sizeof(config.boardUid));
  strlcpy(config.apiBaseUrl, DEFAULT_API_BASE_URL, sizeof(config.apiBaseUrl));
}

void saveConfig(const DeviceConfig &config) {
  g_preferences.begin(PREFS_NAMESPACE, false);
  g_preferences.putBytes(PREFS_KEY_CONFIG, &config, sizeof(config));
  g_preferences.end();
}

void loadConfig() {
  DeviceConfig loaded{};
  clearConfig(loaded);

  g_preferences.begin(PREFS_NAMESPACE, true);
  size_t read = g_preferences.getBytes(PREFS_KEY_CONFIG, &loaded, sizeof(loaded));
  g_preferences.end();

  if (read != sizeof(loaded) || loaded.magic != CONFIG_MAGIC) {
    clearConfig(loaded);
    saveConfig(loaded);
  }

  if (takeMutex(g_stateMutex)) {
    g_config = loaded;
    releaseMutex(g_stateMutex);
  } else {
    g_config = loaded;
  }
}

const char *currentBoardUid() {
  if (g_config.boardUid[0] == '\0') {
    return DEFAULT_BOARD_UID;
  }
  return g_config.boardUid;
}

String currentIpAddress() {
  if (WiFi.status() != WL_CONNECTED) {
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

void setCachedQr(const char *code, const char *doorUid, const char *expiresAt) {
  if (!takeMutex(g_stateMutex)) {
    return;
  }

  strlcpy(g_cachedCode, code ? code : "", sizeof(g_cachedCode));
  strlcpy(g_cachedDoorUid, doorUid ? doorUid : "", sizeof(g_cachedDoorUid));
  strlcpy(g_cachedExpiresAt, expiresAt ? expiresAt : "", sizeof(g_cachedExpiresAt));
  g_cachedQrReady = g_cachedCode[0] != '\0';
  g_lastQrRefreshAt = millis();

  releaseMutex(g_stateMutex);
}

void clearCachedQr() {
  if (!takeMutex(g_stateMutex)) {
    return;
  }

  g_cachedCode[0] = '\0';
  g_cachedDoorUid[0] = '\0';
  g_cachedExpiresAt[0] = '\0';
  g_cachedQrReady = false;
  g_lastQrRefreshAt = 0;
  releaseMutex(g_stateMutex);
}

bool snapshotCachedQr(String &code, String &doorUid, String &expiresAt, unsigned long &lastRefreshAt) {
  if (!takeMutex(g_stateMutex)) {
    return false;
  }

  const bool ready = g_cachedQrReady;
  code = String(g_cachedCode);
  doorUid = String(g_cachedDoorUid);
  expiresAt = String(g_cachedExpiresAt);
  lastRefreshAt = g_lastQrRefreshAt;
  releaseMutex(g_stateMutex);
  return ready;
}

bool isWifiConnected() {
  if (!takeMutex(g_stateMutex)) {
    return g_wifiConnected;
  }
  const bool connected = g_wifiConnected;
  releaseMutex(g_stateMutex);
  return connected;
}

void setWifiConnected(bool connected) {
  if (!takeMutex(g_stateMutex)) {
    g_wifiConnected = connected;
    return;
  }
  g_wifiConnected = connected;
  releaseMutex(g_stateMutex);
}

bool isLockActive() {
  if (!takeMutex(g_stateMutex)) {
    return g_lockActive;
  }
  const bool active = g_lockActive;
  releaseMutex(g_stateMutex);
  return active;
}

void setLockState(bool active) {
  if (!takeMutex(g_stateMutex)) {
    g_lockActive = active;
    if (active) {
      g_lockOpenedAt = millis();
    }
    return;
  }

  g_lockActive = active;
  if (active) {
    g_lockOpenedAt = millis();
  }
  releaseMutex(g_stateMutex);
}

unsigned long lockOpenedAt() {
  if (!takeMutex(g_stateMutex)) {
    return g_lockOpenedAt;
  }
  const unsigned long openedAt = g_lockOpenedAt;
  releaseMutex(g_stateMutex);
  return openedAt;
}

void beginWifiConnect() {
  if (g_config.wifiSsid[0] == '\0') {
    setWifiConnected(false);
    g_wifiConnectInProgress = false;
    setLocalNetworkStatus("ESP: no SSID");
    return;
  }

  if (WiFi.status() == WL_CONNECTED) {
    setWifiConnected(true);
    g_wifiConnectInProgress = false;
    ensureWebServerStarted();
    return;
  }

  resetWifiStation();
  WiFi.begin(g_config.wifiSsid, g_config.wifiPassword);
  g_wifiConnectStartedAt = millis();
  g_lastWifiAttemptAt = millis();
  g_wifiConnectInProgress = true;
  setWifiConnected(false);
  appendLog("Connecting to Wi-Fi SSID: " + String(g_config.wifiSsid));
  setLocalNetworkStatus("ESP: connect...");
}

void resetWifiStation() {
  WiFi.disconnect(true, false);
  delay(100);
  WiFi.mode(WIFI_STA);
  delay(50);
}

void serviceWifiConnection() {
  if (g_config.wifiSsid[0] == '\0') {
    setWifiConnected(false);
    g_wifiConnectInProgress = false;
    return;
  }

  if (WiFi.status() == WL_CONNECTED) {
    if (!isWifiConnected()) {
      setWifiConnected(true);
      g_wifiConnectInProgress = false;
      configTime(0, 0, "pool.ntp.org", "time.nist.gov");
      appendLog("Wi-Fi connected, IP: " + WiFi.localIP().toString());
      setLocalNetworkStatus("ESP: online");
      ensureWebServerStarted();
    }
    return;
  }

  setWifiConnected(false);

  if (g_wifiConnectInProgress) {
    if (millis() - g_wifiConnectStartedAt >= WIFI_CONNECT_TIMEOUT_MS) {
      g_wifiConnectInProgress = false;
      g_lastWifiAttemptAt = millis();
      resetWifiStation();
      appendLog("Wi-Fi connection timeout");
      setLocalNetworkStatus("ESP: timeout");
    }
    return;
  }

  if (millis() - g_lastWifiAttemptAt >= WIFI_RECONNECT_INTERVAL_MS) {
    beginWifiConnect();
  }
}

void handleRootPage() {
  String code;
  String doorUid;
  String expiresAt;
  unsigned long lastRefreshAt = 0;
  snapshotCachedQr(code, doorUid, expiresAt, lastRefreshAt);

  String html;
  html.reserve(4600);
  html += "<!DOCTYPE html><html><head><meta charset='utf-8'>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1'>";
  html += "<title>SmartLocker ESP32 QR Lock</title>";
  html += "<style>";
  html += "body{font-family:Segoe UI,Arial,sans-serif;background:#eef3f7;color:#17324a;margin:0;padding:24px;}";
  html += ".card{background:#fff;border:1px solid #d8e3eb;border-radius:18px;padding:20px;margin-bottom:18px;}";
  html += "h1,h2{margin-top:0;} .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;}";
  html += "ul{padding-left:20px;} .muted{color:#5d7285;} code{word-break:break-all;}";
  html += "</style></head><body>";
  html += "<div class='card'><h1>SmartLocker ESP32 Dual-Core Lock</h1>";
  html += "<p class='muted'>Core 0: provisioning, Wi-Fi and SmartLocker API. Core 1: scanner, relay and local lock logic.</p></div>";
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
  html += "<div><strong>Cached QR</strong><br>" + htmlEscape(code) + "</div>";
  html += "<div><strong>QR expires</strong><br>" + htmlEscape(expiresAt) + "</div>";
  html += "<div><strong>Relay active</strong><br>" + String(isLockActive() ? "yes" : "no") + "</div>";
  html += "<div><strong>Pins</strong><br>";
  html += "Relay=" + String(RELAY_PIN) + ", scanner RX/TX=" + String(SCANNER_RX_PIN) + "/" + String(SCANNER_TX_PIN);
  html += ", aux RX/TX=" + String(AUX_CONTROLLER_RX_PIN) + "/" + String(AUX_CONTROLLER_TX_PIN);
  html += ", trigger=" + String(TRIGGER_PIN) + "</div>";
  html += "</div></div>";
  html += "<div class='card'><h2>Logs</h2>";
  html += renderLogsHtml();
  html += "</div></body></html>";
  g_server.send(200, "text/html; charset=utf-8", html);
}

void handleStatusJson() {
  String code;
  String doorUid;
  String expiresAt;
  unsigned long lastRefreshAt = 0;
  const bool qrReady = snapshotCachedQr(code, doorUid, expiresAt, lastRefreshAt);

  StaticJsonDocument<768> doc;
  doc["ok"] = true;
  doc["chip"] = "ESP32";
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["protocol"] = PROTOCOL_NAME;
  doc["board_uid"] = currentBoardUid();
  doc["lock_id"] = g_config.lockId;
  doc["device_name"] = g_config.deviceName;
  doc["wifi_ssid"] = g_config.wifiSsid;
  doc["wifi_connected"] = isWifiConnected();
  doc["ip_address"] = currentIpAddress();
  doc["door_uid"] = g_config.doorUid;
  doc["api_base_url"] = g_config.apiBaseUrl;
  doc["cached_code"] = code;
  doc["cached_door_uid"] = doorUid;
  doc["cached_expires_at"] = expiresAt;
  doc["cached_qr_ready"] = qrReady;
  doc["relay_active"] = isLockActive();
  doc["esp_network_status"] = g_localNetworkStatus;
  doc["aux_network_status"] = g_auxNetworkStatus;
  doc["timestamp"] = formatTimestamp();
  String response;
  serializeJson(doc, response);
  g_server.send(200, "application/json; charset=utf-8", response);
}

void handleRefreshQr() {
  const bool ok = fetchQrCodeFromServer();
  String code;
  String doorUid;
  String expiresAt;
  unsigned long lastRefreshAt = 0;
  snapshotCachedQr(code, doorUid, expiresAt, lastRefreshAt);

  StaticJsonDocument<256> doc;
  doc["ok"] = ok;
  doc["cached_code"] = code;
  doc["door_uid"] = doorUid;
  doc["expires_at"] = expiresAt;
  String response;
  serializeJson(doc, response);
  g_server.send(ok ? 200 : 502, "application/json; charset=utf-8", response);
}

void ensureWebServerStarted() {
  if (g_httpServerStarted || !isWifiConnected()) {
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
  g_lastQrAttemptAt = millis();

  if (g_config.lockId[0] == '\0' || g_config.apiKey[0] == '\0' || g_config.apiBaseUrl[0] == '\0') {
    appendLog("QR refresh skipped: provisioning is incomplete");
    return false;
  }

  if (!isWifiConnected()) {
    appendLog("QR refresh skipped: Wi-Fi is not connected");
    return false;
  }

  String url = buildQrUrl();
  if (url.length() == 0) {
    appendLog("QR refresh skipped: QR URL is empty");
    return false;
  }

  appendLog("Requesting current QR from " + url);

  int statusCode = -1;
  String payload;
  payload.reserve(512);

  if (url.startsWith("https://")) {
    WiFiClientSecure client;
    client.setInsecure();
    client.setTimeout(HTTP_TIMEOUT_MS);

    HTTPClient http;
    http.setReuse(false);
    http.setTimeout(HTTP_TIMEOUT_MS);

    if (!http.begin(client, url)) {
      appendLog("HTTP begin failed (TLS)");
      return false;
    }

    http.addHeader("X-Lock-Id", g_config.lockId);
    http.addHeader("X-Lock-Api-Key", g_config.apiKey);

    statusCode = http.GET();
    if (statusCode > 0) {
      payload = http.getString();
    }
    http.end();
  } else {
    WiFiClient client;
    client.setTimeout(HTTP_TIMEOUT_MS);

    HTTPClient http;
    http.setReuse(false);
    http.setTimeout(HTTP_TIMEOUT_MS);

    if (!http.begin(client, url)) {
      appendLog("HTTP begin failed");
      return false;
    }

    http.addHeader("X-Lock-Id", g_config.lockId);
    http.addHeader("X-Lock-Api-Key", g_config.apiKey);

    statusCode = http.GET();
    if (statusCode > 0) {
      payload = http.getString();
    }
    http.end();
  }

  if (statusCode <= 0) {
    appendLog("QR request failed with status " + String(statusCode) +
              " (" + HTTPClient::errorToString(statusCode) + ")");
    return false;
  }

  g_qrResponseDoc.clear();
  DeserializationError error = deserializeJson(g_qrResponseDoc, payload);
  if (error) {
    appendLog("Failed to parse QR JSON");
    return false;
  }

  const char *code = g_qrResponseDoc["code"] | "";
  const char *doorUid = g_qrResponseDoc["door_uid"] | "";
  const char *expiresAt = g_qrResponseDoc["expires_at"] | "";

  if (code[0] == '\0') {
    appendLog("QR code not found in response");
    clearCachedQr();
    return false;
  }

  setCachedQr(code, doorUid, expiresAt);

  Serial.print("CODE:");
  Serial.println(code);
  Serial.print("DOOR_UID:");
  Serial.println(doorUid);
  Serial.print("EXPIRES_AT:");
  Serial.println(expiresAt);

  appendLog("QR cache updated");
  return true;
}

void sendCachedCode() {
  String code;
  String doorUid;
  String expiresAt;
  unsigned long lastRefreshAt = 0;

  if (!snapshotCachedQr(code, doorUid, expiresAt, lastRefreshAt)) {
    if (!fetchQrCodeFromServer()) {
      Serial.println("ERROR:NO_CODE");
      return;
    }
    snapshotCachedQr(code, doorUid, expiresAt, lastRefreshAt);
  }

  Serial.print("CODE:");
  Serial.println(code);
  Serial.print("DOOR_UID:");
  Serial.println(doorUid);
  Serial.print("EXPIRES_AT:");
  Serial.println(expiresAt);
}

void handleIdentify() {
  appendLog("Received identify request over serial");
  StaticJsonDocument<320> doc;
  doc["ok"] = true;
  doc["protocol"] = PROTOCOL_NAME;
  doc["chip"] = "ESP32";
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["board_uid"] = currentBoardUid();
  doc["lock_id"] = g_config.lockId;
  doc["wifi_connected"] = isWifiConnected();
  sendJson(doc);
}

void handleProvision(JsonVariantConst payload) {
  appendLog("Received provision request over serial");

  DeviceConfig updated = g_config;
  updated.magic = CONFIG_MAGIC;

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
  strlcpy(updated.ownerEmail, ownerEmail, sizeof(updated.ownerEmail));
  strlcpy(updated.doorUid, doorUid, sizeof(updated.doorUid));

  if (takeMutex(g_stateMutex)) {
    g_config = updated;
    releaseMutex(g_stateMutex);
  } else {
    g_config = updated;
  }
  saveConfig(updated);
  clearCachedQr();

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

  appendLog("Configuration saved for Lock ID " + String(g_config.lockId));
  beginWifiConnect();
}

void handlePlainCommand(const String &rawCommand) {
  String cmd = rawCommand;
  cmd.trim();
  if (cmd.isEmpty()) {
    return;
  }

  Serial.print("[ESP32] CMD: ");
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
    String code;
    String doorUid;
    String expiresAt;
    unsigned long lastRefreshAt = 0;
    snapshotCachedQr(code, doorUid, expiresAt, lastRefreshAt);

    StaticJsonDocument<448> doc;
    doc["ok"] = true;
    doc["chip"] = "ESP32";
    doc["lock_id"] = g_config.lockId;
    doc["door_uid"] = g_config.doorUid;
    doc["wifi_connected"] = isWifiConnected();
    doc["cached_code"] = code;
    doc["cached_door_uid"] = doorUid;
    doc["cached_expires_at"] = expiresAt;
    doc["api_base_url"] = g_config.apiBaseUrl;
    doc["relay_active"] = isLockActive();
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
    handleProvision(doc["payload"]);
    return;
  }

  sendError("unsupported action");
}

void serviceSerialCommands() {
  while (Serial.available()) {
    const char ch = static_cast<char>(Serial.read());
    if (ch == '\n' || ch == '\r') {
      if (g_serialBuffer.length() > 0) {
        handleIncomingLine(g_serialBuffer);
        g_serialBuffer = "";
      }
      continue;
    }

    if (ch >= 32 || ch == '{' || ch == '}') {
      g_serialBuffer += ch;
      if (g_serialBuffer.length() > 2048) {
        g_serialBuffer = "";
        sendError("input too long");
      }
    }
  }
}

void openLock(const String &source) {
  digitalWrite(RELAY_PIN, HIGH);
  setLockState(true);
  g_presenceHandled = true;
  appendLog("Relay opened via " + source);
}

void closeLockIfNeeded() {
  if (!isLockActive()) {
    return;
  }

  if (millis() - lockOpenedAt() >= LOCK_OPEN_TIME_MS) {
    digitalWrite(RELAY_PIN, LOW);
    setLockState(false);
    appendLog("Relay closed");
  }
}

void handleAuxCommand(const String &command) {
  if (command == "D" || command == "5" || command == "ACCESS_GRANTED" || command == "FACE_GRANTED") {
    g_cameraAwaitingResult = false;
    g_cameraResponseDeadlineAt = 0;
    openLock("aux-controller");
  } else if (command.startsWith("STATUS:")) {
    appendLog("Aux " + command);
    updateAuxNetworkStatusFromMessage(command);
  } else if (command == "ACCESS_DENIED" || command == "FACE_DENIED") {
    g_cameraAwaitingResult = false;
    g_cameraResponseDeadlineAt = 0;
    appendLog("Aux denied access");
  }
}

void readFromAuxController() {
  while (g_auxControllerSerial.available()) {
    const char ch = static_cast<char>(g_auxControllerSerial.read());
    if (ch == '\n' || ch == '\r') {
      if (g_auxBuffer.length() > 0) {
        g_auxBuffer.trim();
        handleAuxCommand(g_auxBuffer);
        g_auxBuffer = "";
      }
      continue;
    }

    if (ch >= 32 && ch <= 126) {
      g_auxBuffer += ch;
      if (g_auxBuffer.length() > 64) {
        g_auxBuffer = "";
      }
    }
  }
}

void serviceTriggerInput() {
  const bool presenceActive = digitalRead(TRIGGER_PIN) == HIGH;
  const unsigned long now = millis();

  if (!presenceActive) {
    if (g_presenceDetected) {
      appendLog("Presence sensor cleared");
    }
    g_presenceDetected = false;
    g_presenceHandled = false;
    return;
  }

  if (!g_presenceDetected) {
    g_presenceDetected = true;
    appendLog("Presence sensor detected activity");
  }

  if (g_presenceHandled) {
    return;
  }

  if (isLockActive()) {
    return;
  }

  if (g_cameraAwaitingResult) {
    if (g_cameraResponseDeadlineAt != 0 && now >= g_cameraResponseDeadlineAt) {
      g_cameraAwaitingResult = false;
      g_cameraResponseDeadlineAt = 0;
      appendLog("Camera response timeout, retry will be allowed");
    } else {
      return;
    }
  }

  if (now - g_lastTriggerAt < TRIGGER_INTERVAL_MS) {
    return;
  }

  g_lastTriggerAt = now;
  g_cameraAwaitingResult = true;
  g_cameraResponseDeadlineAt = now + CAMERA_RESPONSE_TIMEOUT_MS;
  appendLog("Presence sensor active, requesting camera capture");
  g_auxControllerSerial.write('1');
  g_auxControllerSerial.flush();
  appendLog("Camera trigger sent");
}

void checkScannerCode(const String &candidateCode) {
  String storedCode;
  String doorUid;
  String expiresAt;
  unsigned long lastRefreshAt = 0;
  const bool hasStoredCode = snapshotCachedQr(storedCode, doorUid, expiresAt, lastRefreshAt);

  appendLog("Scanned QR: " + candidateCode);

  if (!hasStoredCode || storedCode.length() != CODE_LEN) {
    appendLog("Access denied: cached QR is not ready");
    return;
  }

  if (candidateCode == storedCode) {
    appendLog("Access granted: QR matched");
    openLock("scanner");
    return;
  }

  appendLog("Access denied: QR mismatch");
}

void readFromScanner() {
  while (g_scannerSerial.available()) {
    const char ch = static_cast<char>(g_scannerSerial.read());

    if (SCANNER_DEBUG_LOG) {
      String debugMessage = "Scanner byte: ";
      if (ch >= 32 && ch <= 126) {
        debugMessage += "'";
        debugMessage += ch;
        debugMessage += "'";
      } else if (ch == '\r') {
        debugMessage += "\\r";
      } else if (ch == '\n') {
        debugMessage += "\\n";
      } else {
        debugMessage += "0x";
        if (static_cast<uint8_t>(ch) < 16) {
          debugMessage += "0";
        }
        debugMessage += String(static_cast<uint8_t>(ch), HEX);
      }
      appendLog(debugMessage);
    }

    if (ch >= '0' && ch <= '9') {
      g_scannerCode += ch;
      if (g_scannerCode.length() > CODE_LEN) {
        g_scannerCode.remove(0, g_scannerCode.length() - CODE_LEN);
      }
      if (g_scannerCode.length() == CODE_LEN) {
        checkScannerCode(g_scannerCode);
        g_scannerCode = "";
      }
      continue;
    }

    if (ch == '\n' || ch == '\r') {
      if (g_scannerCode.length() == CODE_LEN) {
        checkScannerCode(g_scannerCode);
      } else if (g_scannerCode.length() > 0) {
        appendLog("Scanner frame discarded: expected 11 digits, got " + String(g_scannerCode.length()));
      }
      g_scannerCode = "";
      continue;
    }

    if (g_scannerCode.length() > 0) {
      appendLog("Scanner frame reset on unexpected byte");
      g_scannerCode = "";
    }
  }
}

void controlTask(void *parameter) {
  // Core 0 keeps the QR scanner, presence sensor, relay timing and camera UART reactive.
  appendLog("Control task started on core " + String(xPortGetCoreID()));

  for (;;) {
    serviceTriggerInput();
    readFromAuxController();
    readFromScanner();
    closeLockIfNeeded();
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

void serviceNetworkLoop() {
  // The default Arduino loop runs on the other core and handles Wi-Fi, HTTP and QR cache refresh.
  if (!g_networkLoopLogged) {
    appendLog("Network loop running on core " + String(xPortGetCoreID()));
    g_networkLoopLogged = true;
    beginWifiConnect();
  }

  serviceSerialCommands();
  serviceWifiConnection();

  // if (g_httpServerStarted) {
  //   g_server.handleClient();
  // }

  if (isWifiConnected()) {
    String code;
    String doorUid;
    String expiresAt;
    const unsigned long now = millis();
    unsigned long lastRefreshAt = 0;
    const bool hasQr = snapshotCachedQr(code, doorUid, expiresAt, lastRefreshAt);
    const bool retryWindowElapsed = now - g_lastQrAttemptAt >= QR_RETRY_INTERVAL_MS;

    const bool networkBusy =
        g_cameraAwaitingResult ||
        isLockActive() ||
        (now - g_lastTriggerAt < 10000);

    if (!networkBusy) {
      if ((!hasQr && retryWindowElapsed) || (hasQr && now - lastRefreshAt >= QR_REFRESH_INTERVAL_MS)) {
        fetchQrCodeFromServer();
      }
    }
  }

  renderDefaultLcdState();
}
}  // namespace

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(100);

  g_bootMillis = millis();
  g_stateMutex = xSemaphoreCreateMutex();
  g_logMutex = xSemaphoreCreateMutex();

  // The distance sensor is treated as active-high. Keep the line stable at LOW
  // when the sensor is disconnected or idle so we do not trigger on floating noise.
  pinMode(TRIGGER_PIN, INPUT_PULLDOWN);
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);

  g_scannerSerial.begin(SCANNER_BAUD, SERIAL_8N1, SCANNER_RX_PIN, SCANNER_TX_PIN);
  g_auxControllerSerial.begin(AUX_CONTROLLER_BAUD, SERIAL_8N1, AUX_CONTROLLER_RX_PIN, AUX_CONTROLLER_TX_PIN);

  WiFi.persistent(false);
  WiFi.setSleep(false);
  WiFi.mode(WIFI_OFF);
  delay(100);

  initLcd();
  loadConfig();

  appendLog("SmartLocker ESP32 dual-core QR lock booting");
  setLocalNetworkStatus("ESP: booting");
  setAuxNetworkStatus("CAM: unknown");
  appendLog("Scanner UART2 on RX=" + String(SCANNER_RX_PIN) + " TX=" + String(SCANNER_TX_PIN));
  appendLog("Aux UART1 on RX=" + String(AUX_CONTROLLER_RX_PIN) + " TX=" + String(AUX_CONTROLLER_TX_PIN));
  appendLog("Trigger input on pin " + String(TRIGGER_PIN));
  appendLog("Relay on pin " + String(RELAY_PIN));
  appendLog("LCD I2C on SDA=" + String(LCD_SDA_PIN) + " SCL=" + String(LCD_SCL_PIN));

  xTaskCreatePinnedToCore(controlTask, "sl-control", CONTROL_TASK_STACK, nullptr, CONTROL_TASK_PRIORITY, &g_controlTaskHandle, CONTROL_TASK_CORE);
}

void loop() {
  serviceNetworkLoop();
  delay(20);
}
