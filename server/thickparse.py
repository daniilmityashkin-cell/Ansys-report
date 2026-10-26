"""Толщины поясов из документа заказчика: таблица «пояс - толщина» (xlsx, docx, вставленный из Excel текст) или фраза вида
«с первого по второй – 16,0 мм; с третьего по четвёртый – 15,0 мм». Ничего не придумывает: если пояса не покрыты полностью или значения
неправдоподобны, возвращает понятную ошибку, а решение остаётся за пользователем (результат всегда показывается для проверки)."""
from __future__ import annotations

import io
import re

ORD = [("одиннадцат", 11), ("двенадцат", 12), ("тринадцат", 13), ("четырнадцат", 14), ("пятнадцат", 15), ("шестнадцат", 16), ("семнадцат", 17),
       ("восемнадцат", 18), ("девятнадцат", 19), ("двадцат", 20), ("перв", 1), ("втор", 2), ("трет", 3), ("четв", 4), ("пят", 5), ("шест", 6),
       ("седьм", 7), ("восьм", 8), ("девят", 9), ("десят", 10)]
ROMAN = {"I": 1, "V": 5, "X": 10}
NUM = r"\d+(?:[.,]\d+)?"
TOK = r"(?:\d{1,2}|[IVXІ]{1,5}|[А-Яа-яЁё]{4,16})"            # номер пояса: цифры, римские цифры или порядковое слово
MIN_T, MAX_T = 2.0, 80.0                                        # правдоподобная толщина стенки РВС, мм


def roman(s: str) -> int | None:
    s = s.upper().replace("І", "I")
    if not s or any(ch not in ROMAN for ch in s):
        return None
    total = 0
    for i, ch in enumerate(s):
        v = ROMAN[ch]
        total += -v if i + 1 < len(s) and ROMAN[s[i + 1]] > v else v
    return total if 1 <= total <= 30 else None


def belt_no(tok: str) -> int | None:
    t = tok.strip().lower().replace("ё", "е")
    if t.isdigit():
        n = int(t)
        return n if 1 <= n <= 60 else None
    r = roman(tok)
    if r:
        return r
    for stem, n in ORD:
        if t.startswith(stem):
            return n
    return None


def _f(s) -> float | None:
    try:
        v = float(str(s).replace(",", ".").replace("\xa0", "").strip())
    except (TypeError, ValueError):
        return None
    return v


def _plausible(v) -> bool:
    return v is not None and MIN_T <= v <= MAX_T


def from_phrases(text: str) -> dict[int, float]:
    """Фразы: «с первого по второй – 16,0 мм», «1-2 пояса – 16 мм», «пояс 3: 15 мм», «III пояс – 15,0 мм»."""
    t = re.sub(r"\s+", " ", text.replace("–", "-").replace("—", "-").replace("−", "-"))
    out: dict[int, float] = {}
    pats = [
        (r"с\s+(%s)\s*(?:-?(?:го|й|ого|ого))?\s+по\s+(%s)\s*(?:пояс\w*)?\s*[:=\-]?\s*(%s)\s*мм" % (TOK, TOK, NUM), True),
        (r"(\d{1,2})\s*-\s*(\d{1,2})\s*(?:-?(?:й|е|х))?\s*пояс\w*\s*[:=\-]?\s*(%s)\s*мм" % NUM, True),
        (r"(%s)\s*-?\s*(?:й\s+)?пояс\w*\s*[:=\-]?\s*(%s)\s*мм" % (TOK, NUM), False),
        (r"пояс\w*\s*(?:№|N)?\s*(\d{1,2})\s*[:=\-]\s*(%s)\s*мм" % NUM, False),
    ]
    for pat, rng in pats:
        for m in re.finditer(pat, t, flags=re.IGNORECASE):
            if rng:
                a, b, v = belt_no(m.group(1)), belt_no(m.group(2)), _f(m.group(3))
            else:
                a = b = belt_no(m.group(1))
                v = _f(m.group(2))
            if a is None or b is None or a > b or not _plausible(v):
                continue
            for k in range(a, b + 1):
                out.setdefault(k, v)
    return out


