#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

#include <SPI.h>
#include <MFRC522.h>

/*
 * ==================================================
 * 1. Wi-Fi 및 FastAPI 설정
 * ==================================================
 */

// ESP32가 접속할 2.4GHz Wi-Fi 정보
const char* WIFI_SSID = "YOUR_2_4GHZ_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

/*
 * MacBook의 로컬 IP를 사용해야 함.
 */
const char* API_BASE_URL = "http://<MACBOOK_LOCAL_IP>:8000";

const char* RECEIVER_ID =
  "grandma_001";

/*
 * ==================================================
 * 2. MFRC522 핀 설정
 * ==================================================
 */

constexpr uint8_t RFID_SS_PIN = 5;
constexpr uint8_t RFID_RST_PIN = 22;

constexpr uint8_t RFID_SCK_PIN = 18;
constexpr uint8_t RFID_MISO_PIN = 19;
constexpr uint8_t RFID_MOSI_PIN = 23;

MFRC522 rfid(
  RFID_SS_PIN,
  RFID_RST_PIN
);

/*
 * ==================================================
 * 3. 버튼 핀 설정
 * ==================================================
 */

constexpr uint8_t PREVIOUS_BUTTON_PIN = 32;
constexpr uint8_t NEXT_BUTTON_PIN = 33;

/*
 * 버튼 떨림 방지 시간
 */
constexpr unsigned long DEBOUNCE_MS = 180;

unsigned long lastPreviousButtonTime = 0;
unsigned long lastNextButtonTime = 0;

/*
 * ==================================================
 * 4. 메시지 저장 설정
 * ==================================================
 */

/*
 * 읽지 않은 메시지를 최대 30개까지 저장함.
 */
constexpr int MAX_MESSAGES = 30;

String messageIds[MAX_MESSAGES];
String senderIds[MAX_MESSAGES];
String receiverIds[MAX_MESSAGES];
String originalTexts[MAX_MESSAGES];
String translatedTexts[MAX_MESSAGES];
String createdAts[MAX_MESSAGES];

int messageCount = 0;
int currentMessageIndex = -1;

/*
 * RFID 태그가 정상적으로 처리된 뒤 true가 됨.
 */
bool cardActivated = false;

/*
 * ==================================================
 * 5. RFID 중복 인식 방지
 * ==================================================
 */

String lastUid = "";

unsigned long lastTagTime = 0;

constexpr unsigned long TAG_COOLDOWN_MS = 2500;

/*
 * ==================================================
 * 6. RFID UID를 문자열로 변환
 * ==================================================
 */

String getUidString() {
  String uid = "";

  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) {
      uid += "0";
    }

    uid += String(
      rfid.uid.uidByte[i],
      HEX
    );

    if (i < rfid.uid.size - 1) {
      uid += ":";
    }
  }

  uid.toUpperCase();

  return uid;
}

/*
 * ==================================================
 * 7. Wi-Fi 연결
 * ==================================================
 */

void connectWiFi() {
  Serial.println();
  Serial.print("Wi-Fi 연결 시작: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);

  WiFi.begin(
    WIFI_SSID,
    WIFI_PASSWORD
  );

  unsigned long startedAt = millis();

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");

    if (millis() - startedAt > 20000) {
      Serial.println();
      Serial.println("Wi-Fi 연결 시간 초과");

      return;
    }
  }

  Serial.println();
  Serial.println("Wi-Fi 연결 완료");

  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.localIP());

  Serial.print("Wi-Fi 신호 세기: ");
  Serial.print(WiFi.RSSI());
  Serial.println(" dBm");
}

bool ensureWiFiConnected() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  Serial.println();
  Serial.println(
    "Wi-Fi 연결이 끊어져 재연결을 시도합니다."
  );

  WiFi.disconnect();

  connectWiFi();

  return WiFi.status() == WL_CONNECTED;
}

/*
 * ==================================================
 * 8. 저장된 메시지 초기화
 * ==================================================
 */

void clearMessages() {
  for (int i = 0; i < MAX_MESSAGES; i++) {
    messageIds[i] = "";
    senderIds[i] = "";
    receiverIds[i] = "";
    originalTexts[i] = "";
    translatedTexts[i] = "";
    createdAts[i] = "";
  }

  messageCount = 0;
  currentMessageIndex = -1;
}

/*
 * ==================================================
 * 9. 현재 메시지 출력
 * ==================================================
 */

