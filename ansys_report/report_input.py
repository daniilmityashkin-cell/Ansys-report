"""Данные технического отчёта, которые вводит заказчик до генерации (реквизиты, объект, сталь, нагрузки для Таблицы 1 и раздела 4).
Ничего не придумываем: обязательные поля без значения останавливают сборку отчёта со списком того, что нужно заполнить.
Нормативные коэффициенты (γf, ψ) заполнены значениями ГОСТ Р 58622-2019 / ГОСТ 31385, их можно изменить."""
from __future__ import annotations

import datetime as _dt

# (ключ, подпись, группа, тип: text|num|list, обязательное, значение по умолчанию, подсказка)
FIELDS = [
    ("number", "Номер отчёта", "Реквизиты", "text", True, "", "ТО-019-26"),
    ("year", "Год", "Реквизиты", "num", True, str(_dt.date.today().year), ""),
    ("executor_position", "Должность исполнителя", "Реквизиты", "text", False, "", "Доцент кафедры …"),
    ("executor_name", "Исполнитель (Фамилия И. О.)", "Реквизиты", "text", True, "", ""),
    ("contractor", "Сведения о подрядчике (раздел 1.2)", "Реквизиты", "text", False, "", "Расчёт выполнен …"),
    ("phone", "Телефон подрядчика", "Реквизиты", "text", False, "", "+7…"),

    ("tank_name", "Резервуар (тип)", "Объект", "text", True, "", "РВС-9985"),
    ("tag", "Номер резервуара", "Объект", "text", True, "", "Т-001"),
    ("site", "Объект (площадка)", "Объект", "text", True, "", "Иркутский завод полимеров"),
    ("site_number", "Номер по объекту", "Объект", "text", False, "", "5210-Т-001"),
    ("purpose", "Назначение (предназначен для …)", "Объект", "text", True, "", "хранения технологической воды"),
    ("product", "Наименование хранимого продукта", "Объект", "text", True, "", "Техническая вода"),
    ("hazard_class", "Класс опасности по ГОСТ 31385", "Объект", "text", True, "", "КС-2а"),
    ("kmd", "Источник толщин (проект КМД)", "Объект", "text", False, "", "КМД №238 137 ООО «…»"),
    ("roof_radius", "Радиус сферической крыши, мм", "Объект", "num", True, "", "34200"),

    ("steel_name", "Марка стали", "Сталь", "text", True, "", "09Г2С"),
    ("steel_standard", "Стандарт на сталь", "Сталь", "text", True, "", "ГОСТ 19281-2014"),
    ("steel_density", "Плотность, кг/м³", "Сталь", "num", True, "", "7850"),
    ("steel_e_mpa", "Модуль Юнга, МПа", "Сталь", "num", True, "", "206000"),
    ("steel_poisson", "Коэффициент Пуассона", "Сталь", "num", True, "", "0,3"),
    ("steel_ultimate_mpa", "Предел прочности σв, МПа", "Сталь", "num", True, "", "480"),
    ("steel_yield_mpa", "Предел текучести σт, МПа", "Сталь", "num", True, "", "325"),
    ("elongation_pct", "Относительное удлинение δ, %", "Сталь", "num", True, "", "21"),
    ("steel_thickness_range", "Для толщин стенок, мм", "Сталь", "text", True, "", "9,01-25"),

    ("roof_mass_kg", "Масса крыши (металл) Mкр, кг", "Нагрузки", "num", True, "", "64156"),
    ("roof_equipment_kg", "Массы оборудования и площадок на крыше Mоб, кг (через ;)", "Нагрузки", "list", False, "", "819,5; 5151; 1571,8"),
    ("psi", "Коэффициент сочетания ψ для оборудования", "Нагрузки", "num", True, "0.95", ""),
    ("roof_gf", "γf для веса крыши и оборудования", "Нагрузки", "num", True, "1.05", ""),
    ("load_factor", "γf для теплоизоляции", "Нагрузки", "num", True, "1.3", ""),
    ("overp_gf", "γf для избыточного давления", "Нагрузки", "num", True, "1.2", ""),
    ("roof_ins_kg", "Масса теплоизоляции крыши, кг (0 - нет)", "Нагрузки", "num", True, "", "2080"),
    ("wall_ins_kg", "Масса теплоизоляции стенки, кг (0 - нет)", "Нагрузки", "num", True, "", "4335"),
    ("ins_thickness_mm", "Толщина теплоизоляции, мм", "Нагрузки", "num", False, "", "100"),
    ("snow_kpa", "Нормативный вес снегового покрова, кПа", "Нагрузки", "num", True, "", "1,8"),
    ("snow_gf", "Коэффициент надёжности по снеговой нагрузке", "Нагрузки", "num", True, "1.4", ""),
    ("snow_blowoff", "Учёт сдувания снега с крыши", "Нагрузки", "text", True, "Не учитывается", ""),
    ("wind_kpa", "Расчётное ветровое давление, кПа", "Нагрузки", "num", True, "", "0,3"),
]
KEYS = [f[0] for f in FIELDS]
GROUPS = ["Реквизиты", "Объект", "Сталь", "Нагрузки"]


