#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* API_BASE_URL = "https://YOUR-RENDER-SERVICE.onrender.com";
const char* RECEIVER_ID = "grandma_001";

unsigned long lastPoll = 0;
const unsigned long POLL_INTERVAL_MS = 15000;

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Wi-Fi 연결 중");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWi-Fi 연결 완료");
}

bool markAsRead(const String& messageId) {
  WiFiClientSecure client;
  client.setInsecure(); // 시연용. 실제 운영에서는 CA 인증서 권장.
  HTTPClient https;
  String url = String(API_BASE_URL) + "/messages/read";
  if (!https.begin(client, url)) return false;
  https.addHeader("Content-Type", "application/json");
  JsonDocument doc;
  doc["message_id"] = messageId;
  String body;
  serializeJson(doc, body);
  int code = https.POST(body);
  https.end();
  return code >= 200 && code < 300;
}

void displayMessage(const String& text, const String& emotion) {
  Serial.println("----- 새 메시지 -----");
  Serial.println("감정: " + emotion);
  Serial.println(text);
  // 여기에 TFT 출력 코드를 연결함.
  // 여기에 MAX98357A + TTS 음성 재생 코드를 연결함.
}

void fetchNextMessage() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();

  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient https;
  String url = String(API_BASE_URL) + "/devices/" + RECEIVER_ID + "/next";
  if (!https.begin(client, url)) {
    Serial.println("HTTPS 시작 실패");
    return;
  }

  int code = https.GET();
  if (code != 200) {
    Serial.printf("메시지 조회 실패: %d\n", code);
    https.end();
    return;
  }

  String payload = https.getString();
  https.end();

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, payload);
  if (err) {
    Serial.println("JSON 파싱 실패");
    return;
  }

  bool hasMessage = doc["has_message"] | false;
  if (!hasMessage) return;

  String messageId = doc["message"]["message_id"] | "";
  String translated = doc["message"]["translated_text"] | "";
  String emotion = "알 수 없음";
  if (doc["message"]["emotions"].is<JsonArray>() && doc["message"]["emotions"].size() > 0) {
    emotion = doc["message"]["emotions"][0].as<String>();
  }

  displayMessage(translated, emotion);
  if (messageId.length() > 0 && markAsRead(messageId)) {
    Serial.println("읽음 처리 완료");
  }
}

void setup() {
  Serial.begin(115200);
  connectWiFi();
}

void loop() {
  if (millis() - lastPoll >= POLL_INTERVAL_MS) {
    lastPoll = millis();
    fetchNextMessage();
  }
  delay(100);
}
