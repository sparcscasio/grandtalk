"use strict";

/*
 * config.js에서 설정한 값을 사용함.
 *
 * 예:
 *
 * window.GRANDTALK_CONFIG = {
 *   API_BASE_URL: "http://127.0.0.1:8000",
 *   DEFAULT_SENDER_ID: "grandchild_001",
 *   DEFAULT_RECEIVER_ID: "grandma_001"
 * };
 */

const config = window.GRANDTALK_CONFIG ?? {};

const API_BASE_URL = String(
  config.API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");

const DEFAULT_SENDER_ID =
  config.DEFAULT_SENDER_ID ?? "grandchild_001";

const DEFAULT_RECEIVER_ID =
  config.DEFAULT_RECEIVER_ID ?? "grandma_001";

/* DOM 요소 */

const sourceText =
  document.getElementById("sourceText");

const translatedText =
  document.getElementById("translatedText");

const senderId =
  document.getElementById("senderId");

const receiverId =
  document.getElementById("receiverId");

const previewBtn =
  document.getElementById("previewBtn");

const clearBtn =
  document.getElementById("clearBtn");

const sendBtn =
  document.getElementById("sendBtn");

const checkBtn =
  document.getElementById("checkBtn");

const statusElement =
  document.getElementById("status");

const sendStatusElement =
  document.getElementById("sendStatus");

const resultCard =
  document.getElementById("resultCard");

const llmBadge =
  document.getElementById("llmBadge");

const termList =
  document.getElementById("termList");

const pendingOutput =
  document.getElementById("pendingOutput");

const successModal =
  document.getElementById("successModal");

const closeSuccessModalBtn =
  document.getElementById(
    "closeSuccessModalBtn"
  );

/* 초기 상태 */

senderId.value = DEFAULT_SENDER_ID;
receiverId.value = DEFAULT_RECEIVER_ID;

/* 공통 함수 */

function setStatus(
  element,
  message,
  isError = false
) {
  element.textContent = message;
  element.classList.toggle(
    "error",
    isError
  );
}

function getErrorMessage(
  data,
  fallback
) {
  if (!data) {
    return fallback;
  }

  if (typeof data.detail === "string") {
    return data.detail;
  }

  if (Array.isArray(data.detail)) {
    return data.detail
      .map((item) => item.msg)
      .filter(Boolean)
      .join(", ");
  }

  if (typeof data.message === "string") {
    return data.message;
  }

  return fallback;
}

async function parseResponse(response) {
  let data = null;

  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    throw new Error(
      getErrorMessage(
        data,
        `요청에 실패했어요. (${response.status})`
      )
    );
  }

  return data;
}

function setButtonLoading(
  button,
  loading,
  loadingText,
  normalText
) {
  button.disabled = loading;
  button.classList.toggle(
    "is-loading",
    loading
  );

  button.textContent = loading
    ? loadingText
    : normalText;
}

function clearResult() {
  translatedText.value = "";
  termList.innerHTML = "";

  llmBadge.textContent = "";
  llmBadge.classList.add("hidden");

  resultCard.classList.add("hidden");

  setStatus(sendStatusElement, "");
}

function resetForm() {
  sourceText.value = "";

  senderId.value =
    DEFAULT_SENDER_ID;

  receiverId.value =
    DEFAULT_RECEIVER_ID;

  clearResult();

  setStatus(statusElement, "");

  sourceText.focus();
}

/* 탐색된 신조어 표시 */

function renderDetectedTerms(terms) {
  termList.innerHTML = "";

  if (!Array.isArray(terms) || terms.length === 0) {
    const emptyChip =
      document.createElement("span");

    emptyChip.className = "term-chip";
    emptyChip.textContent =
      "등록된 신조어가 발견되지 않음";

    termList.appendChild(emptyChip);

    return;
  }

  for (const term of terms) {
    const chip =
      document.createElement("span");

    chip.className = "term-chip";

    const expression =
      term.expression ??
      term.matched_form ??
      "표현";

    const meaning =
      term.meaning ??
      term.translation ??
      "";

    const strong =
      document.createElement("strong");

    strong.textContent = expression;

    chip.appendChild(strong);

    if (meaning) {
      chip.appendChild(
        document.createTextNode(
          ` · ${meaning}`
        )
      );
    }

    termList.appendChild(chip);
  }
}

