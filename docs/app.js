"use strict";

/*
 * ==================================================
 * 1. 서버 설정
 * ==================================================
 *
 * config.js에서 아래 형식 중 하나를 사용할 수 있다.
 *
 * window.GRANDTALK_CONFIG = {
 *   API_BASE_URL:
 *     "https://grandtalk-api.onrender.com"
 * };
 *
 * 또는
 *
 * window.API_BASE_URL =
 *   "https://grandtalk-api.onrender.com";
 */

const API_BASE_URL = String(
  window.GRANDTALK_CONFIG?.API_BASE_URL
  || window.API_BASE_URL
  || "https://grandtalk-api.onrender.com"
).replace(/\/+$/, "");


/*
 * ==================================================
 * 2. DOM 요소
 * ==================================================
 */

const sourceText =
  document.getElementById("sourceText");

const senderId =
  document.getElementById("senderId");

const receiverId =
  document.getElementById("receiverId");

const previewBtn =
  document.getElementById("previewBtn");

const clearBtn =
  document.getElementById("clearBtn");

const status =
  document.getElementById("status");

const resultCard =
  document.getElementById("resultCard");

const translatedText =
  document.getElementById("translatedText");

const termList =
  document.getElementById("termList");

const emotionOutput =
  document.getElementById("emotionOutput");

const intentOutput =
  document.getElementById("intentOutput");

const llmBadge =
  document.getElementById("llmBadge");

const sendBtn =
  document.getElementById("sendBtn");

const sendStatus =
  document.getElementById("sendStatus");

const checkBtn =
  document.getElementById("checkBtn");

const pendingOutput =
  document.getElementById("pendingOutput");

const pendingCount =
  document.getElementById("pendingCount");

const successModal =
  document.getElementById("successModal");

const closeSuccessModalBtn =
  document.getElementById(
    "closeSuccessModalBtn"
  );


/*
 * ==================================================
 * 3. 현재 상태
 * ==================================================
 */

let currentTranslation = null;
let isTranslating = false;
let isSending = false;
let isCheckingPending = false;


/*
 * ==================================================
 * 4. 초기값 복원
 * ==================================================
 */

restoreSavedIdentifiers();


/*
 * ==================================================
 * 5. 공통 함수
 * ==================================================
 */

function normalizeText(value) {
  return String(value ?? "").trim();
}


function formatTextList(value) {
  if (value === null || value === undefined) {
    return "";
  }

  if (Array.isArray(value)) {
    return value
      .map((item) => normalizeText(item))
      .filter(Boolean)
      .join(", ");
  }

  if (typeof value === "object") {
    return Object.values(value)
      .map((item) => normalizeText(item))
      .filter(Boolean)
      .join(", ");
  }

  return normalizeText(value);
}


function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}


function escapeAttribute(value) {
  return escapeHtml(value)
    .replaceAll("`", "&#096;");
}


function setStatus(
  element,
  message,
  type = ""
) {
  if (!element) {
    return;
  }

  element.textContent = message;
  element.classList.remove(
    "success",
    "error",
    "loading"
  );

  if (type) {
    element.classList.add(type);
  }
}


function setButtonLoading(
  button,
  loading,
  loadingText,
  normalText
) {
  if (!button) {
    return;
  }

  button.disabled = loading;
  button.textContent =
    loading ? loadingText : normalText;
}


async function parseResponse(response) {
  const contentType =
    response.headers.get("content-type") || "";

  if (
    contentType.includes(
      "application/json"
    )
  ) {
    return response.json();
  }

  const text = await response.text();

  return {
    detail: text || "응답 본문이 없습니다.",
  };
}


async function requestJson(
  url,
  options = {}
) {
  const response = await fetch(
    url,
    options
  );

  const data = await parseResponse(
    response
  );

  if (!response.ok) {
    const message =
      data?.detail
      || data?.message
      || `요청 실패 (${response.status})`;

    throw new Error(
      typeof message === "string"
        ? message
        : JSON.stringify(message)
    );
  }

  return data;
}


function saveIdentifiers() {
  localStorage.setItem(
    "grandtalk.senderId",
    senderId.value.trim()
  );

  localStorage.setItem(
    "grandtalk.receiverId",
    receiverId.value.trim()
  );
}


