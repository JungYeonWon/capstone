"""AI 모듈.

OPENAI_API_KEY 가 있으면 LLM을, 없으면 규칙 기반(동의어 사전 + 유사도)으로 동작한다.
LLM에는 항상 마스킹된 최소 텍스트만 보낸다. 금액·날짜 같은 확정값은 LLM이 만들지 않는다.
"""

import json
import logging
import re
from difflib import SequenceMatcher

from app.core.config import settings
from app.services.masking import mask_text
from app.standard_fields import STANDARD_FIELDS

log = logging.getLogger(__name__)

_NORM = re.compile(r"[\s　·ㆍ:：()\[\]<>{}「」『』\-_/.,*※]")


def _norm(s: str) -> str:
    return _NORM.sub("", s or "").lower()


def _client():
    from openai import OpenAI

    return OpenAI(api_key=settings.OPENAI_API_KEY)


def _chat_json(system: str, user: str, *, response_model=None) -> dict | None:
    if not settings.ai_enabled:
        return None
    try:
        if response_model is not None:
            res = _client().beta.chat.completions.parse(
                model=settings.OPENAI_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format=response_model,
                temperature=0,
            )
            parsed = res.choices[0].message.parsed
            return parsed.model_dump() if parsed is not None else None
        res = _client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return json.loads(res.choices[0].message.content or "{}")
    except Exception as e:  # 네트워크·키 오류 시 규칙 기반으로 폴백
        log.warning("LLM 호출 실패, 규칙 기반으로 대체: %s", type(e).__name__)
        return None


# ---------------------------------------------------------------- 항목명 → 표준 필드 매핑
def rule_match(label: str) -> tuple[str | None, float]:
    """동의어 사전 + 유사도로 표준 필드를 추정."""
    n = _norm(label)
    if not n:
        return None, 0.0
    best_key, best = None, 0.0
    for key, meta in STANDARD_FIELDS.items():
        for cand in [meta["label"], *meta["synonyms"]]:
            c = _norm(cand)
            if not c:
                continue
            if n == c:
                score = 0.95
            elif len(c) >= 2 and (c in n or (len(n) >= 2 and n in c)):
                score = 0.75
            else:
                score = SequenceMatcher(None, n, c).ratio() * 0.8
            if score > best:
                best_key, best = key, score
    return (best_key, round(best, 2)) if best >= 0.55 else (None, round(best, 2))


def map_labels(items: list[dict]) -> tuple[list[dict], dict]:
    """items: [{label, context}] → [{label, field_key, confidence, method}] 와 전송 정보.

    3주차 "AI 의미 분석": 항목명·위치·문맥을 함께 보고 표준 데이터로 연결.
    """
    results = []
    for it in items:
        key, conf = rule_match(it["label"])
        results.append({"label": it["label"], "field_key": key, "confidence": conf, "method": "rule"})

    sent_info = {"ai_used": False, "masked": {}, "sent_chars": 0}
    if not settings.ai_enabled or not items:
        return results, sent_info

    # 최소 전송: 항목명과 짧은 주변 문맥만, 마스킹 후 전송
    lines = []
    total_masked: dict[str, int] = {}
    for i, it in enumerate(items):
        ctx, cnt = mask_text((it.get("context") or "")[:80])
        lab, cnt2 = mask_text(it["label"])
        for d in (cnt, cnt2):
            for k, v in d.items():
                total_masked[k] = total_masked.get(k, 0) + v
        lines.append(f'{i}. 항목명="{lab}" 문맥="{ctx}"')
    field_desc = "\n".join(f"- {k}: {m['label']} (예: {', '.join(m['synonyms'][:4])})" for k, m in STANDARD_FIELDS.items())
    system = (
        "너는 한국 계약·행정서류 양식을 분석하는 도우미다. 양식의 항목명을 의미가 같은 표준 필드 키로 매핑한다. "
        "모양이 아니라 의미로 판단하라. 해당 없으면 null. 반드시 JSON으로만 답하라: "
        '{"mappings":[{"index":0,"field_key":"amount","confidence":0.9}]}'
    )
    user = f"표준 필드 목록:\n{field_desc}\n\n양식 항목:\n" + "\n".join(lines)
    sent_info.update(masked=total_masked, sent_chars=len(user))
    data = _chat_json(system, user)
    if not data:
        return results, sent_info
    sent_info["ai_used"] = True
    for m in data.get("mappings", []):
        try:
            i = int(m["index"])
            key = m.get("field_key")
            if key is not None and key not in STANDARD_FIELDS:
                continue
            if 0 <= i < len(results):
                results[i].update(field_key=key, confidence=round(float(m.get("confidence", 0.8)), 2), method="ai")
        except (KeyError, ValueError, TypeError):
            continue
    return results, sent_info


