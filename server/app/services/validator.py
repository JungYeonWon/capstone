"""작성 결과 검증: 누락·형식 오류·서류 간 불일치 (규칙 기반).

금액·날짜처럼 정답이 정해진 값은 LLM이 아닌 코드로 검증한다.
사용자가 서류별로 값을 직접 고칠 수 있으므로, 수정 이후 서류끼리 어긋난 값을 찾는 게 핵심.
"""

import re
from datetime import date
from fastapi import HTTPException

from app.standard_fields import CONSISTENCY_FIELDS, field_label, korean_amount

_NUM = re.compile(r"[^\d]")
_DATE = re.compile(r"(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
_BIZNO = re.compile(r"^\d{3}-\d{2}-\d{5}$")


def _money(v) -> int | None:
    s = _NUM.sub("", str(v or ""))
    return int(s) if s else None


def _date(v) -> date | None:
    m = _DATE.search(str(v or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _norm(v) -> str:
    return re.sub(r"\s+", "", str(v or ""))


def document_keys(doc) -> tuple[list[str], list[str]]:
    """(서류에서 쓰는 필드 키, 필수 키)"""
    t = doc.template
    if t.kind in ("builtin", "custom"):
        from app.builtin_templates import template_field_keys

        keys = template_field_keys(t.definition)
        return keys, t.definition.get("required", keys)
    keys = [f["field_key"] for f in t.fields if f.get("field_key")]
    return keys, keys


def _issue(severity, type_, message, docs=(), field_key=None):
    return {
        "severity": severity,  # error | warning
        "type": type_,
        "field_key": field_key,
        "field_label": field_label(field_key) if field_key else None,
        "message": message,
        "document_ids": [d.id for d in docs],
        "document_titles": [d.title for d in docs],
    }


def has_value(template, key, value):
    text = str(value or "")
    if template.kind == "custom" and any(section.get("key") == key and section.get("kind") == "table"
                                         for section in template.definition["custom_plan"]["layout"]["sections"]):
        text = text.replace("|", "")
    return bool(text.strip())


def validate(documents: list, master: dict) -> dict:
    """documents: Document 목록(template 로드됨), master: 회사·계약정보 기준값."""
    issues: list[dict] = []

    for d in documents:
        keys, required = document_keys(d)
        v = d.values or {}
        for k in required:
            if not has_value(d.template, k, v.get(k)):
                label = next((f["label"] for f in d.template.fields if f.get("field_key") == k), field_label(k))
                issue = _issue("error", "누락", f"'{label}' 값이 비어 있습니다.", [d], k)
                issue["field_label"] = label
                issues.append(issue)

        if d.template.kind == "uploaded":
            unmapped = [f["label"] for f in d.template.fields if not f.get("field_key")]
            if unmapped:
                issues.append(_issue("warning", "미매핑", f"표준 항목과 연결되지 않은 칸 {len(unmapped)}개: {', '.join(unmapped[:5])}", [d]))

        for key in keys:
            text=str(v.get(key,'') or '')
            if any(marker in text for marker in ('[검토용 제안]','[작성 필요]','[확인 필요]','TODO','미정')):
                issues.append(_issue('warning','검토 필요 문구','검토용 제안 또는 미확정 문구가 남아 있습니다. 근거를 확인하고 문구를 확정하세요.',[d],key))
        if d.template.kind=='custom':
            from app.services.professional_renderer import data_table_rows
            for section in d.template.definition['custom_plan']['layout']['sections']:
                if section['kind']=='table' and str(v.get(section['key'],'')).replace('|','').strip():
                    try:
                        rows=data_table_rows(section,v)
                        if any(any(str(cell).strip() for cell in row) and not all(str(cell).strip() for cell in row) for row in rows):
                            issues.append(_issue('warning','표 빈칸',f"'{section['label']}' 표의 일부 칸이 비어 있습니다.",[d],section['key']))
                    except (ValueError, HTTPException):
                        issues.append(_issue('error','표 형식',f"'{section['label']}' 표의 열 수 또는 행 수를 확인하세요.",[d],section['key']))

        s, e = _date(v.get("start_date")), _date(v.get("end_date"))
        if "start_date" in keys and "end_date" in keys and s and e and s > e:
            issues.append(_issue("error", "날짜 오류", f"착수일({v.get('start_date')})이 완료일({v.get('end_date')})보다 늦습니다.", [d], "start_date"))
        if "period" in keys and v.get("period") and "~" not in str(v.get("period")):
            issues.append(_issue("warning", "형식", "계약기간은 '시작일 ~ 종료일' 형식이어야 합니다.", [d], "period"))

        amt = _money(v.get("amount"))
        for key in ("advance_amount", "payment_amount"):
            claimed = _money(v.get(key))
            if key in keys and claimed is not None and amt is not None and claimed > amt:
                issues.append(_issue("error", "청구금액", "신청·청구금액이 계약금액을 초과합니다.", [d], key))
        for key in ("quote_items", "detail_items"):
            if key in keys and v.get(key):
                from app.services.professional_renderer import parse_items, item_amounts
                items = parse_items(v[key], "", 0)
                total = sum(sum(item_amounts(i)) for i in items)
                if amt is not None and total != amt:
                    issues.append(_issue("error", "내역 합계", f"품목별 금액 합계({total:,}원)가 계약금액({amt:,}원)과 다릅니다.", [d], key))
        if d.template.kind in ("builtin", "custom"):
            issues.append(_issue("warning", "제출 확인", "발주기관 지정 서식·첨부서류·대표자 날인 여부를 확인하세요. 미리보기는 PDF 배치 기준이며 HWPX는 한글에서 최종 확인하세요.", [d]))
        sup, vat = _money(v.get("supply_amount")), _money(v.get("vat"))
        if amt and sup is not None and vat is not None and "supply_amount" in keys and sup + vat != amt:
            issues.append(_issue("error", "금액 계산", f"공급가액({sup:,}) + 부가세({vat:,}) ≠ 합계({amt:,})", [d], "amount"))
        if amt and v.get("amount_korean") and "amount_korean" in keys and _norm(v["amount_korean"]) != _norm(korean_amount(amt)):
            issues.append(_issue("error", "금액 표기", f"한글 금액 '{v['amount_korean']}'이 숫자 금액 {amt:,}원과 다릅니다. (정답: {korean_amount(amt)})", [d], "amount_korean"))

        bn = str(v.get("business_number", "") or "")
        if "business_number" in keys and bn and not _BIZNO.match(bn):
            issues.append(_issue("warning", "형식", f"사업자등록번호 형식(000-00-00000)이 아닙니다: {bn}", [d], "business_number"))

    # 서류 간 교차 검증
    for k in CONSISTENCY_FIELDS:
        groups: dict[str, list] = {}
        for d in documents:
            keys, _ = document_keys(d)
            val = (d.values or {}).get(k)
            if k in keys and str(val or "").strip():
                groups.setdefault(_norm(val), []).append((d, val))
        if len(groups) > 1:
            detail = " / ".join(f"{items[0][1]} ({', '.join(x[0].title for x in items)})" for items in groups.values())
            all_docs = [x[0] for items in groups.values() for x in items]
            issues.append(_issue("error", "서류 간 불일치", f"'{field_label(k)}' 값이 서류마다 다릅니다: {detail}", all_docs, k))
        base = _norm(master.get(k))
        if base:
            diff_docs = [x[0] for key, items in groups.items() if key != base for x in items]
            if diff_docs and len(groups) == 1:
                issues.append(_issue("warning", "계약정보와 다름", f"'{field_label(k)}' 값이 계약 기본정보({master.get(k)})와 다릅니다.", diff_docs, k))

    errors = sum(1 for i in issues if i["severity"] == "error")
    return {
        "summary": {"documents": len(documents), "errors": errors, "warnings": len(issues) - errors, "passed": errors == 0},
        "issues": issues,
    }
