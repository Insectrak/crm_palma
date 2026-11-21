"""
Tests del endpoint de configuración SMTP.
En demo_mode devuelve defaults; PUT siempre requiere auth.
"""


def test_smtp_get_requires_auth(client):
    res = client.get("/api/settings/smtp")
    assert res.status_code in (401, 403)


def test_smtp_get_returns_defaults_for_admin_in_demo(client, auth_headers_admin):
    res = client.get("/api/settings/smtp", headers=auth_headers_admin)
    assert res.status_code == 200
    body = res.json()
    assert "smtp_port" in body
    assert "use_ssl" in body


def test_smtp_put_requires_auth(client):
    res = client.put(
        "/api/settings/smtp",
        json={
            "from_address": "",
            "smtp_server": "",
            "from_domain": "",
            "smtp_port": 587,
            "username": "",
            "password": "",
            "use_ssl": False,
            "ignore_tls_errors": False,
            "reject_unauthorized": True,
        },
    )
    assert res.status_code in (401, 403)


def test_smtp_put_accepts_admin_in_demo(client, auth_headers_admin):
    res = client.put(
        "/api/settings/smtp",
        headers=auth_headers_admin,
        json={
            "from_address": "noreply@test.local",
            "smtp_server": "smtp.test.local",
            "from_domain": "test.local",
            "smtp_port": 465,
            "username": "noreply",
            "password": "s3cr3t",
            "use_ssl": True,
            "ignore_tls_errors": False,
            "reject_unauthorized": True,
        },
    )
    assert res.status_code == 200
    assert res.json().get("demo") is True


# ─── Tests de regresión: privilege escalation (SEC-001) ────────────────────
# Antes del fix, los endpoints SMTP solo requerían get_current_user (cualquier
# usuario autenticado), permitiendo que un asesor leyera/sobrescribiera las
# credenciales SMTP. Ahora deben requerir admin estrictamente.

def test_smtp_get_rejects_asesor(client, auth_headers_asesor):
    res = client.get("/api/settings/smtp", headers=auth_headers_asesor)
    assert res.status_code == 403, "Un asesor NO debe poder leer credenciales SMTP"


def test_smtp_get_rejects_supervisor(client, auth_headers_supervisor):
    res = client.get("/api/settings/smtp", headers=auth_headers_supervisor)
    assert res.status_code == 403, "Un supervisor NO debe poder leer credenciales SMTP"


def test_smtp_put_rejects_asesor(client, auth_headers_asesor):
    res = client.put(
        "/api/settings/smtp",
        headers=auth_headers_asesor,
        json={"from_address": "evil@attacker.com", "smtp_server": "evil.com",
              "smtp_port": 25, "username": "evil", "password": "pwn",
              "from_domain": "", "use_ssl": False,
              "ignore_tls_errors": False, "reject_unauthorized": True},
    )
    assert res.status_code == 403, "Un asesor NO debe poder sobrescribir SMTP"


def test_smtp_test_rejects_asesor(client, auth_headers_asesor):
    res = client.post(
        "/api/settings/smtp/test",
        headers=auth_headers_asesor,
        json={"to": "victim@example.com"},
    )
    assert res.status_code == 403, "Un asesor NO debe poder enviar test SMTP"
