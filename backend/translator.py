from __future__ import annotations

import csv
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kiwipiepy import Kiwi

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "korean_slang_dictionary_100_variants_fixed.csv"


def parse_variants(value: Any) -> list[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return []
    return list(dict.fromkeys(v.strip() for v in text.split("|") if v.strip()))


def load_dictionary(path: Path = CSV_PATH) -> list[dict[str, Any]]:
    required = {
        "id", "expression", "variants", "meaning", "translation",
        "emotion", "intent", "example", "warning", "source", "updated_at",
    }
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise RuntimeError("신조어 CSV가 비어 있음.")
    missing = required - set(rows[0])
    if missing:
        raise RuntimeError(f"CSV 필수 열 누락: {sorted(missing)}")

    records: list[dict[str, Any]] = []
    for row in rows:
        cleaned = {k: (v or "").strip() for k, v in row.items()}
        cleaned["variants"] = parse_variants(cleaned.get("variants"))
        records.append(cleaned)
    return records


def normalize_input_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("입력 문장은 문자열이어야 함.")
    text = unicodedata.normalize("NFC", text).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"~{3,}", "~~", text)
    text = re.sub(r"!{3,}", "!!", text)
    text = re.sub(r"\?{3,}", "??", text)
    text = re.sub(r"(ㅋ|ㅎ|ㅠ|ㅜ)\1{2,}", r"\1\1", text)
    return text


@dataclass
class MatchResult:
    start: int
    end: int
    matched_form: str
    record: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.record["id"],
            "start": self.start,
            "end": self.end,
            "matched_form": self.matched_form,
            "expression": self.record["expression"],
            "meaning": self.record["meaning"],
            "translation": self.record["translation"],
            "emotion": self.record["emotion"],
            "intent": self.record["intent"],
            "warning": self.record.get("warning", ""),
        }


class KoreanPostprocessor:
    def __init__(self, kiwi: Kiwi, use_spacing: bool = False):
        self.kiwi = kiwi
        self.use_spacing = use_spacing

    @staticmethod
    def basic_cleanup(text: str) -> str:
        text = unicodedata.normalize("NFC", text).strip()
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s+([,.!?])", r"\1", text)
        text = re.sub(r"([,.!?])(?=[가-힣A-Za-z0-9])", r"\1 ", text)
        return text.strip()

    @staticmethod
    def remove_duplicate_words(text: str) -> str:
        words = text.split()
        if not words:
            return text
        out = [words[0]]
        for word in words[1:]:
            if word != out[-1]:
                out.append(word)
        return " ".join(out)

    @staticmethod
    def apply_rules(text: str) -> str:
        rules = [
            (r"\b정말\s+정말\b", "정말"),
            (r"\b진짜\s+정말\b", "정말"),
            (r"\b정말\s+진짜\b", "정말"),
            (r"\b매우\s+매우\b", "매우"),
            (r"([가-힣]+음)\s*임\b", r"\1"),
            (r"([가-힣]+음)\s*이다\b", r"\1"),
            (r"([가-힣]+함)\s*임\b", r"\1"),
            (r"([가-힣]+함)\s*이다\b", r"\1"),
            (r"([가-힣]+됨)\s*임\b", r"\1"),
            (r"([가-힣]+김)\s*임\b", r"\1"),
            (r"([가-힣]+움)\s*임\b", r"\1"),
            (r"([가-힣]+임)\s*임\b", r"\1"),
            # 흔한 접합 오류
            (r"정신이\s+없음옴\b", "정신이 없었음"),
            (r"재미가\s+없음이었음\b", "재미가 없었음"),
            (r"재미가\s+없음이었어\b", "재미가 없었어"),
            (r"있음이었음\b", "있었음"),
            (r"없음이었음\b", "없었음"),
        ]
        previous = None
        while previous != text:
            previous = text
            for pattern, replacement in rules:
                text = re.sub(pattern, replacement, text)
        return text

    def postprocess(self, text: str) -> str:
        text = self.basic_cleanup(text)
        text = self.remove_duplicate_words(text)
        text = self.apply_rules(text)
        if self.use_spacing:
            try:
                text = self.kiwi.space(text, reset_whitespace=False)
            except Exception:
                pass
        return self.basic_cleanup(self.apply_rules(text))


