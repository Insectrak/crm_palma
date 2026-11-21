"""
Verifica que el middleware CORS esté configurado y responda correctamente
a preflight requests desde los orígenes permitidos.
"""


def test_cors_preflight_allowed_origin(client):
    res = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    # FastAPI/Starlette responde 200 o 204 dependiendo de la versión
    assert res.status_code in (200, 204)
    assert "access-control-allow-origin" in {k.lower() for k in res.headers.keys()}


def test_health_response_has_cors_header(client):
    res = client.get(
        "/api/health",
        headers={"Origin": "http://localhost:5173"},
    )
    assert res.status_code == 200
    # Con Origin presente, el middleware debe reflejar el header
    headers_lower = {k.lower(): v for k, v in res.headers.items()}
    assert "access-control-allow-origin" in headers_lower
