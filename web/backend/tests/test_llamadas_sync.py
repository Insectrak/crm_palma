"""
test_llamadas_sync.py — Pruebas para el endpoint POST /api/llamadas/sync
y la prevención de descarte de llamadas consecutivas al mismo contacto.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from app.routers.llamadas import sync_llamadas, LlamadaSync
from app.auth.jwt import TokenData


def test_sync_dos_llamadas_consecutivas_al_mismo_lead():
    """
    Verifica que al enviar dos llamadas consecutivas al mismo número telefónico,
    ambas sean insertadas exitosamente cuando sus call_log_id son distintos
    (generados con el formato compuesto t{ts}_d{dur}_p{phone}_y{type}).
    """
    user = TokenData(
        user_id="00000000-0000-0000-0000-000000000001",
        role="asesor",
        email="asesor@example.com",
    )

    # Simular llamada 1 (inicio 10:00:00, duracion 15s)
    llamada1 = LlamadaSync(
        call_log_id="t1716000000000_d15_p999888777_y2",
        telefono="+51999888777",
        duracion_segundos=15,
        tipo="saliente",
        fecha_llamada="2026-05-18T15:00:00Z",
        dispositivo_id="dev-123",
        nombre_contacto="Juan Perez",
    )

    # Simular llamada 2 (inicio 10:01:00, duracion 30s)
    llamada2 = LlamadaSync(
        call_log_id="t1716000060000_d30_p999888777_y2",
        telefono="+51999888777",
        duracion_segundos=30,
        tipo="saliente",
        fecha_llamada="2026-05-18T15:01:00Z",
        dispositivo_id="dev-123",
        nombre_contacto="Juan Perez",
    )

    cur = MagicMock()
    # Para cada llamada:
    # 1. SELECT lead_id por telefono
    # 2. INSERT en crm.llamadas (cur.rowcount = 1)
    cur.fetchone.return_value = {"id": 100}  # lead_id = 100
    cur.rowcount = 1

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.llamadas.get_db", return_value=db_cm), \
         patch("app.services.sla_service.registrar_primer_contacto_sla"):

        result = sync_llamadas(items=[llamada1, llamada2], current_user=user)

    assert result["synced"] == 2
    assert result["skipped"] == 0


def test_sync_duplicado_exacto_se_descarta():
    """
    Verifica que un reenvío del mismo registro de llamada (mismo call_log_id)
    sea reconocido como duplicado por Postgres y se contabilice en 'skipped'.
    """
    user = TokenData(
        user_id="00000000-0000-0000-0000-000000000001",
        role="asesor",
        email="asesor@example.com",
    )

    llamada_repetida = LlamadaSync(
        call_log_id="t1716000000000_d15_p999888777_y2",
        telefono="+51999888777",
        duracion_segundos=15,
        tipo="saliente",
        fecha_llamada="2026-05-18T15:00:00Z",
        dispositivo_id="dev-123",
    )

    cur = MagicMock()
    cur.fetchone.return_value = {"id": 100}
    cur.rowcount = 0  # ON CONFLICT DO NOTHING -> 0 filas insertadas

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.llamadas.get_db", return_value=db_cm):
        result = sync_llamadas(items=[llamada_repetida], current_user=user)

    assert result["synced"] == 0
    assert result["skipped"] == 1
