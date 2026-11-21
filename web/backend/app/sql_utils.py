"""
Utilidades para construir fragmentos SQL de forma segura.
"""
import re

# Patron valido para nombres de columna PostgreSQL
_COL_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def safe_set_clause(
    fields: dict,
    allowed_columns: set[str],
) -> tuple[str, list]:
    """Genera un SET clause seguro a partir de un dict de campos.

    Valida que cada key sea una columna permitida y tenga formato valido.
    Retorna (set_sql, params) listos para psycopg2.

    Raises:
        ValueError: si algun campo no esta en la whitelist.
    """
    invalid = set(fields.keys()) - allowed_columns
    if invalid:
        raise ValueError(f"Columnas no permitidas: {invalid}")

    for col in fields:
        if not _COL_RE.match(col):
            raise ValueError(f"Nombre de columna invalido: {col!r}")

    parts = [f"{col} = %s" for col in fields]
    return ", ".join(parts), list(fields.values())