def _num(v) -> float:
    return float(str(v).replace(",", ".").replace("\xa0", "").replace(" ", ""))


def _nums(v) -> list[float]:
    return [_num(x) for x in str(v or "").replace("\n", ";").split(";") if x.strip()]


def defaults() -> dict:
    return {k: d for k, _, _, _, _, d, _ in FIELDS}


def parse(form: dict) -> tuple[dict, list[str]]:
    """Поля формы (с префиксом r_ или без) → (данные, ошибки формата). Пустые обязательные поля ошибкой не считаются: см. missing()."""
    out, errors = {}, []
    for key, label, _, kind, _, _, _ in FIELDS:
        v = form.get("r_" + key, form.get(key, ""))
        v = "" if v is None else str(v).strip()
        if v and kind == "num":
            try:
                _num(v)
            except ValueError:
                errors.append(f"«{label}»: нужно число.")
        if v and kind == "list":
            try:
                _nums(v)
            except ValueError:
                errors.append(f"«{label}»: числа через точку с запятой.")
        out[key] = v
    if not errors:
        for key, lo, hi in (("steel_poisson", 0.1, 0.5), ("steel_yield_mpa", 100, 1500), ("steel_ultimate_mpa", 100, 2000), ("steel_e_mpa", 50000, 400000),
                            ("steel_density", 5000, 10000), ("psi", 0, 1), ("snow_kpa", 0, 20), ("wind_kpa", 0, 5)):
            if out.get(key) and not lo <= _num(out[key]) <= hi:
                errors.append(f"«{dict((f[0], f[1]) for f in FIELDS)[key]}»: значение {out[key]} вне разумных пределов {lo}…{hi}.")
        if out.get("steel_yield_mpa") and out.get("steel_ultimate_mpa") and _num(out["steel_yield_mpa"]) >= _num(out["steel_ultimate_mpa"]):
            errors.append("Предел текучести должен быть меньше предела прочности.")
    return out, errors


def missing(data: dict | None) -> list[str]:
    """Подписи незаполненных обязательных полей (пустой список - всё заполнено)."""
    data = data or {}
    return [label for key, label, _, _, req, _, _ in FIELDS if req and not str(data.get(key, "")).strip()]