# ---------------------------------------------------------------- 서류 검색 (요청 의도 분석)
def search_templates(query: str, templates: list) -> list[dict]:
    """'착수신고서 내라는데요' 같은 요청에서 필요한 양식을 찾는다."""
    q = _norm(query)
    scored = []
    for t in templates:
        names = [t.name, *(t.aliases or [])]
        best = 0.0
        for n in names:
            nn = _norm(n)
            if nn and (nn in q or q in nn):
                best = max(best, 1.0 if nn == q else 0.85)
            else:
                best = max(best, SequenceMatcher(None, q, nn).ratio() * 0.7)
        if q and _norm(t.category) in q:
            best = max(best, 0.6)
        if best >= 0.35 or not q:
            scored.append({"template_id": t.id, "score": round(best, 2)})
    scored.sort(key=lambda x: -x["score"])

    if settings.ai_enabled and q and (not scored or scored[0]["score"] < 0.8):
        catalog = "\n".join(f"{t.id}: {t.name} ({', '.join(t.aliases or [])}) - {t.description}" for t in templates)
        masked, _ = mask_text(query)
        data = _chat_json(
            "사용자의 서류 요청 문장을 보고 필요한 양식 id를 관련도 순으로 고른다. JSON: {\"ids\":[1,2]}",
            f"양식 목록:\n{catalog}\n\n요청: {masked}",
        )
        if data and data.get("ids"):
            ai_ids = [int(i) for i in data["ids"] if str(i).isdigit()]
            rest = [s for s in scored if s["template_id"] not in ai_ids]
            scored = [{"template_id": i, "score": 0.9, "ai": True} for i in ai_ids] + rest
    return scored


# ---------------------------------------------------------------- 문장 생성
def generate_work_summary(values: dict) -> tuple[str, bool]:
    """과업 개요 문장 생성. (텍스트, AI사용여부)"""
    title = values.get("contract_title", "")
    desc = values.get("description", "")
    period = values.get("period", "")
    fallback = (
        f"본 과업은 「{title}」의 수행을 목적으로 하며, 주요 내용은 {desc.strip() or '계약서에 명시된 과업'}이다. "
        f"과업은 {period or '계약기간'} 동안 계약 조건에 따라 성실히 수행한다."
    )
    if not settings.ai_enabled:
        return fallback, False
    masked_desc, _ = mask_text(desc[:500])
    data = _chat_json(
        "공공·기업 계약 행정서류의 '과업 개요' 문장을 2~3문장, 개조식이 아닌 공문체로 작성한다. 금액·날짜는 쓰지 않는다. JSON: {\"text\":\"...\"}",
        f"계약명: {title}\n업무내용: {masked_desc}",
    )
    if data and data.get("text"):
        return str(data["text"]).strip(), True
    return fallback, False


def review_text(doc_title: str, text: str) -> list[str]:
    """LLM 문장 검토(선택). 규칙 검증은 validator.py 가 담당."""
    if not settings.ai_enabled:
        return []
    masked, _ = mask_text(text[:3000])
    data = _chat_json(
        "계약 행정서류의 문장을 검토해 어색한 표현, 서로 모순되는 내용, 빠진 필수 내용만 짧게 지적한다. 없으면 빈 배열. JSON: {\"comments\":[\"...\"]}",
        f"서류: {doc_title}\n\n{masked}",
    )
    return [str(c) for c in (data or {}).get("comments", [])][:5]