/* 통역 방식 배지 */

function renderTranslationBadge(data) {
  const llmUsed =
    Boolean(data.llm_used);

  llmBadge.classList.remove("hidden");

  if (llmUsed) {
    llmBadge.textContent = "AI 문장 교정";
  } else {
    llmBadge.textContent = "규칙 기반";
  }
}

/* 전송 완료 팝업 */

function openSuccessModal() {
  successModal.classList.remove("hidden");

  document.body.style.overflow =
    "hidden";

  window.setTimeout(() => {
    closeSuccessModalBtn.focus();
  }, 50);
}

function closeSuccessModal() {
  successModal.classList.add("hidden");

  document.body.style.overflow = "";

  sourceText.focus();
}

/* 통역 미리보기 */

async function previewTranslation() {
  const text =
    sourceText.value.trim();

  const sender =
    senderId.value.trim();

  const receiver =
    receiverId.value.trim();

  if (!text) {
    setStatus(
      statusElement,
      "보낼 문장을 입력해 주세요.",
      true
    );

    sourceText.focus();

    return;
  }

  if (!sender || !receiver) {
    setStatus(
      statusElement,
      "보내는 사람과 받는 사람을 입력해 주세요.",
      true
    );

    return;
  }

  setButtonLoading(
    previewBtn,
    true,
    "통역 중",
    "통역하기"
  );

  clearResult();

  setStatus(
    statusElement,
    "문장을 통역하고 있어요."
  );

  try {
    const response = await fetch(
      `${API_BASE_URL}/translate`,
      {
        method: "POST",

        headers: {
          "Content-Type":
            "application/json"
        },

        body: JSON.stringify({
          text,
          sender_id: sender,
          receiver_id: receiver
        })
      }
    );

    const data =
      await parseResponse(response);

    translatedText.value =
      data.translated ??
      data.translated_rule_based ??
      data.translated_raw ??
      text;

    renderDetectedTerms(
      data.detected_terms
    );

    renderTranslationBadge(data);

    resultCard.classList.remove(
      "hidden"
    );

    setStatus(
      statusElement,
      "통역이 완료되었어요."
    );

    resultCard.scrollIntoView({
      behavior: "smooth",
      block: "start"
    });
  } catch (error) {
    console.error(error);

    setStatus(
      statusElement,
      error instanceof Error
        ? error.message
        : "통역 중 오류가 발생했어요.",
      true
    );
  } finally {
    setButtonLoading(
      previewBtn,
      false,
      "통역 중",
      "통역하기"
    );
  }
}

/* 수정한 통역문 전송 */

async function sendMessage() {
  const originalText =
    sourceText.value.trim();

  const correctedText =
    translatedText.value.trim();

  const sender =
    senderId.value.trim();

  const receiver =
    receiverId.value.trim();

  if (!originalText) {
    setStatus(
      sendStatusElement,
      "보낼 원문이 없습니다.",
      true
    );

    return;
  }

  if (!correctedText) {
    setStatus(
      sendStatusElement,
      "전송할 통역문을 입력해 주세요.",
      true
    );

    translatedText.focus();

    return;
  }

  if (!sender || !receiver) {
    setStatus(
      sendStatusElement,
      "보내는 사람과 받는 사람을 입력해 주세요.",
      true
    );

    return;
  }

  setButtonLoading(
    sendBtn,
    true,
    "전송 중",
    "수정한 문장 전송"
  );

  setStatus(
    sendStatusElement,
    "조부모님의 기기로 전송하고 있어요."
  );

  try {
    const response = await fetch(
      `${API_BASE_URL}/messages`,
      {
        method: "POST",

        headers: {
          "Content-Type":
            "application/json"
        },

        body: JSON.stringify({
          text: originalText,
          sender_id: sender,
          receiver_id: receiver,
          corrected_text: correctedText
        })
      }
    );

    await parseResponse(response);

    /*
     * 전송 성공 후 통역 결과 section을 숨김.
     */
    resultCard.classList.add("hidden");

    /*
     * 입력 문장을 비움.
     * 보내는 사람과 받는 사람은 다음 전송을 위해 유지함.
     */
    sourceText.value = "";
    translatedText.value = "";

    termList.innerHTML = "";

    llmBadge.textContent = "";
    llmBadge.classList.add("hidden");

    setStatus(statusElement, "");
    setStatus(sendStatusElement, "");

    /*
     * 중앙 팝업 표시
     */
    openSuccessModal();
  } catch (error) {
    console.error(error);

    setStatus(
      sendStatusElement,
      error instanceof Error
        ? error.message
        : "메시지 전송 중 오류가 발생했어요.",
      true
    );
  } finally {
    setButtonLoading(
      sendBtn,
      false,
      "전송 중",
      "수정한 문장 전송"
    );
  }
}