void printCurrentMessage() {
  if (
    messageCount <= 0
    || currentMessageIndex < 0
    || currentMessageIndex >= messageCount
  ) {
    Serial.println();
    Serial.println("출력할 메시지가 없습니다.");

    return;
  }

  Serial.println();
  Serial.println(
    "========================================"
  );

  Serial.print("[메시지 ");
  Serial.print(currentMessageIndex + 1);
  Serial.print("/");
  Serial.print(messageCount);
  Serial.println("]");

  Serial.print("메시지 ID: ");
  Serial.println(
    messageIds[currentMessageIndex]
  );

  Serial.print("보낸 사람: ");
  Serial.println(
    senderIds[currentMessageIndex]
  );

  Serial.print("받는 사람: ");
  Serial.println(
    receiverIds[currentMessageIndex]
  );

  Serial.print("원문: ");
  Serial.println(
    originalTexts[currentMessageIndex]
  );

  Serial.print("통역문: ");
  Serial.println(
    translatedTexts[currentMessageIndex]
  );

  Serial.print("전송 시각: ");
  Serial.println(
    createdAts[currentMessageIndex]
  );

  Serial.println(
    "========================================"
  );
}

/*
 * ==================================================
 * 10. JSON 메시지 배열 저장
 * ==================================================
 */

void saveMessagesFromArray(
  JsonArrayConst messages
) {
  clearMessages();

  for (JsonObjectConst message : messages) {
    if (messageCount >= MAX_MESSAGES) {
      Serial.print("최대 ");
      Serial.print(MAX_MESSAGES);
      Serial.println(
        "개의 메시지만 저장합니다."
      );

      break;
    }

    messageIds[messageCount] =
      message["message_id"] | "";

    senderIds[messageCount] =
      message["sender_id"] | "";

    receiverIds[messageCount] =
      message["receiver_id"] | "";

    originalTexts[messageCount] =
      message["original_text"] | "";

    translatedTexts[messageCount] =
      message["translated_text"] | "";

    createdAts[messageCount] =
      message["created_at"] | "";

    messageCount++;
  }

  if (messageCount > 0) {
    currentMessageIndex = 0;
  }
}

/*
 * ==================================================
 * 11. 읽지 않은 메시지 전체 조회
 * ==================================================
 */

bool fetchUnreadMessages() {
  if (!ensureWiFiConnected()) {
    Serial.println(
      "Wi-Fi 미연결로 메시지를 조회하지 못했습니다."
    );

    return false;
  }

  String url =
    String(API_BASE_URL)
    + "/devices/"
    + RECEIVER_ID
    + "/pending";

  Serial.println();
  Serial.println(
    "읽지 않은 메시지를 조회합니다."
  );

  Serial.print("요청 URL: ");
  Serial.println(url);

  WiFiClient client;
  HTTPClient http;

  if (!http.begin(client, url)) {
    Serial.println(
      "HTTP 연결 초기화에 실패했습니다."
    );

    return false;
  }

  http.setConnectTimeout(5000);
  http.setTimeout(15000);

  int statusCode = http.GET();

  Serial.print("HTTP 상태 코드: ");
  Serial.println(statusCode);

  if (statusCode <= 0) {
    Serial.print("HTTP 요청 실패: ");

    Serial.println(
      http.errorToString(statusCode)
    );

    http.end();

    return false;
  }

  String responseBody =
    http.getString();

  http.end();

  if (statusCode != 200) {
    Serial.println(
      "서버가 오류를 반환했습니다."
    );

    Serial.println(responseBody);

    return false;
  }

  JsonDocument document;

  DeserializationError jsonError =
    deserializeJson(
      document,
      responseBody
    );

  if (jsonError) {
    Serial.print("JSON 해석 실패: ");
    Serial.println(jsonError.c_str());

    Serial.println("서버 원본 응답:");
    Serial.println(responseBody);

    return false;
  }

  if (document["messages"].is<JsonArrayConst>()) {
    saveMessagesFromArray(
      document["messages"]
        .as<JsonArrayConst>()
    );
  } else if (document.is<JsonArrayConst>()) {
    saveMessagesFromArray(
      document.as<JsonArrayConst>()
    );
  } else {
    Serial.println(
      "응답에서 messages 배열을 찾지 못했습니다."
    );

    Serial.println("서버 원본 응답:");
    Serial.println(responseBody);

    clearMessages();

    return false;
  }

  Serial.println();
  Serial.print("읽지 않은 메시지 수: ");
  Serial.println(messageCount);

  if (messageCount == 0) {
    Serial.println(
      "현재 읽지 않은 메시지가 없습니다."
    );

    return true;
  }

  /*
   * RFID 태그 직후 첫 번째 메시지를 출력함.
   */
  printCurrentMessage();

  Serial.println();
  Serial.println(
    "이전 또는 다음 버튼을 눌러 메시지를 이동할 수 있습니다."
  );

  return true;
}

/*
 * ==================================================
 * 12. 이전 메시지로 이동
 * ==================================================
 */