def report_data(data: dict, loads_input: dict | None = None) -> dict:
    """Числа для Таблицы 1, Таблицы 3 и раздела 4 (уходят в project.yaml как report_data)."""
    L = loads_input or {}
    n = lambda k: _num(data[k]) if str(data.get(k, "")).strip() else None
    return {
        "steel": {"name": data.get("steel_name", ""), "standard": data.get("steel_standard", ""), "density": n("steel_density"),
                  "young_modulus_mpa": n("steel_e_mpa"), "poisson": n("steel_poisson"), "ultimate_mpa": n("steel_ultimate_mpa"),
                  "yield_mpa": n("steel_yield_mpa"), "elongation_pct": n("elongation_pct"), "thickness_range": data.get("steel_thickness_range", "")},
        "roof_mass_kg": n("roof_mass_kg"), "roof_equipment_kg": _nums(data.get("roof_equipment_kg")), "psi": n("psi"), "roof_gf": n("roof_gf"),
        "load_factor": n("load_factor"), "overp_gf": n("overp_gf"), "roof_ins_kg": n("roof_ins_kg"), "wall_ins_kg": n("wall_ins_kg"),
        "ins_thickness_mm": n("ins_thickness_mm"), "snow_kpa": n("snow_kpa"), "snow_gf": n("snow_gf"), "snow_blowoff": data.get("snow_blowoff", ""),
        "wind_kpa": n("wind_kpa"), "roof_radius_mm": n("roof_radius"), "hazard_class": data.get("hazard_class", ""), "product": data.get("product", ""),
        "overpressure_kpa": float(L.get("overpressure_pa") or 0) / 1000.0, "terrain": L.get("terrain", ""),
        "product_density_kg_m3": float(L["product_density_t_m3"]) * 1000.0 if L.get("product_density_t_m3") else None,
        "fill_level_mm": float(L["fill_height_m"]) * 1000.0 if L.get("fill_height_m") else None,
    }


def anketa(data: dict, loads_input: dict | None = None) -> dict:
    """Поля anketa.json пакета (подставляются в project.yaml) + report_data одной строкой JSON."""
    import json
    title = f"Резервуара {data.get('tank_name', '')}" + (f" №{data['tag']}" if data.get("tag") else "") + " на прочность и устойчивость"
    a = {"number": data.get("number", ""), "year": data.get("year", ""), "title": title,
         "executor_position": data.get("executor_position", ""), "executor_name": data.get("executor_name", ""),
         "contractor": data.get("contractor", ""), "phone": data.get("phone", ""),
         "tank_name": data.get("tank_name", ""), "tag": data.get("tag", ""), "site": data.get("site", ""), "site_number": data.get("site_number", ""),
         "purpose": data.get("purpose", ""), "product": data.get("product", ""), "hazard_class": data.get("hazard_class", ""), "kmd": data.get("kmd", ""),
         "roof_radius": data.get("roof_radius", ""), "steel_name": data.get("steel_name", ""), "steel_standard": data.get("steel_standard", ""),
         "steel_yield_mpa": data.get("steel_yield_mpa", ""), "steel_ultimate_mpa": data.get("steel_ultimate_mpa", ""),
         "elongation_pct": data.get("elongation_pct", ""), "steel_thickness_range": data.get("steel_thickness_range", ""),
         "report_data": json.dumps(report_data(data, loads_input), ensure_ascii=False)}
    return {k: (str(v).replace(",", ".") if k in ("roof_radius", "steel_yield_mpa", "steel_ultimate_mpa", "elongation_pct", "year") else v) for k, v in a.items()}


def loads_overrides(data: dict) -> dict:
    """Поправки во входные данные расчёта нагрузок (loads_input.json): Ansys считает с теми же числами, что в отчёте."""
    n = lambda k: _num(data[k]) if str(data.get(k, "")).strip() else None
    out = {"snow_kpa": n("snow_kpa"), "snow_gf": n("snow_gf"), "wind_kpa": n("wind_kpa"), "roof_insulation_kg": n("roof_ins_kg"),
           "wall_insulation_kg": n("wall_ins_kg"), "ryn_mpa": n("steel_yield_mpa"), "e_mpa": n("steel_e_mpa"), "steel_density_kg_m3": n("steel_density")}
    return {k: v for k, v in out.items() if v is not None}
