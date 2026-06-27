"""Парсинг PDF-чека и проверка перевода на нужную сумму (BOT_PLAN.md §5).

Извлекаем текстовый слой через pdfplumber, ищем сумму и признаки успешного
перевода, формируем fingerprint (для защиты от повторного использования чека).

ВАЖНО (открытый вопрос §9.3 плана): набор признаков «валидного чека» —
сумма/получатель/статус — зависит от твоего банка. Подстрой константы ниже.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

import pdfplumber

log = logging.getLogger(__name__)

# Признаки успешного перевода (расширь под свой банк/платёжку)
SUCCESS_MARKERS = (
    "успешно",
    "выполнен",
    "completed",
    "success",
    "оплата",
    "перевод",
    "получатель",
    "чек по операции",
)


@dataclass
class ReceiptResult:
    ok: bool
    amount: float | None
    fingerprint: str | None
    reason: str = ""


def _extract_text(pdf_path: str) -> str:
    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _find_amounts(text: str) -> list[float]:
    """Находит денежные суммы вида 200, 200.00, 200,00, 1 200,00 ₽/руб/RUB."""
    amounts: list[float] = []
    pattern = re.compile(
        r"(\d[\d\s ]*[.,]?\d*)\s*(?:₽|руб|р\.|rub)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        raw = m.group(1).replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            amounts.append(float(raw))
        except ValueError:
            continue
    return amounts


def verify_receipt(pdf_path: str, expected_rub: int) -> ReceiptResult:
    """Проверяет PDF-чек: текстовый слой, нужная сумма, признаки перевода."""
    try:
        text = _extract_text(pdf_path)
    except Exception as e:  # noqa: BLE001
        log.warning("PDF parse error: %s", e)
        return ReceiptResult(False, None, None, "Не удалось прочитать PDF")

    if not text.strip():
        # Возможно скан-картинка без текстового слоя — нужен OCR (резерв из плана).
        return ReceiptResult(False, None, None, "Пустой текст (нужен OCR-чек)")

    return analyze_text(text, expected_rub)


def analyze_text(text: str, expected_rub: int) -> ReceiptResult:
    """Анализ уже извлечённого текста чека (вынесено отдельно для самотеста)."""
    low = text.lower()
    has_marker = any(mk in low for mk in SUCCESS_MARKERS)
    amounts = _find_amounts(text)

    # fingerprint: предпочтительно номер операции; иначе — хэш всего текста
    op = re.search(r"(?:чек|операц\w*|документ|receipt|id)\D{0,5}([0-9]{6,})", low)
    if op:
        fingerprint = "op:" + op.group(1)
    else:
        fingerprint = "sha:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]

    amount_ok = any(abs(a - expected_rub) < 0.01 for a in amounts)

    if amount_ok and has_marker:
        matched = next(a for a in amounts if abs(a - expected_rub) < 0.01)
        return ReceiptResult(True, matched, fingerprint)

    reason = []
    if not amount_ok:
        reason.append(f"сумма {expected_rub} не найдена (нашёл: {amounts or '—'})")
    if not has_marker:
        reason.append("нет признаков успешного перевода")
    return ReceiptResult(False, None, fingerprint, "; ".join(reason))
