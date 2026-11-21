"""
Pruebas unitarias y de integración para el módulo Leads Campañas:
- Sincronización de campañas Meta y TikTok.
- Asignación de supervisores a campañas.
- Enrutamiento y resolución de supervisor por campaña.
- Endpoints del router /api/campaign-assignments.
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.campaign_assignment_service import (
    _fetch_meta_campaigns,
    _fetch_tiktok_campaigns,
    resolve_campaign_supervisor,
    list_campaign_assignments,
    update_campaign_assignment,
    bulk_assign_supervisors,
    create_or_upsert_campaign_assignment,
    sync_all_campaigns,
)


def test_fetch_meta_campaigns_parses_active_and_paused():
    mock_data = {
        "data": [
            {
                "id": "120202938484",
                "name": "Campaña Leads Meta Verano",
                "status": "ACTIVE",
                "effective_status": "ACTIVE",
                "objective": "OUTCOME_LEADS",
            },
            {
                "id": "120202938485",
                "name": "Campaña Meta Invierno Pausada",
                "status": "PAUSED",
                "effective_status": "CAMPAIGN_PAUSED",
                "objective": "CONVERSIONS",
            },
        ],
        "paging": {}
    }

    with patch("httpx.Client.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_data
        mock_get.return_value = mock_resp

        campaigns = _fetch_meta_campaigns("act_123456789", "fake_token")
        assert len(campaigns) == 2
        assert campaigns[0]["campaign_id"] == "120202938484"
        assert campaigns[0]["status"] == "ACTIVE"
        assert campaigns[0]["provider"] == "meta"
        assert campaigns[1]["campaign_id"] == "120202938485"
        assert campaigns[1]["status"] == "PAUSED"


def test_fetch_tiktok_campaigns_parses_active_and_disabled():
    mock_data = {
        "code": 0,
        "message": "OK",
        "data": {
            "list": [
                {
                    "campaign_id": "71928374928172",
                    "campaign_name": "TikTok Lead Gen Activa",
                    "operation_status": "ENABLE",
                    "secondary_status": "CAMPAIGN_STATUS_ENABLE",
                    "objective_type": "LEAD_GENERATION",
                },
                {
                    "campaign_id": "71928374928173",
                    "campaign_name": "TikTok Promo Pausada",
                    "operation_status": "DISABLE",
                    "secondary_status": "CAMPAIGN_STATUS_DISABLE",
                    "objective_type": "TRAFFIC",
                },
            ],
            "page_info": {"total_page": 1}
        }
    }

    with patch("httpx.Client.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_data
        mock_get.return_value = mock_resp

        campaigns = _fetch_tiktok_campaigns("adv_987654", "fake_tt_token")
        assert len(campaigns) == 2
        assert campaigns[0]["campaign_id"] == "71928374928172"
        assert campaigns[0]["status"] == "ACTIVE"
        assert campaigns[0]["provider"] == "tiktok"
        assert campaigns[1]["campaign_id"] == "71928374928173"
        assert campaigns[1]["status"] == "PAUSED"


def test_resolve_campaign_supervisor_finds_assigned_active_supervisor():
    cur = MagicMock()
    sup_uuid = "11111111-2222-3333-4444-555555555555"
    cur.fetchone.return_value = {
        "assignment_id": 1,
        "default_supervisor_id": sup_uuid,
        "distribution_mode": "supervisor",
        "campaign_name": "Campaña Test",
    }
    cur.fetchall.return_value = [
        {"cas_id": 10, "supervisor_id": sup_uuid, "last_assigned_at": None, "sup_nombre": "Sup Test"}
    ]

    result = resolve_campaign_supervisor(cur, campana="120202938484", campaign_name="Campaña Test")
    assert result == sup_uuid
    assert cur.execute.called


def test_resolve_campaign_supervisor_returns_none_if_unassigned():
    cur = MagicMock()
    cur.fetchone.return_value = None

    result = resolve_campaign_supervisor(cur, campana="campana_sin_asignar")
    assert result is None


def test_update_campaign_assignment_validates_and_updates():
    cur = MagicMock()
    sup_uuid = "11111111-2222-3333-4444-555555555555"
    # User check passes
    cur.fetchall.return_value = [{"id": sup_uuid, "is_active": True, "role": "supervisor"}]
    cur.fetchone.return_value = {
        "id": 1,
        "provider": "meta",
        "campaign_id": "123",
        "supervisor_id": sup_uuid,
        "is_active": True,
    }

    res = update_campaign_assignment(cur, assignment_id=1, supervisor_id=sup_uuid, is_active=True, admin_user_id="admin-uuid")
    assert res["ok"] is True
    assert res["assignment"]["supervisor_id"] == sup_uuid


def test_update_campaign_assignment_multiple_supervisors():
    cur = MagicMock()
    sup_a = "11111111-1111-1111-1111-111111111111"
    sup_b = "22222222-2222-2222-2222-222222222222"

    cur.fetchall.return_value = [
        {"id": sup_a, "is_active": True, "role": "supervisor"},
        {"id": sup_b, "is_active": True, "role": "supervisor"},
    ]
    cur.fetchone.return_value = {
        "id": 1,
        "provider": "meta",
        "campaign_id": "123",
        "supervisor_id": sup_a,
        "is_active": True,
    }

    res = update_campaign_assignment(
        cur,
        assignment_id=1,
        supervisor_ids=[sup_a, sup_b],
        distribution_mode="equipo",
        admin_user_id="admin-uuid",
    )
    assert res["ok"] is True
    assert res["assignment"]["supervisor_id"] == sup_a
    assert cur.execute.called


def test_bulk_assign_supervisors():
    cur = MagicMock()
    sup_uuid = "11111111-2222-3333-4444-555555555555"
    cur.fetchall.side_effect = [
        [{"id": sup_uuid, "is_active": True}],  # user check
        [{"id": 1}, {"id": 2}],                 # updated rows
    ]

    res = bulk_assign_supervisors(cur, assignment_ids=[1, 2], supervisor_id=sup_uuid, admin_user_id="admin-uuid")
    assert res["ok"] is True
    assert res["updated_count"] == 2


def test_bulk_assign_multiple_supervisors():
    cur = MagicMock()
    sup_a = "11111111-1111-1111-1111-111111111111"
    sup_b = "22222222-2222-2222-2222-222222222222"

    cur.fetchall.side_effect = [
        [{"id": sup_a, "is_active": True}, {"id": sup_b, "is_active": True}],  # users check
        [{"id": 10}, {"id": 20}],                                               # updated rows
    ]

    res = bulk_assign_supervisors(
        cur,
        assignment_ids=[10, 20],
        supervisor_ids=[sup_a, sup_b],
        distribution_mode="equipo",
        admin_user_id="admin-uuid",
    )
    assert res["ok"] is True
    assert res["updated_count"] == 2


def test_resolve_campaign_supervisor_assignment_direct_and_team():
    from app.services.campaign_assignment_service import resolve_campaign_supervisor_assignment

    cur = MagicMock()
    sup_uuid = "11111111-2222-3333-4444-555555555555"

    # Caso 1: Modo direct (supervisor)
    cur.fetchone.return_value = {
        "assignment_id": 1,
        "default_supervisor_id": sup_uuid,
        "distribution_mode": "supervisor",
        "campaign_name": "Campaña Directa",
    }
    cur.fetchall.return_value = [
        {"cas_id": 10, "supervisor_id": sup_uuid, "last_assigned_at": None, "sup_nombre": "Sup Directo"}
    ]
    res = resolve_campaign_supervisor_assignment(cur, campana="12345", campaign_name="Campaña Directa")
    assert res is not None
    assert res["supervisor_id"] == sup_uuid
    assert res["distribution_mode"] == "supervisor"

    # Caso 2: Modo equipo
    cur.fetchone.return_value = {
        "assignment_id": 2,
        "default_supervisor_id": sup_uuid,
        "distribution_mode": "equipo",
        "campaign_name": "Campaña Equipo",
    }
    cur.fetchall.return_value = [
        {"cas_id": 11, "supervisor_id": sup_uuid, "last_assigned_at": None, "sup_nombre": "Sup Equipo"}
    ]
    res2 = resolve_campaign_supervisor_assignment(cur, campana="67890", campaign_name="Campaña Equipo")
    assert res2 is not None
    assert res2["supervisor_id"] == sup_uuid
    assert res2["distribution_mode"] == "equipo"


def test_multi_supervisor_equitable_direct_rotation():
    """Verifica que con dos supervisores asignados, los leads roten equitativamente 50%/50%."""
    from app.services.campaign_assignment_service import resolve_campaign_supervisor_assignment
    import datetime

    cur = MagicMock()
    sup_a = "11111111-1111-1111-1111-111111111111"
    sup_b = "22222222-2222-2222-2222-222222222222"

    cur.fetchone.return_value = {
        "assignment_id": 1,
        "default_supervisor_id": sup_a,
        "distribution_mode": "supervisor",
        "campaign_name": "Campaña Multi-Supervisor Directa",
    }

    # Lead 1: Ambos en NULL -> Elige Sup A
    cur.fetchall.return_value = [
        {"cas_id": 1, "supervisor_id": sup_a, "last_assigned_at": None, "sup_nombre": "Sup A"},
        {"cas_id": 2, "supervisor_id": sup_b, "last_assigned_at": None, "sup_nombre": "Sup B"},
    ]
    r1 = resolve_campaign_supervisor_assignment(cur, campana="multi_direct")
    assert r1["supervisor_id"] == sup_a

    # Lead 2: Sup B en NULL, Sup A con timestamp reciente -> Elige Sup B
    cur.fetchall.return_value = [
        {"cas_id": 2, "supervisor_id": sup_b, "last_assigned_at": None, "sup_nombre": "Sup B"},
        {"cas_id": 1, "supervisor_id": sup_a, "last_assigned_at": datetime.datetime(2026, 9, 7, 10, 0), "sup_nombre": "Sup A"},
    ]
    r2 = resolve_campaign_supervisor_assignment(cur, campana="multi_direct")
    assert r2["supervisor_id"] == sup_b

    # Lead 3: Sup A tiene fecha más antigua -> Elige Sup A
    cur.fetchall.return_value = [
        {"cas_id": 1, "supervisor_id": sup_a, "last_assigned_at": datetime.datetime(2026, 9, 7, 10, 0), "sup_nombre": "Sup A"},
        {"cas_id": 2, "supervisor_id": sup_b, "last_assigned_at": datetime.datetime(2026, 9, 7, 10, 5), "sup_nombre": "Sup B"},
    ]
    r3 = resolve_campaign_supervisor_assignment(cur, campana="multi_direct")
    assert r3["supervisor_id"] == sup_a

    # Lead 4: Sup B tiene fecha más antigua -> Elige Sup B
    cur.fetchall.return_value = [
        {"cas_id": 2, "supervisor_id": sup_b, "last_assigned_at": datetime.datetime(2026, 9, 7, 10, 5), "sup_nombre": "Sup B"},
        {"cas_id": 1, "supervisor_id": sup_a, "last_assigned_at": datetime.datetime(2026, 9, 7, 10, 10), "sup_nombre": "Sup A"},
    ]
    r4 = resolve_campaign_supervisor_assignment(cur, campana="multi_direct")
    assert r4["supervisor_id"] == sup_b


def test_multi_supervisor_team_interleaved_distribution():
    """Verifica el caso específico solicitado:

    Equipo A (4 personas) y Equipo B (4 personas).
    Secuencia esperada de asignación de leads:
    Lead 1: Equipo A -> Asesor A1
    Lead 2: Equipo B -> Asesor B1
    Lead 3: Equipo A -> Asesor A2
    Lead 4: Equipo B -> Asesor B2
    Lead 5: Equipo A -> Asesor A3
    Lead 6: Equipo B -> Asesor B3
    Lead 7: Equipo A -> Asesor A4
    Lead 8: Equipo B -> Asesor B4
    Lead 9: Equipo A -> Asesor A1
    """
    from app.services.campaign_assignment_service import (
        resolve_campaign_supervisor_assignment,
        assign_to_supervisor_team_round_robin,
    )
    import datetime

    sup_a = "11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    sup_b = "22222222-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    # Simulación de estados internos de los dos equipos
    team_a_members = [
        {"equipo_id": 101, "user_id": "a1", "nombre": "Persona A1", "email": "a1@test.com", "orden": 1, "last_assigned_at": None},
        {"equipo_id": 102, "user_id": "a2", "nombre": "Persona A2", "email": "a2@test.com", "orden": 2, "last_assigned_at": None},
        {"equipo_id": 103, "user_id": "a3", "nombre": "Persona A3", "email": "a3@test.com", "orden": 3, "last_assigned_at": None},
        {"equipo_id": 104, "user_id": "a4", "nombre": "Persona A4", "email": "a4@test.com", "orden": 4, "last_assigned_at": None},
    ]
    team_b_members = [
        {"equipo_id": 201, "user_id": "b1", "nombre": "Persona B1", "email": "b1@test.com", "orden": 1, "last_assigned_at": None},
        {"equipo_id": 202, "user_id": "b2", "nombre": "Persona B2", "email": "b2@test.com", "orden": 2, "last_assigned_at": None},
        {"equipo_id": 203, "user_id": "b3", "nombre": "Persona B3", "email": "b3@test.com", "orden": 3, "last_assigned_at": None},
        {"equipo_id": 204, "user_id": "b4", "nombre": "Persona B4", "email": "b4@test.com", "orden": 4, "last_assigned_at": None},
    ]
    sups_state = [
        {"cas_id": 1, "supervisor_id": sup_a, "last_assigned_at": None, "sup_nombre": "Supervisor A"},
        {"cas_id": 2, "supervisor_id": sup_b, "last_assigned_at": None, "sup_nombre": "Supervisor B"},
    ]

    cur = MagicMock()

    cur.fetchone.return_value = {
        "assignment_id": 99,
        "default_supervisor_id": sup_a,
        "distribution_mode": "equipo",
        "campaign_name": "Campaña Inmobiliaria Verano",
    }

    clock = 1000

    def mock_fetchall():
        # Ordenar sups_state por last_assigned_at ASC NULLS FIRST, cas_id ASC
        return sorted(sups_state, key=lambda s: (s["last_assigned_at"] is not None, s["last_assigned_at"] or 0, s["cas_id"]))

    cur.fetchall.side_effect = mock_fetchall

    def simular_lead():
        nonlocal clock
        # 1. Resolver campaña
        camp_rule = resolve_campaign_supervisor_assignment(cur, campana="campana_verano")
        chosen_sup = camp_rule["supervisor_id"]

        # Actualizar last_assigned_at del supervisor en sups_state
        for s in sups_state:
            if s["supervisor_id"] == chosen_sup:
                s["last_assigned_at"] = clock
                break
        clock += 1

        # 2. Asignar en equipo
        members = team_a_members if chosen_sup == sup_a else team_b_members
        # Orden de la query: last_assigned_at ASC NULLS FIRST, orden ASC
        ordered = sorted(members, key=lambda m: (m["last_assigned_at"] is not None, m["last_assigned_at"] or 0, m["orden"]))
        winner = ordered[0]
        winner["last_assigned_at"] = clock
        clock += 1

        return chosen_sup, winner["user_id"]

    results = [simular_lead() for _ in range(9)]

    expected_sequence = [
        (sup_a, "a1"),
        (sup_b, "b1"),
        (sup_a, "a2"),
        (sup_b, "b2"),
        (sup_a, "a3"),
        (sup_b, "b3"),
        (sup_a, "a4"),
        (sup_b, "b4"),
        (sup_a, "a1"),  # Vuelve a rotar la primera persona del equipo A
    ]

    for idx, (expected, actual) in enumerate(zip(expected_sequence, results), 1):
        assert actual == expected, f"Lead #{idx} esperado {expected}, pero fue {actual}"


def test_assign_to_supervisor_team_round_robin():
    from app.services.campaign_assignment_service import assign_to_supervisor_team_round_robin

    cur = MagicMock()
    sup_uuid = "11111111-2222-3333-4444-555555555555"
    asesor_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    # Caso 1: Asesor encontrado en el equipo
    cur.fetchone.return_value = {
        "equipo_id": 42,
        "user_id": asesor_uuid,
        "nombre": "Asesor Uno",
        "email": "asesor1@empresa.com",
    }
    winner = assign_to_supervisor_team_round_robin(cur, sup_uuid)
    assert winner is not None
    assert winner["user_id"] == asesor_uuid
    assert winner["nombre"] == "Asesor Uno"
    # Debe haber ejecutado el SELECT con filtro de disponible_rotacion y el UPDATE de last_assigned_at
    assert cur.execute.call_count >= 2
    select_sql = cur.execute.call_args_list[0][0][0]
    assert "crm.asesor_settings" in select_sql
    assert "disponible_rotacion" in select_sql
    assert "ausencia_desde" in select_sql

    # Caso 2: Equipo sin asesores disponibles (ej. todos pausados)
    cur.fetchone.return_value = None
    fallback = assign_to_supervisor_team_round_robin(cur, sup_uuid)
    assert fallback is None


def test_update_campaign_assignment_distribution_mode():
    cur = MagicMock()
    sup_uuid = "11111111-2222-3333-4444-555555555555"
    cur.fetchone.return_value = {
        "id": 1,
        "provider": "meta",
        "campaign_id": "123",
        "supervisor_id": sup_uuid,
        "distribution_mode": "equipo",
        "is_active": True,
    }

    # Actualizar solo distribution_mode sin cambiar supervisor
    res = update_campaign_assignment(
        cur,
        assignment_id=1,
        distribution_mode="equipo",
        update_supervisor=False,
    )
    assert res["ok"] is True
    assert res["assignment"]["distribution_mode"] == "equipo"

    # Modo inválido
    res_bad = update_campaign_assignment(
        cur,
        assignment_id=1,
        distribution_mode="invalido",
        update_supervisor=False,
    )
    assert res_bad["ok"] is False
    assert "inválido" in res_bad["error"]


def test_bulk_assign_supervisors_with_distribution_mode():
    cur = MagicMock()
    sup_uuid = "11111111-2222-3333-4444-555555555555"
    cur.fetchall.side_effect = [
        [{"id": sup_uuid, "is_active": True}],
        [{"id": 10}, {"id": 11}],
    ]

    res = bulk_assign_supervisors(
        cur,
        assignment_ids=[10, 11],
        supervisor_id=sup_uuid,
        distribution_mode="equipo",
    )
    assert res["ok"] is True
    assert res["updated_count"] == 2


def test_create_or_upsert_campaign_assignment_stores_distribution_mode():
    cur = MagicMock()
    sup_uuid = "11111111-2222-3333-4444-555555555555"
    cur.fetchall.return_value = [{"id": sup_uuid, "is_active": True}]
    cur.fetchone.return_value = {
        "id": 99,
        "provider": "tiktok",
        "campaign_id": "tt_99",
        "campaign_name": "TT Camp",
        "supervisor_id": sup_uuid,
        "distribution_mode": "equipo",
        "is_active": True,
        "status": "ACTIVE",
    }

    res = create_or_upsert_campaign_assignment(
        cur,
        provider="tiktok",
        campaign_id="tt_99",
        campaign_name="TT Camp",
        supervisor_id=sup_uuid,
        distribution_mode="equipo",
    )
    assert res["ok"] is True
    assert res["assignment"]["distribution_mode"] == "equipo"


def test_resolve_campaign_supervisor_uses_clock_timestamp_and_provider_priority():
    from app.services.campaign_assignment_service import resolve_campaign_supervisor_assignment

    cur = MagicMock()
    sup_a = "11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    cur.fetchone.return_value = {
        "assignment_id": 42,
        "default_supervisor_id": sup_a,
        "distribution_mode": "equipo",
        "campaign_name": "Virtual Oct 1",
    }
    cur.fetchall.return_value = [
        {"cas_id": 1, "supervisor_id": sup_a, "last_assigned_at": None, "sup_nombre": "Edith Campos"}
    ]

    res = resolve_campaign_supervisor_assignment(
        cur,
        campana="1877863290865665",
        campaign_name="Virtual Oct 1",
        provider="tiktok",
    )
    assert res is not None
    assert res["supervisor_id"] == sup_a

    # Check SQL query used clock_timestamp() and provider ordering
    queries = [call[0][0] for call in cur.execute.call_args_list]
    camp_lookup_sql = queries[0]
    assert "c.provider" in camp_lookup_sql
    assert "ORDER BY" in camp_lookup_sql

    update_sql = queries[2]  # 0 is select camp, 1 is select sups, 2 is update
    assert "clock_timestamp()" in update_sql


def test_custom_percentages_weighted_fair_queuing():
    """Valida la distribución ponderada personalizada (ej. 45%, 45%, 10%).

    Para 20 leads distribuidos con pesos 45, 45, 10:
    - Supervisor C (10%) debe recibir exactamente 2 leads (1 de cada 10).
    - Supervisores A y B (45% c/u) deben recibir exactamente 9 leads cada uno.
    """
    from datetime import datetime, timezone
    from app.services.campaign_assignment_service import resolve_campaign_supervisor_assignment

    cur = MagicMock()
    sup_a = "11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # 45%
    sup_b = "22222222-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # 45%
    sup_c = "33333333-cccc-cccc-cccc-cccccccccccc"  # 10%

    cur.fetchone.return_value = {
        "assignment_id": 100,
        "default_supervisor_id": sup_a,
        "distribution_mode": "supervisor",
        "campaign_name": "Campaña Ponderada 45-45-10",
    }

    state = [
        {"cas_id": 1, "supervisor_id": sup_a, "last_assigned_at": None, "porcentaje": 45, "assigned_count": 0, "sup_nombre": "Edith Campos"},
        {"cas_id": 2, "supervisor_id": sup_b, "last_assigned_at": None, "porcentaje": 45, "assigned_count": 0, "sup_nombre": "DARWIN"},
        {"cas_id": 3, "supervisor_id": sup_c, "last_assigned_at": None, "porcentaje": 10, "assigned_count": 0, "sup_nombre": "Supervisor2"},
    ]

    cur.fetchall.side_effect = lambda: [dict(s) for s in state]

    def mock_update(*args, **kwargs):
        sql = args[0]
        params = args[1]
        if "UPDATE crm.campaign_assigned_supervisors" in sql:
            cas_id = params[0]
            for s in state:
                if s["cas_id"] == cas_id:
                    s["assigned_count"] += 1
                    s["last_assigned_at"] = datetime.now(timezone.utc)
                    break

    cur.execute.side_effect = mock_update

    history = []
    for _ in range(20):
        res = resolve_campaign_supervisor_assignment(cur, campana="camp_weighted")
        assert res is not None
        history.append(res["supervisor_id"])

    count_a = history.count(sup_a)
    count_b = history.count(sup_b)
    count_c = history.count(sup_c)

    # 45% de 20 = 9 leads
    # 45% de 20 = 9 leads
    # 10% de 20 = 2 leads (exactamente 1 cada 10)
    assert count_a == 9, f"Esperado 9 para sup_a (45%), pero obtuvo {count_a}"
    assert count_b == 9, f"Esperado 9 para sup_b (45%), pero obtuvo {count_b}"
    assert count_c == 2, f"Esperado 2 para sup_c (10%), pero obtuvo {count_c}"

    # Sup C debe recibir su primer lead temprano (lead 3) y el segundo en el siguiente bloque de 10
    first_c_index = history.index(sup_c)
    second_c_index = history.index(sup_c, first_c_index + 1)
    assert first_c_index < 5
    assert 9 <= second_c_index <= 14


def test_update_campaign_assignment_todos_mode():
    cur = MagicMock()
    sup_uuid = "11111111-2222-3333-4444-555555555555"
    cur.fetchall.return_value = [{"id": sup_uuid, "is_active": True, "role": "supervisor"}]
    cur.fetchone.return_value = {
        "id": 1,
        "provider": "meta",
        "campaign_id": "camp_1",
        "supervisor_id": sup_uuid,
        "distribution_mode": "todos",
        "is_active": True,
    }

    res = update_campaign_assignment(
        cur,
        assignment_id=1,
        distribution_mode="todos",
        admin_user_id="admin-uuid",
        update_supervisor=False,
    )
    assert res["ok"] is True
    assert res["assignment"]["distribution_mode"] == "todos"


def test_update_campaign_assignment_team_custom_modes_and_percentages():
    cur = MagicMock()
    sup_a = "11111111-1111-1111-1111-111111111111"
    asesor_1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    asesor_2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    cur.fetchall.return_value = [{"id": sup_a, "is_active": True, "role": "supervisor"}]
    cur.fetchone.return_value = {
        "id": 1,
        "provider": "meta",
        "campaign_id": "camp_1",
        "supervisor_id": sup_a,
        "distribution_mode": "equipo",
        "is_active": True,
    }

    res = update_campaign_assignment(
        cur,
        assignment_id=1,
        supervisor_ids=[sup_a],
        distribution_mode="equipo",
        team_distribution_modes={sup_a: "todos"},
        team_member_percentages={sup_a: {asesor_1: 60, asesor_2: 40}},
        admin_user_id="admin-uuid",
    )
    assert res["ok"] is True


def test_assign_to_supervisor_team_todos_mode_picks_supervisor_when_oldest():
    from app.services.campaign_assignment_service import assign_to_supervisor_team_round_robin
    from datetime import datetime, timezone, timedelta

    cur = MagicMock()
    sup_uuid = "11111111-2222-3333-4444-555555555555"
    asesor_uuid = "22222222-3333-4444-5555-666666666666"

    now = datetime.now(timezone.utc)
    # Asesor assigned 1 minute ago, supervisor never assigned (None)
    asesores_data = [
        {
            "equipo_id": 10,
            "user_id": asesor_uuid,
            "nombre": "Asesor Uno",
            "email": "asesor1@test.com",
            "last_assigned_at": now - timedelta(minutes=1),
            "orden": 1,
            "is_supervisor": False,
        }
    ]
    cur.fetchall.return_value = asesores_data
    # Supervisor query
    cur.fetchone.side_effect = [
        # auth.users query for supervisor
        {
            "user_id": sup_uuid,
            "nombre": "Supervisor Jefe",
            "email": "sup@test.com",
            "is_active": True,
            "login_blocked": False,
        },
        # campaign_assigned_supervisors query (cas_id)
        {
            "last_assigned_at": None,
            "member_last_assigned": {},
        },
        # cas query for member_percentages
        None,
    ]

    winner = assign_to_supervisor_team_round_robin(
        cur,
        supervisor_id=sup_uuid,
        distribution_mode="todos",
        cas_id=99,
    )
    assert winner is not None
    assert winner["user_id"] == sup_uuid
    assert winner["is_supervisor"] is True


def test_assign_to_supervisor_team_member_percentages_wfq():
    from app.services.campaign_assignment_service import assign_to_supervisor_team_round_robin

    cur = MagicMock()
    sup_uuid = "11111111-2222-3333-4444-555555555555"
    asesor_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    asesor_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    # 2 asesores en el equipo: Asesor A (70%), Asesor B (30%)
    asesores_data = [
        {"equipo_id": 1, "user_id": asesor_a, "nombre": "Asesor A", "email": "a@t.com", "last_assigned_at": None, "orden": 1, "is_supervisor": False},
        {"equipo_id": 2, "user_id": asesor_b, "nombre": "Asesor B", "email": "b@t.com", "last_assigned_at": None, "orden": 2, "is_supervisor": False},
    ]
    cur.fetchall.return_value = asesores_data

    # Estado mutable de conteos
    member_counts = {asesor_a: 0, asesor_b: 0}
    member_percentages = {asesor_a: 70, asesor_b: 30}

    cur.fetchone.return_value = None  # No cas_id DB query needed since passed directly

    history = []
    for _ in range(10):
        w = assign_to_supervisor_team_round_robin(
            cur,
            supervisor_id=sup_uuid,
            distribution_mode="equipo",
            cas_id=None,
            member_percentages=member_percentages,
            member_counts=member_counts,
        )
        assert w is not None
        history.append(w["user_id"])

    # En 10 leads con 70% / 30%: Asesor A debe recibir 7 leads, Asesor B 3 leads
    assert history.count(asesor_a) == 7
    assert history.count(asesor_b) == 3


def test_list_eligible_supervisors_includes_team_members():
    from app.services.campaign_assignment_service import list_eligible_supervisors

    cur = MagicMock()
    sup_uuid = "11111111-2222-3333-4444-555555555555"
    asesor_uuid = "22222222-3333-4444-5555-666666666666"

    # fetchall 1: supervisores
    # fetchall 2: equipos miembros
    cur.fetchall.side_effect = [
        [
            {
                "id": sup_uuid,
                "email": "sup@test.com",
                "role": "supervisor",
                "first_name": "Sup",
                "last_name": "Test",
                "advisor_name": "Supervisor Test",
                "is_active": True,
                "display_name": "Supervisor Test",
            }
        ],
        [
            {
                "supervisor_id": sup_uuid,
                "id": asesor_uuid,
                "email": "asesor@test.com",
                "role": "asesor",
                "display_name": "Asesor 1",
                "orden": 1,
            }
        ],
    ]

    sups = list_eligible_supervisors(cur)
    assert len(sups) == 1
    assert "team_members" in sups[0]
    assert len(sups[0]["team_members"]) == 1
    assert sups[0]["team_members"][0]["id"] == asesor_uuid