/* 기기 수신함 조회 */

async function checkPendingMessages() {
  const receiver =
    receiverId.value.trim();

  if (!receiver) {
    pendingOutput.textContent =
      "받는 사람을 입력해 주세요.";

    return;
  }

  setButtonLoading(
    checkBtn,
    true,
    "조회 중",
    "현재 수신함 확인"
  );

  pendingOutput.textContent =
    "읽지 않은 메시지를 조회하고 있어요.";

  try {
    const response = await fetch(
      `${API_BASE_URL}/devices/${encodeURIComponent(
        receiver
      )}/pending`
    );

    const data =
      await parseResponse(response);

    const messages =
      Array.isArray(data.messages)
        ? data.messages
        : [];

    if (messages.length === 0) {
      pendingOutput.textContent =
        "현재 대기 중인 메시지가 없음.";

      return;
    }

    const output = messages
      .map((message, index) => {
        const createdAt =
          message.created_at
            ? new Date(
                message.created_at
              ).toLocaleString("ko-KR")
            : "시간 정보 없음";

        return [
          `[메시지 ${index + 1}]`,
          `보낸 사람: ${
            message.sender_id ??
            "알 수 없음"
          }`,
          `받는 사람: ${
            message.receiver_id ??
            receiver
          }`,
          `원문: ${
            message.original_text ??
            ""
          }`,
          `통역문: ${
            message.translated_text ??
            ""
          }`,
          `전송 시각: ${createdAt}`
        ].join("\n");
      })
      .join("\n\n");

    pendingOutput.textContent = output;
  } catch (error) {
    console.error(error);

    pendingOutput.textContent =
      error instanceof Error
        ? error.message
        : "수신함 조회 중 오류가 발생했어요.";
  } finally {
    setButtonLoading(
      checkBtn,
      false,
      "조회 중",
      "현재 수신함 확인"
    );
  }
}

/* 이벤트 연결 */

previewBtn.addEventListener(
  "click",
  previewTranslation
);

clearBtn.addEventListener(
  "click",
  resetForm
);

sendBtn.addEventListener(
  "click",
  sendMessage
);

checkBtn.addEventListener(
  "click",
  checkPendingMessages
);

closeSuccessModalBtn.addEventListener(
  "click",
  closeSuccessModal
);

successModal.addEventListener(
  "click",
  (event) => {
    if (event.target === successModal) {
      closeSuccessModal();
    }
  }
);

document.addEventListener(
  "keydown",
  (event) => {
    if (
      event.key === "Escape" &&
      !successModal.classList.contains(
        "hidden"
      )
    ) {
      closeSuccessModal();
    }

    /*
     * 원문 입력창에서 Ctrl+Enter 또는 Command+Enter로 통역함.
     */
    if (
      (event.ctrlKey || event.metaKey) &&
      event.key === "Enter" &&
      document.activeElement === sourceText
    ) {
      previewTranslation();
    }
  }
);

/* 서비스 워커 등록 */

if ("serviceWorker" in navigator) {
  window.addEventListener(
    "load",
    async () => {
      try {
        await navigator.serviceWorker.register(
          "./service-worker.js"
        );
      } catch (error) {
        console.warn(
          "서비스 워커 등록 실패:",
          error
        );
      }
    }
  );
}