#include <ArduinoJson.h>
#include <ESP8266HTTPClient.h>
#include <ESP8266WiFi.h>
#include <WiFiClientSecureBearSSL.h>

namespace {
constexpr char WIFI_SSID[] = "REPLACE_WITH_WIFI_SSID";
constexpr char WIFI_PASSWORD[] = "REPLACE_WITH_WIFI_PASSWORD";
constexpr char QR_URL[] = "http://188.130.251.23/api/v1/locks/qr/current";
constexpr char LOCK_ID[] = "LOCK-REPLACE-ME";
constexpr char LOCK_API_KEY[] = "REPLACE_WITH_LOCK_API_KEY";

constexpr unsigned long QR_REFRESH_INTERVAL_MS = 30000;
constexpr unsigned long WIFI_RETRY_DELAY_MS = 500;
constexpr unsigned long HTTP_TIMEOUT_MS = 10000;
constexpr unsigned long SERIAL_BAUD = 9600;

String g_cachedCode;
String g_cachedDoorUid;
String g_cachedExpiresAt;
unsigned long g_lastRefreshAt = 0;

void printStatus(const String &message) {
  Serial.print("[ESP8266] ");
  Serial.println(message);
}

bool ensureWifiConnected() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  printStatus("Connecting to Wi-Fi");

  while (WiFi.status() != WL_CONNECTED) {
    delay(WIFI_RETRY_DELAY_MS);
    Serial.print(".");
  }

  Serial.println();
  printStatus("Wi-Fi connected");
  Serial.print("[ESP8266] IP: ");
  Serial.println(WiFi.localIP());
  return true;
}

bool fetchQrCodeFromServer() {
  ensureWifiConnected();

  std::unique_ptr<BearSSL::WiFiClientSecure> client(new BearSSL::WiFiClientSecure);
  client->setInsecure();

  HTTPClient http;
  if (!http.begin(*client, QR_URL)) {
    printStatus("HTTP begin failed");
    return false;
  }

  http.setTimeout(HTTP_TIMEOUT_MS);
  http.addHeader("X-Lock-Id", LOCK_ID);
  http.addHeader("X-Lock-Api-Key", LOCK_API_KEY);

  printStatus("Requesting current QR code");
  int statusCode = http.GET();
  if (statusCode <= 0) {
    Serial.print("[ESP8266] Request failed: ");
    Serial.println(statusCode);
    http.end();
    return false;
  }

  String payload = http.getString();
  http.end();

  StaticJsonDocument<768> doc;
  DeserializationError error = deserializeJson(doc, payload);
  if (error) {
    printStatus("Failed to parse server JSON");
    return false;
  }

  const char *code = doc["code"] | "";
  const char *doorUid = doc["door_uid"] | "";
  const char *expiresAt = doc["expires_at"] | "";

  if (code[0] == '\0') {
    printStatus("QR code not found in response");
    return false;
  }

  g_cachedCode = String(code);
  g_cachedDoorUid = String(doorUid);
  g_cachedExpiresAt = String(expiresAt);
  g_lastRefreshAt = millis();

  Serial.print("CODE:");
  Serial.println(g_cachedCode);
  Serial.print("DOOR_UID:");
  Serial.println(g_cachedDoorUid);
  Serial.print("EXPIRES_AT:");
  Serial.println(g_cachedExpiresAt);
  printStatus("Fresh QR cached and sent to Nano");
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

void handleSerialCommand(const String &rawCommand) {
  String cmd = rawCommand;
  cmd.trim();
  if (cmd.isEmpty()) {
    return;
  }

  Serial.print("[ESP8266] CMD: ");
  Serial.println(cmd);

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

  if (cmd == "ping") {
    Serial.println("PONG");
    return;
  }

  Serial.println("ERROR:UNKNOWN_COMMAND");
}
}  // namespace

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(150);
  printStatus("Boot");
  ensureWifiConnected();
  fetchQrCodeFromServer();
  printStatus("Ready. Commands: get-code, refresh-code, ping");
}

void loop() {
  if (millis() - g_lastRefreshAt >= QR_REFRESH_INTERVAL_MS) {
    fetchQrCodeFromServer();
  }

  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    handleSerialCommand(cmd);
  }
}