function restoreSavedIdentifiers() {
  const savedSender =
    localStorage.getItem(
      "grandtalk.senderId"
    );

  const savedReceiver =
    localStorage.getItem(
      "grandtalk.receiverId"
    );

  if (savedSender && senderId) {
    senderId.value = savedSender;
  }

  if (savedReceiver && receiverId) {
    receiverId.value = savedReceiver;
  }
}


function validateCommonFields() {
  const text =
    sourceText.value.trim();

  const sender =
    senderId.value.trim();

  const receiver =
    receiverId.value.trim();

  if (!text) {
    throw new Error(
      "보낼 문장을 입력해 주세요."
    );
  }

  if (!sender) {
    throw new Error(
      "보내는 사람을 입력해 주세요."
    );
  }

  if (!receiver) {
    throw new Error(
      "받는 사람을 입력해 주세요."
    );
  }

  return {
    text,
    sender,
    receiver,
  };
}


/*
 * ==================================================
 * 6. 통역 결과 표시
 * ==================================================
 */

function renderTranslationResult(result) {
  currentTranslation = result;

  const translated =
    normalizeText(result.translated)
    || normalizeText(
      result.translated_text
    )
    || normalizeText(
      result.translated_raw
    )
    || normalizeText(result.original);

  translatedText.value = translated;

  renderDetectedTerms(
    result.detected_terms || []
  );

  const emotion =
    formatTextList(
      result.emotion
      || result.emotions
    );

  const intent =
    formatTextList(
      result.intent
      || result.intents
    );

  emotionOutput.textContent =
    emotion || "분석 결과 없음";

  intentOutput.textContent =
    intent || "분석 결과 없음";

  renderLlmBadge(result);

  resultCard.classList.remove(
    "hidden"
  );

  resultCard.scrollIntoView({
    behavior: "smooth",
    block: "start",
  });
}


function renderDetectedTerms(terms) {
  if (!Array.isArray(terms)) {
    terms = [];
  }

  if (terms.length === 0) {
    termList.innerHTML = `
      <p class="empty-message">
        발견된 신조어가 없습니다.
      </p>
    `;

    return;
  }

  termList.innerHTML = terms
    .map((term) => {
      if (
        typeof term === "string"
      ) {
        return `
          <span class="term-chip">
            ${escapeHtml(term)}
          </span>
        `;
      }

      const source =
        normalizeText(
          term.term
          || term.source
          || term.original
          || term.word
        );

      const meaning =
        normalizeText(
          term.meaning
          || term.translation
          || term.replacement
          || term.description
        );

      if (!source && !meaning) {
        return "";
      }

      if (!meaning) {
        return `
          <span class="term-chip">
            ${escapeHtml(source)}
          </span>
        `;
      }

      return `
        <div class="term-item">
          <strong>
            ${escapeHtml(source)}
          </strong>

          <span>
            ${escapeHtml(meaning)}
          </span>
        </div>
      `;
    })
    .filter(Boolean)
    .join("");
}


function renderLlmBadge(result) {
  const usedLlm =
    result.used_llm
    ?? result.use_llm
    ?? result.llm_used
    ?? false;

  const method =
    normalizeText(
      result.method
      || result.translation_method
    );

  if (usedLlm) {
    llmBadge.textContent =
      method || "AI 통역";

    llmBadge.classList.remove(
      "hidden"
    );

    return;
  }

  if (method) {
    llmBadge.textContent = method;

    llmBadge.classList.remove(
      "hidden"
    );

    return;
  }

  llmBadge.classList.add(
    "hidden"
  );

  llmBadge.textContent = "";
}


/*
 * ==================================================
 * 7. 통역 요청
 * ==================================================
 */

async function handlePreview() {
  if (isTranslating) {
    return;
  }

  let fields;

  try {
    fields = validateCommonFields();
  } catch (error) {
    setStatus(
      status,
      error.message,
      "error"
    );

    return;
  }

  isTranslating = true;

  setStatus(
    status,
    "문장을 통역하고 있습니다.",
    "loading"
  );

  setButtonLoading(
    previewBtn,
    true,
    "통역 중...",
    "통역하기"
  );

  try {
    saveIdentifiers();

    const result = await requestJson(
      `${API_BASE_URL}/translate`,
      {
        method: "POST",
        headers: {
          "Content-Type":
            "application/json",
        },
        body: JSON.stringify({
          text: fields.text,
          sender_id: fields.sender,
          receiver_id: fields.receiver,
          use_llm: true,
        }),
      }
    );

    renderTranslationResult(result);

    setStatus(
      status,
      "통역이 완료되었습니다.",
      "success"
    );

    setStatus(
      sendStatus,
      ""
    );
  } catch (error) {
    console.error(error);

    setStatus(
      status,
      error.message
      || "통역 중 오류가 발생했습니다.",
      "error"
    );
  } finally {
    isTranslating = false;

    setButtonLoading(
      previewBtn,
      false,
      "통역 중...",
      "통역하기"
    );
  }
}