def from_rows(rows: list[list]) -> list[dict]:
    """Таблица (строки ячеек): столбец с номером пояса и один или несколько столбцов толщины («Номинальная», «Расчётная», «Фактическая», «Мин.», «Макс.»).
    Возвращает [{name, belts: {номер: толщина}}] по каждому столбцу толщины."""
    rows = [[("" if c is None else str(c).strip()) for c in r] for r in rows]
    found: list[dict] = []
    for hi, hdr in enumerate(rows):
        cols = [j for j, c in enumerate(hdr) if "толщ" in c.lower()]
        if not cols or sum(1 for c in hdr if c) < 2:                    # заголовок таблицы («Таблица 2 – Толщина элементов») из одной ячейки - не шапка столбцов
            continue
        bcol = next((j for j, c in enumerate(hdr) if "пояс" in c.lower() and "толщ" not in c.lower()), None)
        data = []
        for r in rows[hi + 1:hi + 80]:
            first = next((c for c in r if c), "")
            tok = (r[bcol] if bcol is not None and bcol < len(r) else first)
            m = re.match(r"^\s*(%s)\s*(?:-?\s*й)?\s*(?:пояс\w*)?\s*$" % TOK, tok, flags=re.IGNORECASE) or re.match(r"^\s*пояс\w*\s*(?:№|N)?\s*(\d{1,2})\s*$", tok, flags=re.IGNORECASE)
            if not m or belt_no(m.group(1)) is None:
                if data:
                    break
                continue
            data.append((belt_no(m.group(1)), r))
        if len(data) < 2:
            continue
        # столбцы толщины в строках данных: по заголовку, а если заголовок объединённый - по порядку числовых ячеек после номера пояса
        for ci, j in enumerate(cols):
            belts = {}
            for n, r in data:
                v = _f(r[j]) if j < len(r) else None
                if v is None:
                    nums = [x for x in (_f(c) for c in r[1:]) if x is not None]
                    v = nums[ci] if ci < len(nums) else None
                if _plausible(v):
                    belts[n] = v
            if len(belts) >= 2:
                found.append({"name": re.sub(r"\s+", " ", hdr[j]).strip(" ,") or "толщина", "belts": belts})
        if found:
            break
    return found


def _text_rows(text: str) -> list[list[str]]:
    return [re.split(r"\t|;|\s{2,}|\|", ln.strip()) for ln in text.splitlines() if ln.strip()]


def _complete(belts: dict[int, float]) -> list[float] | None:
    if not belts:
        return None
    n = max(belts)
    return [belts[k] for k in range(1, n + 1)] if all(k in belts for k in range(1, n + 1)) else None


def parse_document(text: str = "", tables: list[list[list]] | None = None, n_belts: int | None = None) -> dict:
    """Возвращает {columns: [{name, values}], how, warnings}. Вариантов может быть несколько (номинальная/расчётная/мин./макс.) - выбирает пользователь."""
    cands: list[tuple[str, str, dict]] = []
    for rows in (tables or []) + ([_text_rows(text)] if text.strip() else []):
        for col in from_rows(rows):
            cands.append(("таблица", col["name"], col["belts"]))
    if text.strip():
        ph = from_phrases(text)
        if ph:
            cands.append(("текст", "по фразам документа", ph))
    cols, warn = [], []
    for how, name, belts in cands:
        vals = _complete(belts)
        if vals is None:
            warn.append(f"«{name}»: найдены не все пояса подряд ({sorted(belts)}), столбец пропущен.")
            continue
        if n_belts and len(vals) != n_belts:
            warn.append(f"«{name}»: в документе {len(vals)} поясов, а в замерах {n_belts}.")
            continue
        if not any(c["values"] == vals and c["name"] == name for c in cols):
            cols.append({"name": name, "how": how, "values": vals})
    if not cols:
        raise ValueError("Толщины поясов в документе не найдены" + (": " + " ".join(warn) if warn else "") +
                         ". Нужна таблица «пояс — толщина» или фраза вида «с первого по второй — 16,0 мм». Введите толщины вручную.")
    return {"columns": cols, "warnings": warn}


def read_file(name: str, raw: bytes) -> tuple[str, list[list[list]]]:
    """Текст и таблицы из xlsx / docx / txt / csv."""
    low = name.lower()
    if low.endswith(".xlsx"):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        tables = [[list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets]
        wb.close()
        return "", tables
    if low.endswith(".docx"):
        import docx
        d = docx.Document(io.BytesIO(raw))
        tables = [[[c.text for c in row.cells] for row in t.rows] for t in d.tables]
        return "\n".join(p.text for p in d.paragraphs), tables
    if low.endswith((".txt", ".csv")):
        for enc in ("utf-8-sig", "cp1251"):
            try:
                return raw.decode(enc), []
            except UnicodeDecodeError:
                continue
    raise ValueError("Поддерживаются файлы .xlsx, .docx и .txt. Из PDF скопируйте таблицу и вставьте текстом.")
