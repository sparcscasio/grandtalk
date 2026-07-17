#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

#include <SPI.h>
#include <MFRC522.h>

/*
 * ==================================================
 * 1. Wi-Fi 설정
 * ==================================================
 *
 * ESP32는 일반적으로 2.4GHz Wi-Fi에 연결해야 함.
 *
 * GitHub에 올릴 코드에는 실제 Wi-Fi 비밀번호를
 * 넣지 않는 것이 안전함.
 */

const char* WIFI_SSID =
  "YOUR_2_4GHZ_WIFI_NAME";

const char* WIFI_PASSWORD =
  "YOUR_WIFI_PASSWORD";

/*
 * ==================================================
 * 2. Render API 설정
 * ==================================================
 *
 * 실제 Render 서비스 주소로 변경함.
 *
 * 예:
 * https://grandtalk-api.onrender.com
 *
 * 끝에 /를 붙이지 않음.
 */

const char* API_BASE_URL =
  "https://grandtalk-api.onrender.com";

/*
 * 메시지를 받을 기기 ID
 */
const char* RECEIVER_ID =
  "grandma_001";

/*
 * ==================================================
 * 3. MFRC522 RFID 핀
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
 * 4. 버튼 핀
 * ==================================================
 */

constexpr uint8_t PREVIOUS_BUTTON_PIN = 32;
constexpr uint8_t NEXT_BUTTON_PIN = 33;

/*
 * 버튼 접점 떨림 방지 시간
 */
constexpr unsigned long DEBOUNCE_MS = 180;

unsigned long lastPreviousButtonTime = 0;
unsigned long lastNextButtonTime = 0;

/*
 * ==================================================
 * 5. 메시지 저장 공간
 * ==================================================
 *
 * 읽지 않은 메시지를 ESP32 메모리에 저장한 뒤
 * 버튼으로 앞뒤 이동함.
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
 * RFID를 태그해 메시지 조회에 성공한 뒤 true가 됨.
 */
bool cardActivated = false;

/*
 * ==================================================
 * 6. RFID 중복 인식 방지
 * ==================================================
 */

String lastUid = "";

unsigned long lastTagTime = 0;

constexpr unsigned long TAG_COOLDOWN_MS = 2500;

/*
 * ==================================================
 * 7. Render 무료 서버 대응 설정
 * ==================================================
 *
 * Render 무료 서버는 일정 시간 사용하지 않으면
 * 정지할 수 있음.
 *
 * 첫 요청에서 서버가 다시 시작되는 동안
 * 시간이 걸릴 수 있으므로 타임아웃을 길게 설정함.
 */

constexpr int HTTP_CONNECT_TIMEOUT_MS = 15000;
constexpr int HTTP_RESPONSE_TIMEOUT_MS = 90000;

/*
 * ==================================================
 * 8. RFID UID를 문자열로 변환
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
 * 9. Wi-Fi 연결
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

    if (millis() - startedAt > 30000) {
      Serial.println();
      Serial.println(
        "Wi-Fi 연결 시간 초과"
      );

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

/*
 * 연결이 끊어졌을 때 다시 연결함.
 */
bool ensureWiFiConnected() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  Serial.println();
  Serial.println(
    "Wi-Fi 연결이 끊어졌습니다."
  );

  Serial.println(
    "Wi-Fi 재연결을 시도합니다."
  );

  WiFi.disconnect();

  delay(500);

  connectWiFi();

  return WiFi.status() == WL_CONNECTED;
}

/*
 * ==================================================
 * 10. HTTPS 클라이언트 설정
 * ==================================================
 *
 * 테스트 단계에서는 setInsecure()를 사용함.
 *
 * 이는 HTTPS 암호화는 사용하지만 서버 인증서를
 * 검증하지 않는 방식임.
 *
 * 시제품 테스트에는 편리하지만 최종 제품에서는
 * 루트 인증서 검증을 적용하는 것이 안전함.
 */

void configureSecureClient(
  WiFiClientSecure& client
) {
  client.setInsecure();

  client.setTimeout(
    HTTP_RESPONSE_TIMEOUT_MS / 1000
  );
}

/*
 * ==================================================
 * 11. 메시지 배열 초기화
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
 * 12. 현재 메시지 출력
 * ==================================================
 */