void moveToPreviousMessage() {
  if (!cardActivated) {
    Serial.println();
    Serial.println(
      "먼저 RFID 카드를 태그해 주세요."
    );

    return;
  }

  if (messageCount == 0) {
    Serial.println();
    Serial.println(
      "읽지 않은 메시지가 없습니다."
    );

    return;
  }

  if (currentMessageIndex <= 0) {
    Serial.println();
    Serial.println(
      "최초 메시지입니다."
    );

    return;
  }

  currentMessageIndex--;

  Serial.println();
  Serial.println(
    "이전 메시지로 이동합니다."
  );

  printCurrentMessage();
}

/*
 * ==================================================
 * 13. 다음 메시지로 이동
 * ==================================================
 */

void moveToNextMessage() {
  if (!cardActivated) {
    Serial.println();
    Serial.println(
      "먼저 RFID 카드를 태그해 주세요."
    );

    return;
  }

  if (messageCount == 0) {
    Serial.println();
    Serial.println(
      "읽지 않은 메시지가 없습니다."
    );

    return;
  }

  if (
    currentMessageIndex
    >= messageCount - 1
  ) {
    Serial.println();
    Serial.println(
      "마지막 메시지입니다."
    );

    return;
  }

  currentMessageIndex++;

  Serial.println();
  Serial.println(
    "다음 메시지로 이동합니다."
  );

  printCurrentMessage();
}

/*
 * ==================================================
 * 14. 버튼 처리
 * ==================================================
 */

void handleButtons() {
  /*
   * INPUT_PULLUP이므로 버튼을 누르면 LOW가 됨.
   */

  if (
    digitalRead(PREVIOUS_BUTTON_PIN) == LOW
    && millis() - lastPreviousButtonTime
       > DEBOUNCE_MS
  ) {
    lastPreviousButtonTime = millis();

    moveToPreviousMessage();

    /*
     * 버튼에서 손을 뗄 때까지 기다려
     * 한 번 누를 때 한 번만 동작하게 함.
     */
    while (
      digitalRead(PREVIOUS_BUTTON_PIN)
      == LOW
    ) {
      delay(10);
    }
  }

  if (
    digitalRead(NEXT_BUTTON_PIN) == LOW
    && millis() - lastNextButtonTime
       > DEBOUNCE_MS
  ) {
    lastNextButtonTime = millis();

    moveToNextMessage();

    while (
      digitalRead(NEXT_BUTTON_PIN)
      == LOW
    ) {
      delay(10);
    }
  }
}

/*
 * ==================================================
 * 15. RFID 처리
 * ==================================================
 */

void handleRfid() {
  if (!rfid.PICC_IsNewCardPresent()) {
    return;
  }

  if (!rfid.PICC_ReadCardSerial()) {
    return;
  }

  String uid = getUidString();

  unsigned long currentTime = millis();

  if (
    uid == lastUid
    && currentTime - lastTagTime
       < TAG_COOLDOWN_MS
  ) {
    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();

    return;
  }

  lastUid = uid;
  lastTagTime = currentTime;

  Serial.println();
  Serial.println("RFID 태그 감지");

  Serial.print("UID: ");
  Serial.println(uid);

  /*
   * 현재는 어떤 카드든 grandma_001 기기를
   * 활성화하도록 함.
   */
  bool success = fetchUnreadMessages();

  if (success) {
    cardActivated = true;
  } else {
    cardActivated = false;

    Serial.println();
    Serial.println(
      "메시지 조회에 실패하여 버튼을 활성화하지 않았습니다."
    );
  }

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}

/*
 * ==================================================
 * 16. setup
 * ==================================================
 */

void setup() {
  Serial.begin(115200);

  delay(1000);

  Serial.println();
  Serial.println(
    "GrandTalk RFID + 버튼 테스트 시작"
  );

  /*
   * 내부 풀업 저항 사용
   */
  pinMode(
    PREVIOUS_BUTTON_PIN,
    INPUT_PULLUP
  );

  pinMode(
    NEXT_BUTTON_PIN,
    INPUT_PULLUP
  );

  /*
   * RFID SPI 초기화
   */
  SPI.begin(
    RFID_SCK_PIN,
    RFID_MISO_PIN,
    RFID_MOSI_PIN,
    RFID_SS_PIN
  );

  rfid.PCD_Init();

  delay(100);

  rfid.PCD_DumpVersionToSerial();

  /*
   * Wi-Fi 연결
   */
  connectWiFi();

  Serial.println();
  Serial.println(
    "RFID 카드나 태그를 대어 주세요."
  );
}

/*
 * ==================================================
 * 17. loop
 * ==================================================
 */

void loop() {
  handleRfid();
  handleButtons();

  delay(20);
}