/*
 * ==================================================
 * 8. 메시지 전송
 * ==================================================
 */

async function handleSend() {
  if (isSending) {
    return;
  }

  let fields;

  try {
    fields = validateCommonFields();
  } catch (error) {
    setStatus(
      sendStatus,
      error.message,
      "error"
    );

    return;
  }

  const corrected =
    translatedText.value.trim();

  if (!corrected) {
    setStatus(
      sendStatus,
      "전송할 통역문을 입력해 주세요.",
      "error"
    );

    return;
  }

  isSending = true;

  setStatus(
    sendStatus,
    "조부모 기기로 전송하고 있습니다.",
    "loading"
  );

  setButtonLoading(
    sendBtn,
    true,
    "전송 중...",
    "수정한 문장 전송"
  );

  try {
    saveIdentifiers();

    const result = await requestJson(
      `${API_BASE_URL}/messages`,
      {
        method: "POST",
        headers: {
          "Content-Type":
            "application/json",
        },
        body: JSON.stringify({
          text: fields.text,
          corrected_text: corrected,
          sender_id: fields.sender,
          receiver_id: fields.receiver,
          use_llm: true,
        }),
      }
    );

    const savedMessage =
      result.message || {};

    console.log(
      "저장된 메시지:",
      savedMessage
    );

    setStatus(
      sendStatus,
      "전송이 완료되었습니다.",
      "success"
    );

    showSuccessModal();

    await refreshPendingInbox({
      silent: true,
    });
  } catch (error) {
    console.error(error);

    setStatus(
      sendStatus,
      error.message
      || "메시지 전송에 실패했습니다.",
      "error"
    );
  } finally {
    isSending = false;

    setButtonLoading(
      sendBtn,
      false,
      "전송 중...",
      "수정한 문장 전송"
    );
  }
}


/*
 * ==================================================
 * 9. 대기 메시지 조회
 * ==================================================
 */

async function refreshPendingInbox(
  options = {}
) {
  const silent =
    Boolean(options.silent);

  if (isCheckingPending) {
    return;
  }

  const receiver =
    receiverId.value.trim();

  if (!receiver) {
    pendingCount.classList.add(
      "hidden"
    );

    pendingOutput.innerHTML = `
      <p class="empty-message error">
        받는 사람을 입력해 주세요.
      </p>
    `;

    return;
  }

  isCheckingPending = true;

  if (!silent) {
    setButtonLoading(
      checkBtn,
      true,
      "조회 중...",
      "현재 수신함 확인"
    );

    pendingOutput.innerHTML = `
      <p class="empty-message">
        메시지를 불러오는 중입니다.
      </p>
    `;
  }

  try {
    saveIdentifiers();

    const result = await requestJson(
      `${API_BASE_URL}/devices/`
      + `${encodeURIComponent(receiver)}`
      + "/pending"
    );

    renderPendingMessages(
      result.messages || []
    );
  } catch (error) {
    console.error(error);

    pendingCount.classList.add(
      "hidden"
    );

    pendingOutput.innerHTML = `
      <p class="empty-message error">
        ${escapeHtml(
          error.message
          || "수신함 조회에 실패했습니다."
        )}
      </p>
    `;
  } finally {
    isCheckingPending = false;

    if (!silent) {
      setButtonLoading(
        checkBtn,
        false,
        "조회 중...",
        "현재 수신함 확인"
      );
    }
  }
}