void printCurrentMessage() {
  if (
    messageCount <= 0
    || currentMessageIndex < 0
    || currentMessageIndex >= messageCount
  ) {
    Serial.println();
    Serial.println(
      "출력할 메시지가 없습니다."
    );

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
 * 13. JSON 메시지 배열 저장
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
 * 14. Render 서버 상태 확인
 * ==================================================
 */

bool checkServerHealth() {
  if (!ensureWiFiConnected()) {
    return false;
  }

  String url =
    String(API_BASE_URL)
    + "/health";

  Serial.println();
  Serial.println(
    "Render 서버 상태를 확인합니다."
  );

  Serial.print("Health URL: ");
  Serial.println(url);

  WiFiClientSecure client;

  configureSecureClient(client);

  HTTPClient http;

  if (!http.begin(client, url)) {
    Serial.println(
      "HTTPS 연결 초기화에 실패했습니다."
    );

    return false;
  }

  http.setConnectTimeout(
    HTTP_CONNECT_TIMEOUT_MS
  );

  http.setTimeout(
    HTTP_RESPONSE_TIMEOUT_MS
  );

  int statusCode = http.GET();

  Serial.print("Health 상태 코드: ");
  Serial.println(statusCode);

  if (statusCode <= 0) {
    Serial.print("Health 요청 실패: ");

    Serial.println(
      http.errorToString(statusCode)
    );

    http.end();

    return false;
  }

  String responseBody =
    http.getString();

  Serial.print("Health 응답: ");
  Serial.println(responseBody);

  http.end();

  return statusCode == 200;
}

/*
 * ==================================================
 * 15. 읽지 않은 메시지 전체 조회
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

  /*
   * Render는 HTTPS이므로
   * WiFiClient가 아니라 WiFiClientSecure를 사용함.
   */
  WiFiClientSecure client;

  configureSecureClient(client);

  HTTPClient http;

  if (!http.begin(client, url)) {
    Serial.println(
      "HTTPS 연결 초기화에 실패했습니다."
    );

    return false;
  }

  http.setConnectTimeout(
    HTTP_CONNECT_TIMEOUT_MS
  );

  http.setTimeout(
    HTTP_RESPONSE_TIMEOUT_MS
  );

  /*
   * 응답 연결을 매번 닫아 메모리와 연결 상태를
   * 정리하도록 함.
   */
  http.setReuse(false);

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
      "서버가 오류 응답을 반환했습니다."
    );

    Serial.println("서버 응답:");

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

    Serial.println(
      jsonError.c_str()
    );

    Serial.println("서버 원본 응답:");

    Serial.println(responseBody);

    return false;
  }

  /*
   * 응답 형태 1:
   *
   * {
   *   "messages": [...]
   * }
   */
  if (
    document["messages"]
      .is<JsonArrayConst>()
  ) {
    saveMessagesFromArray(
      document["messages"]
        .as<JsonArrayConst>()
    );
  }

  /*
   * 응답 형태 2:
   *
   * [...]
   */
  else if (
    document.is<JsonArrayConst>()
  ) {
    saveMessagesFromArray(
      document.as<JsonArrayConst>()
    );
  }

  else {
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
    "이전 또는 다음 버튼으로 메시지를 이동할 수 있습니다."
  );

  return true;
}

/*
 * ==================================================
 * 16. 이전 메시지로 이동
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

    /*
     * 첫 메시지를 다시 출력하고 싶으면
     * 아래 줄의 주석을 제거함.
     */
    // printCurrentMessage();

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
 * 17. 다음 메시지로 이동
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

    /*
     * 마지막 메시지를 다시 출력하고 싶으면
     * 아래 줄의 주석을 제거함.
     */
    // printCurrentMessage();

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
 * 18. 버튼 처리
 * ==================================================
 */

void handleButtons() {
  /*
   * INPUT_PULLUP을 사용하므로:
   *
   * 누르지 않음: HIGH
   * 누름:       LOW
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
 * 19. RFID 처리
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

  Serial.println(
    "RFID 태그 감지"
  );

  Serial.print("UID: ");
  Serial.println(uid);

  Serial.println();

  Serial.println(
    "Render 서버에서 메시지를 불러옵니다."
  );

  /*
   * 현재 단계에서는 어떤 RFID 카드든
   * grandma_001의 메시지를 불러오도록 함.
   */
  bool success =
    fetchUnreadMessages();

  if (success) {
    cardActivated = true;

    Serial.println();

    Serial.println(
      "버튼 기능이 활성화되었습니다."
    );
  } else {
    cardActivated = false;

    Serial.println();

    Serial.println(
      "메시지 조회에 실패했습니다."
    );

    Serial.println(
      "서버 주소와 배포 상태를 확인해 주세요."
    );
  }

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}

/*
 * ==================================================
 * 20. setup
 * ==================================================
 */

void setup() {
  Serial.begin(115200);

  delay(1200);

  Serial.println();

  Serial.println(
    "GrandTalk Render 배포 서버 연결 테스트"
  );

  /*
   * 버튼 내부 풀업 저항 사용
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

  if (WiFi.status() == WL_CONNECTED) {
    /*
     * 부팅 시 Render 서버를 한 번 깨움.
     *
     * 무료 서버가 정지 상태라면 이 요청에서
     * 시간이 다소 걸릴 수 있음.
     */
    checkServerHealth();
  }

  Serial.println();

  Serial.println(
    "RFID 카드나 태그를 대어 주세요."
  );
}

/*
 * ==================================================
 * 21. loop
 * ==================================================
 */

void loop() {
  handleRfid();
  handleButtons();

  delay(20);
}