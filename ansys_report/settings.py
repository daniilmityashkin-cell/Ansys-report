"""Настройка соответствий: как в конкретном проекте Ansys называются пояса, расчёты, какая ось вертикальная."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict


@dataclass
class ModelSettings:
    belt_regex: str = r"^p\s*(\d+)$"      # имя тела-пояса; группа 1 = номер пояса (снизу вверх)
    vertical_axis: str = "X"              # вертикальная ось резервуара в Ansys: X, Y или Z
    static_prefix: str = "Static"         # расчёты прочности начинаются с этого
    buckling_prefix: str = "Eigenvalue"   # расчёты устойчивости начинаются с этого
    full_analysis: str = ""               # расчёт «полного» резервуара; пусто = выбрать автоматически
    empty_analysis: str = ""              # расчёт «пустого»; пусто = выбрать автоматически
    buckling_labels: dict = field(default_factory=dict)   # {имя расчёта устойчивости: подпись в отчёте}

    def env(self) -> dict[str, str]:
        """Переменные окружения для скриптов, исполняемых внутри Mechanical."""
        return {"ANSYS_REPORT_BELT_REGEX": self.belt_regex, "ANSYS_REPORT_AXIS": self.vertical_axis.upper(),
                "ANSYS_REPORT_STATIC": self.static_prefix, "ANSYS_REPORT_EIGEN": self.buckling_prefix}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "ModelSettings":
        d = d or {}
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def pick_roles(analyses: list[str], s: ModelSettings) -> tuple[str | None, str | None]:
    """Какой расчёт прочности считать «полным», какой «пустым» (по настройке, иначе по имени, иначе по порядку)."""
    static = [a for a in analyses if a.startswith(s.static_prefix)]
    if not static:
        return None, None
    low = lambda a: a.lower()
    full = s.full_analysis if s.full_analysis in static else next(
        (a for a in static if "full" in low(a) or "полн" in low(a)), static[-1])
    rest = [a for a in static if a != full]
    empty = s.empty_analysis if s.empty_analysis in static and s.empty_analysis != full else next(
        (a for a in rest if "empty" in low(a) or "пуст" in low(a)), rest[-1] if rest else None)
    return full, empty