class LLMRefiner:
    """OpenAI가 설정된 경우에만 문장 문법을 자연스럽게 다듬음."""

    def __init__(self) -> None:
        self.enabled = os.getenv("USE_LLM", "false").lower() == "true"
        self.model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
        self.client = None
        if self.enabled and os.getenv("OPENAI_API_KEY"):
            try:
                from openai import OpenAI
                self.client = OpenAI()
            except Exception:
                self.client = None

    def refine(self, original: str, rule_based: str, terms: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.enabled or self.client is None or not terms:
            return {"used": False, "text": rule_based, "reason": "LLM 비활성화"}

        compact_terms = [
            {"expression": t["expression"], "meaning": t["meaning"], "translation": t["translation"]}
            for t in terms
        ]
        prompt = {
            "original": original,
            "rule_based_translation": rule_based,
            "dictionary_terms": compact_terms,
        }
        instructions = (
            "너는 한국어 문장 교정기다. 신조어 뜻은 dictionary_terms만 신뢰한다. "
            "원문의 사실과 뉘앙스를 유지하고, 조사·어미·시제·문장 호응만 자연스럽게 고친다. "
            "새 정보를 추가하지 말고 한 문장만 출력한다. 설명이나 따옴표를 붙이지 않는다. "
            "'정신이 없음옴', '재미가 없음이었음', '맛있음임' 같은 접합 오류를 자연스럽게 고친다."
        )
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=instructions,
                input=json.dumps(prompt, ensure_ascii=False),
            )
            text = (response.output_text or "").strip()
            if not text:
                raise ValueError("빈 LLM 응답")
            return {"used": True, "text": text, "reason": "LLM 문법 교정 적용"}
        except Exception as exc:
            return {"used": False, "text": rule_based, "reason": f"LLM 실패: {exc}"}


class SlangTranslator:
    def __init__(self, records: list[dict[str, Any]], kiwi: Kiwi, postprocessor: KoreanPostprocessor):
        self.records = records
        self.kiwi = kiwi
        self.postprocessor = postprocessor
        self.llm = LLMRefiner()
        self.search_items = self._build_search_items()

    def _build_search_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for record in self.records:
            forms = [record["expression"], *record.get("variants", [])]
            for form in dict.fromkeys(x.strip() for x in forms if x and x.strip()):
                items.append({"form": form, "record": record})
        items.sort(key=lambda x: (len(x["form"]), x["form"]), reverse=True)
        return items

    @staticmethod
    def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
        return any(start < b and end > a for a, b in spans)

    def find_matches(self, text: str) -> list[MatchResult]:
        matches: list[MatchResult] = []
        spans: list[tuple[int, int]] = []
        for item in self.search_items:
            for found in re.finditer(re.escape(item["form"]), text):
                if self._overlaps(found.start(), found.end(), spans):
                    continue
                matches.append(MatchResult(found.start(), found.end(), found.group(), item["record"]))
                spans.append((found.start(), found.end()))
        return sorted(matches, key=lambda m: m.start)

    @staticmethod
    def select_translation(match: MatchResult) -> str:
        return re.sub(r"\s+", " ", str(match.record.get("translation", "")).strip())

    def replace_matches(self, text: str, matches: list[MatchResult]) -> str:
        out = text
        for match in sorted(matches, key=lambda m: m.start, reverse=True):
            out = out[:match.start] + self.select_translation(match) + out[match.end:]
        return out

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(v for v in values if v))

    def translate(self, text: str, use_llm: bool | None = None) -> dict[str, Any]:
        if not isinstance(text, str):
            return {"success": False, "error_code": "INVALID_TYPE", "message": "문자열을 입력해야 함."}
        normalized = normalize_input_text(text)
        if not normalized:
            return {"success": False, "error_code": "EMPTY_INPUT", "message": "문장을 입력해 주세요."}

        matches = self.find_matches(normalized)
        raw = self.replace_matches(normalized, matches)
        rule_based = self.postprocessor.postprocess(raw)

        detected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for match in matches:
            rid = match.record["id"]
            if rid in seen:
                continue
            seen.add(rid)
            item = match.to_dict()
            item["selected_translation"] = self.select_translation(match)
            detected.append(item)

        original_llm_flag = self.llm.enabled
        if use_llm is not None:
            self.llm.enabled = use_llm
        llm_result = self.llm.refine(normalized, rule_based, detected)
        self.llm.enabled = original_llm_flag

        return {
            "success": True,
            "original": text,
            "normalized": normalized,
            "translated_raw": raw,
            "translated_rule_based": rule_based,
            "translated": llm_result["text"],
            "detected_terms": detected,
            "emotions": self._unique([x["emotion"] for x in detected]) or ["알 수 없음"],
            "intents": self._unique([x["intent"] for x in detected]) or ["알 수 없음"],
            "warnings": self._unique([x["warning"] for x in detected]),
            "has_detected_term": bool(detected),
            "llm_used": llm_result["used"],
            "llm_reason": llm_result["reason"],
        }


records = load_dictionary()
kiwi = Kiwi()
for record in records:
    for form in [record["expression"], *record.get("variants", [])]:
        try:
            kiwi.add_user_word(form, "NNG")
        except Exception:
            pass
postprocessor = KoreanPostprocessor(kiwi=kiwi, use_spacing=False)
translator = SlangTranslator(records=records, kiwi=kiwi, postprocessor=postprocessor)