function renderPendingMessages(messages) {
  if (!Array.isArray(messages)) {
    messages = [];
  }

  pendingCount.textContent =
    `${messages.length}개`;

  pendingCount.classList.toggle(
    "hidden",
    messages.length === 0
  );

  if (messages.length === 0) {
    pendingOutput.innerHTML = `
      <p class="empty-message">
        조회된 읽지 않은 메시지가 없습니다.
      </p>
    `;

    return;
  }

  pendingOutput.innerHTML = messages
    .map((message, index) => {
      const emotion =
        formatTextList(
          message.emotion
          || message.emotions
        )
        || "분석 결과 없음";

      const intent =
        formatTextList(
          message.intent
          || message.intents
        )
        || "분석 결과 없음";

      const messageId =
        normalizeText(
          message.message_id
        );

      const audioUrl =
        normalizeText(
          message.audio_url
        )
        || (
          `${API_BASE_URL}/messages/`
          + `${encodeURIComponent(
            messageId
          )}/audio`
        );

      const createdAt =
        formatDateTime(
          message.created_at
        );

      return `
        <article class="message-item">
          <div class="message-meta">
            <strong>
              메시지 ${index + 1}
            </strong>

            <span class="unread-label">
              읽지 않음
            </span>
          </div>

          <dl class="message-details">
            <div>
              <dt>보낸 사람</dt>

              <dd>
                ${escapeHtml(
                  message.sender_id || "-"
                )}
              </dd>
            </div>

            <div>
              <dt>도착 시간</dt>

              <dd>
                ${escapeHtml(
                  createdAt || "-"
                )}
              </dd>
            </div>

            <div>
              <dt>원문</dt>

              <dd>
                ${escapeHtml(
                  message.original_text || "-"
                )}
              </dd>
            </div>

            <div>
              <dt>통역문</dt>

              <dd>
                ${escapeHtml(
                  message.translated_text
                  || message.translated_raw
                  || "-"
                )}
              </dd>
            </div>

            <div>
              <dt>감정</dt>

              <dd>
                ${escapeHtml(emotion)}
              </dd>
            </div>

            <div>
              <dt>의도</dt>

              <dd>
                ${escapeHtml(intent)}
              </dd>
            </div>
          </dl>

          <div class="message-audio">
            <p class="analysis-label">
              TTS 미리 듣기
            </p>

            <audio
              controls
              preload="none"
              src="${escapeAttribute(
                audioUrl
              )}"
            >
              오디오를 재생할 수 없습니다.
            </audio>
          </div>
        </article>
      `;
    })
    .join("");
}


function formatDateTime(value) {
  const raw = normalizeText(value);

  if (!raw) {
    return "";
  }

  const date = new Date(raw);

  if (
    Number.isNaN(date.getTime())
  ) {
    return raw;
  }

  return new Intl.DateTimeFormat(
    "ko-KR",
    {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }
  ).format(date);
}


/*
 * ==================================================
 * 10. 초기화
 * ==================================================
 */

function handleClear() {
  sourceText.value = "";
  translatedText.value = "";

  currentTranslation = null;

  termList.innerHTML = "";

  emotionOutput.textContent =
    "분석 결과 없음";

  intentOutput.textContent =
    "분석 결과 없음";

  llmBadge.textContent = "";
  llmBadge.classList.add(
    "hidden"
  );

  resultCard.classList.add(
    "hidden"
  );

  setStatus(status, "");
  setStatus(sendStatus, "");

  sourceText.focus();
}


/*
 * ==================================================
 * 11. 성공 모달
 * ==================================================
 */

function showSuccessModal() {
  successModal.classList.remove(
    "hidden"
  );

  document.body.classList.add(
    "modal-open"
  );

  closeSuccessModalBtn.focus();
}


function closeSuccessModal() {
  successModal.classList.add(
    "hidden"
  );

  document.body.classList.remove(
    "modal-open"
  );

  sendBtn.focus();
}


/*
 * ==================================================
 * 12. 이벤트 연결
 * ==================================================
 */

previewBtn.addEventListener(
  "click",
  handlePreview
);


sendBtn.addEventListener(
  "click",
  handleSend
);


clearBtn.addEventListener(
  "click",
  handleClear
);


checkBtn.addEventListener(
  "click",
  () => {
    refreshPendingInbox();
  }
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
      event.key === "Escape"
      && !successModal.classList.contains(
        "hidden"
      )
    ) {
      closeSuccessModal();
    }

    if (
      event.key === "Enter"
      && (
        event.ctrlKey
        || event.metaKey
      )
      && document.activeElement
         === sourceText
    ) {
      handlePreview();
    }
  }
);


senderId.addEventListener(
  "change",
  saveIdentifiers
);


receiverId.addEventListener(
  "change",
  saveIdentifiers
);


/*
 * ==================================================
 * 13. 시작 상태
 * ==================================================
 */

setStatus(status, "");
setStatus(sendStatus, "");