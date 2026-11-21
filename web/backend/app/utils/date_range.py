"""
Date range parser para los endpoints del dashboard (V096).

Permite que cada KPI del dashboard se calcule sobre una ventana temporal
arbitraria + su periodo anterior equivalente (para comparacion 12% vs
periodo anterior).

Default: ultimos 7 dias si no se pasan parametros. Mantiene compatibilidad
con endpoints que esperaban valores semana/mes hardcoded.

Convencion de bounds:
  - start_date INCLUSIVE — incluye 00:00:00 del dia
  - end_date INCLUSIVE — incluye 23:59:59.999 del dia
  - timezone: America/Lima (operacion del CRM)

Previo periodo se calcula simetrico:
  - rango actual = [start, end]
  - rango previo = [start - duration, start - 1 dia]
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, Query

# Lima es UTC-5 sin DST. Para queries con created_at::date funciona OK
# usar la fecha local; para los counts ya filtramos por l.created_at >=.
_LIMA_OFFSET = timedelta(hours=-5)
_LIMA_TZ = timezone(_LIMA_OFFSET, name="America/Lima")


class DateRange:
    """Ventana temporal + su periodo anterior equivalente.

    Atributos:
      start, end:         datetime aware (UTC) — bounds del periodo actual
      prev_start, prev_end: datetime aware (UTC) — bounds del periodo anterior
      duration_days:      duracion del periodo en dias (entero)
      label_start, label_end: date — para mostrar al usuario ("13 jun – 19 jun")
    """

    def __init__(self, start_d: date, end_d: date):
        if end_d < start_d:
            raise HTTPException(
                status_code=422,
                detail="end_date no puede ser anterior a start_date.",
            )

        # Lima local -> UTC. start = 00:00 Lima, end = 23:59:59.999 Lima.
        self.start = datetime(start_d.year, start_d.month, start_d.day, 0, 0, 0, tzinfo=_LIMA_TZ).astimezone(timezone.utc)
        self.end   = datetime(end_d.year,   end_d.month,   end_d.day,   23, 59, 59, 999999, tzinfo=_LIMA_TZ).astimezone(timezone.utc)

        self.label_start = start_d
        self.label_end   = end_d
        self.duration_days = (end_d - start_d).days + 1

        # Periodo anterior: misma duracion, justo antes del actual.
        prev_end_d   = start_d - timedelta(days=1)
        prev_start_d = prev_end_d - timedelta(days=self.duration_days - 1)
        self.prev_start = datetime(prev_start_d.year, prev_start_d.month, prev_start_d.day, 0, 0, 0, tzinfo=_LIMA_TZ).astimezone(timezone.utc)
        self.prev_end   = datetime(prev_end_d.year,   prev_end_d.month,   prev_end_d.day,   23, 59, 59, 999999, tzinfo=_LIMA_TZ).astimezone(timezone.utc)
        self.label_prev_start = prev_start_d
        self.label_prev_end   = prev_end_d

    def as_dict(self) -> dict:
        """Serializable para el frontend — los labels para mostrar 'del X al Y'."""
        return {
            "start":      self.label_start.isoformat(),
            "end":        self.label_end.isoformat(),
            "duration_days": self.duration_days,
            "prev_start": self.label_prev_start.isoformat(),
            "prev_end":   self.label_prev_end.isoformat(),
        }


def parse_date_range(
    start_date: str | None = Query(None, description="YYYY-MM-DD inclusive. Default: hace 6 dias."),
    end_date:   str | None = Query(None, description="YYYY-MM-DD inclusive. Default: hoy."),
) -> DateRange:
    """Dependencia FastAPI: parsea ?start_date=&end_date= a un DateRange.

    Default = ultimos 7 dias (hoy y 6 dias previos).
    """
    today_lima = datetime.now(_LIMA_TZ).date()
    default_start = today_lima - timedelta(days=6)

    if start_date:
        try:
            start_d = date.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"start_date invalido: {start_date} (esperado YYYY-MM-DD)") from None
    else:
        start_d = default_start

    if end_date:
        try:
            end_d = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"end_date invalido: {end_date} (esperado YYYY-MM-DD)") from None
    else:
        end_d = today_lima

    return DateRange(start_d, end_d)
