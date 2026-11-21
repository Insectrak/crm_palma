"""
Carga Masiva — importación de leads desde Excel o CSV.
- GET  /api/leads/carga-masiva/plantilla  — descarga plantilla Excel
- POST /api/leads/carga-masiva/preview    — previsualiza el archivo sin importar
- POST /api/leads/carga-masiva            — importa con validaciones completas
"""
import io
import csv
import re
import json
import logging
from datetime import datetime, date
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import StreamingResponse
import openpyxl
from psycopg2.extras import RealDictCursor
from app.auth.jwt import require_supervisor_or_admin, get_current_user
from app.auth.schemas import TokenData
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/leads/carga-masiva", tags=["Carga Masiva"])

MAX_ROWS    = 1000
MAX_MB      = 5
MAX_PREVIEW = 10


# ── Limpieza y validación de campos ──────────────────────────────────────────

def _clean_phone(raw) -> str | None:
    """Normaliza teléfono: limpia separadores, normaliza números peruanos."""
    if raw is None:
        return None
    s = re.sub(r'[\s\-\(\)\.]+', '', str(raw).strip())
    digits = re.sub(r'\D', '', s)
    if not digits or set(digits) == {'0'}:
        return None
    # Móvil peruano: 9 dígitos
    if len(digits) == 9:
        return '+51' + digits
    # Con código de país 51: 11 dígitos
    if len(digits) == 11 and digits.startswith('51'):
        return '+' + digits
    # Aceptar cualquier otro número de longitud razonable
    if 7 <= len(digits) <= 15:
        return digits
    return None


def _clean_email(raw) -> str | None:
    if not raw:
        return None
    s = str(raw).strip().lower()
    if re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$', s):
        return s
    return None  # email malformado → ignorar, no es error fatal


def _clean_text(raw, max_len: int = 200) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()[:max_len]
    return s or None


# Aliases estáticos para idiomas/variantes comunes que no están en la DB.
# El catálogo real (`crm.catalogo_calidad`) es la fuente de verdad y el `codigo`
# se consulta directamente; estos aliases solo sirven para que gerencia pueda
# escribir "frío", "cold", "hot" en el Excel y el importador lo reconozca.
_CALIDAD_ALIASES_ESTATICOS: dict[str, str] = {
    'frio': 'FRIO', 'frío': 'FRIO', 'cold': 'FRIO',
    'tibio': 'TIBIO', 'warm': 'TIBIO',
    'caliente': 'CALIENTE', 'hot': 'CALIENTE',
}


def _load_calidad_catalog() -> tuple[set[str], dict[str, str]]:
    """Lee el catálogo activo y devuelve (codigos, aliases_dinamicos).

    `aliases_dinamicos` mapea `nombre.lower()` → `codigo`, de modo que si
    gerencia agrega "Hielo" con código FRIO, el importador lo reconozca sin
    más cambios. Los códigos mismos siempre se reconocen (match exacto).
    """
    codigos: set[str] = set()
    aliases: dict[str, str] = {}
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT codigo, nombre FROM crm.catalogo_calidad WHERE activo = TRUE"
                )
                for codigo, nombre in cur.fetchall():
                    codigos.add(codigo)
                    aliases[codigo.lower()] = codigo
                    if nombre:
                        aliases[nombre.strip().lower()] = codigo
    except Exception as exc:
        logger.info("carga_masiva: no se pudo leer catalogo_calidad — %s", exc)
    return codigos, aliases


def _ensure_carga_masiva_schema(cur):
    """Asegura que las columnas de detalles en carga_masiva_historial existan."""
    try:
        cur.execute("""
            ALTER TABLE crm.carga_masiva_historial
                ADD COLUMN IF NOT EXISTS duplicates_details JSONB DEFAULT '[]'::jsonb,
                ADD COLUMN IF NOT EXISTS error_details JSONB DEFAULT '[]'::jsonb;
        """)
    except Exception as exc:
        logger.warning("[carga_masiva] ensure schema error: %s", exc)


def _clean_calidad(
    raw,
    *,
    codigos: set[str] | None = None,
    aliases_dinamicos: dict[str, str] | None = None,
) -> str | None:
    """Normaliza temperatura del lead contra el catálogo activo. Retorna None si no coincide.

    Si `codigos` viene None hace lookup a la DB (útil en tests / llamadas
    aisladas). En el flujo de importación se pre-cargan una sola vez.
    """
    if raw is None:
        return None
    key = str(raw).strip().lower()
    if not key:
        return None

    if codigos is None or aliases_dinamicos is None:
        codigos, aliases_dinamicos = _load_calidad_catalog()

    # 1) Match directo contra los códigos del catálogo (en UPPER).
    upper = key.upper()
    if upper in codigos:
        return upper

    # 2) Alias dinámicos (nombre visible del catálogo).
    if key in aliases_dinamicos:
        return aliases_dinamicos[key]

    # 3) Alias estáticos (multi-idioma). Solo aplican si el código resultante
    # sigue existiendo en el catálogo; si el admin eliminó FRIO, la palabra
    # "frío" deja de reconocerse automáticamente.
    mapped = _CALIDAD_ALIASES_ESTATICOS.get(key)
    if mapped and mapped in codigos:
        return mapped

    return None


# Formatos de fecha aceptados en orden de preferencia. Ampliar con cuidado:
# un formato ambiguo (DD/MM vs MM/DD) puede meter datos en el mes equivocado.
# La plantilla y la UI documentan YYYY-MM-DD y DD/MM/YYYY como canónicos.
_FECHA_FORMATS: tuple[str, ...] = (
    '%Y-%m-%d',
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%dT%H:%M:%S',
    '%d/%m/%Y',
    '%d/%m/%Y %H:%M:%S',
    '%d-%m-%Y',
)


def _clean_fecha(raw) -> datetime | None:
    """Parsea una fecha (Excel date, datetime, ISO, DD/MM/YYYY). Retorna None si no se reconoce."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day)
    s = str(raw).strip()
    if not s:
        return None
    for fmt in _FECHA_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _validate_row(
    mapped: dict,
    *,
    calidad_codigos: set[str] | None = None,
    calidad_aliases: dict[str, str] | None = None,
    calidad_requerida: bool = False,
) -> tuple[dict, list[str]]:
    """Valida y limpia un diccionario de campos. Retorna (datos_limpios, errores).

    `calidad_codigos` / `calidad_aliases`: catálogo pre-cargado. Si no se pasan
    se consultan a la DB fila por fila (útil en tests; innecesariamente lento
    en el flujo real).
    `calidad_requerida`: si True, una fila sin calidad reconocida se marca
    como error bloqueante (flag administrado desde settings).
    """
    errors: list[str] = []
    out: dict = {}

    # Teléfono — obligatorio
    tel = _clean_phone(mapped.get('telefono'))
    if not tel:
        errors.append('Teléfono inválido o vacío (mínimo 7 dígitos, sin letras ni solo ceros)')
    else:
        out['telefono'] = tel

    # Nombres / Apellidos — al menos uno requerido
    nombres   = _clean_text(mapped.get('nombres'))
    apellidos = _clean_text(mapped.get('apellidos'))
    if not nombres and not apellidos:
        errors.append('Debe tener al menos nombres o apellidos')
    out['nombres']   = nombres or 'Sin nombre'
    out['apellidos'] = apellidos

    # Email — opcional, se ignora si malformado (sin bloquear la fila)
    out['email'] = _clean_email(mapped.get('email'))

    # DNI — solo dígitos, 6-12 caracteres
    dni_raw = _clean_text(mapped.get('dni'))
    if dni_raw:
        digits = re.sub(r'\D', '', dni_raw)
        out['dni'] = digits if 6 <= len(digits) <= 12 else None
    else:
        out['dni'] = None

    # Campaña y observaciones — texto libre
    out['campana']       = _clean_text(mapped.get('campana'), 150)
    out['observaciones'] = _clean_text(mapped.get('observaciones'), 500)

    # Campos gerencia: ciudad, calidad, codigo_convenio
    out['ciudad']          = _clean_text(mapped.get('ciudad'),          120)
    out['codigo_convenio'] = _clean_text(mapped.get('codigo_convenio'), 100)
    # V060: proyecto y estrategia siguen siendo aceptados por retrocompat
    # con plantillas antiguas, pero ya NO son la convencion canonica.
    # La unificacion campana <- proyecto y fuente <- estrategia se hace
    # mas abajo, despues de que out['fuente_raw'] este seteado.
    out['proyecto']   = _clean_text(mapped.get('proyecto'),   120)
    out['estrategia'] = _clean_text(mapped.get('estrategia'), 200)

    # Calidad — validada contra el catálogo configurable (V028). Si el admin
    # tiene activado `calidad_requerida`, una fila sin valor válido se bloquea.
    calidad_raw = mapped.get('calidad')
    calidad_clean = _clean_calidad(
        calidad_raw,
        codigos=calidad_codigos,
        aliases_dinamicos=calidad_aliases,
    )
    opciones_txt = ", ".join(sorted(calidad_codigos)) if calidad_codigos else "ver catálogo"
    if calidad_raw and not calidad_clean and str(calidad_raw).strip():
        errors.append(
            f"Calidad '{str(calidad_raw).strip()}' no reconocida (valores válidos: {opciones_txt})"
        )
    elif calidad_requerida and not calidad_clean:
        errors.append(f"Calidad obligatoria. Valores válidos: {opciones_txt}")
    out['calidad'] = calidad_clean

    # Fecha — sobrescribe created_at si viene presente y válida.
    fecha_raw = mapped.get('fecha')
    fecha_clean = _clean_fecha(fecha_raw)
    if fecha_raw and not fecha_clean and str(fecha_raw).strip():
        errors.append(
            f"Fecha '{str(fecha_raw).strip()}' no reconocida (usa YYYY-MM-DD o DD/MM/YYYY)"
        )
    out['fecha'] = fecha_clean

    # Fuente — se resuelve después contra la DB
    out['fuente_raw'] = _clean_text(mapped.get('fuente'), 100)

    # Asesor — opcional, se resuelve después contra auth.users
    out['asesor_raw'] = _clean_text(mapped.get('asesor'), 100)

    # V065: Sede — opcional, slug case-insensitive. Resolver despues
    # contra crm.sedes. Si no existe el slug, queda NULL y se loguea.
    out['sede_raw'] = _clean_text(mapped.get('sede'), 60)

    # V060: retrocompatibilidad con plantillas antiguas (proyecto/estrategia).
    # Si campana viene vacia y proyecto trae valor, lo unificamos.
    # Si fuente viene vacia y estrategia trae valor, intentamos usarla como
    # fuente (lookup en crm.fuentes la resuelve si matchea, sino fuente_id=NULL).
    if not out['campana'] and out['proyecto']:
        out['campana'] = out['proyecto']
    if not out['fuente_raw'] and out['estrategia']:
        out['fuente_raw'] = out['estrategia']

    # Fuente es obligatoria
    if not out.get('fuente_raw'):
        errors.append("La fuente es obligatoria")

    # Si la fuente es convenio o convenios, codigo_convenio es obligatorio
    if out.get('fuente_raw') and "convenio" in out['fuente_raw'].lower():
        if not (out.get('codigo_convenio') and str(out.get('codigo_convenio')).strip()):
            errors.append("Para la fuente Convenios es obligatorio indicar el código de convenio")

    return out, errors


# ── Parseo de archivo ─────────────────────────────────────────────────────────

def _parse_file(content: bytes, filename: str) -> tuple[list[str], list[dict]]:
    """Parsea Excel o CSV → (columnas, filas). Máximo MAX_ROWS filas."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    if ext in ('xlsx', 'xls'):
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception:
            raise HTTPException(400, "No se pudo abrir el archivo Excel. Verifica que no esté dañado.")
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        raw_header = next(rows_iter, None)
        if not raw_header:
            wb.close()
            raise HTTPException(400, "El archivo no tiene cabecera.")
        header = [
            str(c).strip() if c is not None else f'col_{i}'
            for i, c in enumerate(raw_header)
        ]
        # Quitar columnas vacías del final
        while header and header[-1].startswith('col_'):
            header.pop()
        if not header:
            wb.close()
            raise HTTPException(400, "No se detectaron columnas en la cabecera.")

        rows: list[dict] = []
        for vals in rows_iter:
            if len(rows) >= MAX_ROWS:
                break
            row_data = dict(zip(header, vals))
            if all(v is None or str(v).strip() == '' for v in row_data.values()):
                continue  # fila vacía
            rows.append(row_data)
        wb.close()
        return header, rows

    elif ext == 'csv':
        text = content.decode('utf-8-sig', errors='replace')
        reader = csv.DictReader(io.StringIO(text))
        header = list(reader.fieldnames or [])
        if not header:
            raise HTTPException(400, "El archivo CSV no tiene cabecera.")
        rows = []
        for row in reader:
            if len(rows) >= MAX_ROWS:
                break
            if all(not str(v or '').strip() for v in row.values()):
                continue
            rows.append(dict(row))
        return header, rows

    else:
        raise HTTPException(400, "Formato no soportado. Use .xlsx, .xls o .csv")


def _apply_map(raw_row: dict, col_map: dict) -> dict:
    """Traduce nombres de columna del archivo a claves internas según col_map."""
    return {
        key: raw_row.get(file_col)
        for key, file_col in col_map.items()
        if file_col
    }


# ── Resolución de fuente ──────────────────────────────────────────────────────

_FUENTE_ALIASES: dict[str, str] = {
    'facebook': 'fb', 'facebook ads': 'fb', 'fb ads': 'fb', 'fb': 'fb',
    'instagram': 'ig', 'ig': 'ig',
    'tiktok': 'tt mensaje', 'tt mensaje': 'tt mensaje',
    'tiktok mensaje': 'tt mensaje', 'tt': 'tt mensaje',
    'whatsapp': 'wa mensaje', 'wa mensaje': 'wa mensaje', 'wa': 'wa mensaje',
    'manual': 'manual', 'referido': 'referido',
}


def _resolve_asesor(asesor_raw: str | None, users_db: dict[str, str]) -> str | None:
    """Resuelve nombre de asesor/supervisor → UUID. Búsqueda flexible por nombre."""
    if not asesor_raw:
        return None
    key = asesor_raw.strip().lower()
    # Búsqueda exacta
    if key in users_db:
        return users_db[key]
    # Búsqueda parcial (nombre contiene o está contenido)
    for name, uid in users_db.items():
        if key in name or name in key:
            return uid
    return None


def _resolve_fuente(fuente_raw: str | None, fuentes_db: dict[str, int]) -> int | None:
    """Resuelve texto libre → fuente_id (int). Retorna None si no se encuentra."""
    if not fuente_raw:
        return None
    key = fuente_raw.strip().lower()
    if key in fuentes_db:
        return fuentes_db[key]
    alias = _FUENTE_ALIASES.get(key)
    if alias and alias in fuentes_db:
        return fuentes_db[alias]
    for db_name, db_id in fuentes_db.items():
        if key in db_name or db_name in key:
            return db_id
    return None


def _resolve_sede(sede_raw: str | None, sedes_db: dict[str, str]) -> str | None:
    """V065: resuelve slug/nombre → sede_id (uuid str). Retorna None si no match.

    Acepta el codigo exacto (lima, arequipa) o el nombre (Clinica Lima).
    Busqueda case-insensitive.
    """
    if not sede_raw:
        return None
    key = sede_raw.strip().lower()
    return sedes_db.get(key)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/plantilla")
def download_plantilla(current_user: TokenData = Depends(get_current_user)):
    """Devuelve una plantilla Excel con cabeceras y fila de ejemplo."""
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Leads"

    # V060: plantilla unificada — campana engloba al proyecto, fuente engloba
    # a la estrategia. Las columnas legacy 'proyecto' y 'estrategia' siguen
    # siendo aceptadas por el parser para retrocompatibilidad con plantillas
    # antiguas, pero ya NO se incluyen en la plantilla descargable.
    # `fecha` sobrescribe created_at si viene; `calidad` acepta FRIO|TIBIO|CALIENTE.
    # V065: agregada columna `sede` opcional (slug o nombre de sede activa).
    # V104: agregada columna `codigo_convenio` opcional para leads de convenios.
    headers = [
        'fecha', 'nombres', 'apellidos', 'telefono', 'email', 'dni',
        'ciudad', 'campana', 'fuente', 'codigo_convenio', 'calidad', 'sede', 'asesor', 'observaciones',
    ]
    # V070.68 (Bundle B): ejemplos genericos sin marca/industria del cliente.
    # Antes esto decia 'Palma Rio' y 'departamento de 2 dormitorios', lo que
    # confundia a usuarios de Doctor Muelita u otros verticales no inmobiliarios.
    example = [
        '2026-04-20', 'Carlos', 'García López', '987654321', 'carlos@email.com', '12345678',
        'Arequipa', 'Campaña Q2 2026', 'Convenios', 'CONV-2026', 'TIBIO',
        'arequipa', 'asesor@test.local',
        'Interesado en nuestros servicios',
    ]
    fuentes_nota = (
        "* telefono y fuente son OBLIGATORIOS.  "
        "fecha (YYYY-MM-DD o DD/MM/YYYY) sobrescribe la fecha de ingreso; si se deja vacía se usa la fecha actual.  |  "
        "campana = nombre de la campaña o promoción.  |  "
        "fuente = canal de origen (Convenios, Activación, Referido, Volanteo, Facebook, etc. — debe existir en el catálogo).  |  "
        "codigo_convenio = código del convenio (obligatorio para leads de convenios).  |  "
        "calidad acepta FRIO, TIBIO o CALIENTE.  |  "
        "sede = slug o nombre de sede activa (ej: 'lima', 'arequipa') — opcional, solo si el CRM tiene sedes configuradas.  |  "
        "asesor = nombre completo o email del asesor (opcional, si se deja vacío se asigna al elegido en la UI).  |  "
        "Máximo 1 000 filas por archivo."
    )

    indigo = "4F46E5"
    thin = Border(
        left=Side(style="thin", color="E5E7EB"),
        right=Side(style="thin", color="E5E7EB"),
        bottom=Side(style="thin", color="E5E7EB"),
    )

    for i, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font      = Font(bold=True, color="FFFFFF", size=10)
        c.fill      = PatternFill("solid", fgColor=indigo)
        c.alignment = Alignment(horizontal="center")
        c.border    = thin
        ws.column_dimensions[c.column_letter].width = max(len(h) + 6, 14)

    for i, v in enumerate(example, 1):
        c = ws.cell(row=2, column=i, value=v)
        c.border    = thin
        c.alignment = Alignment(horizontal="left")
        c.fill      = PatternFill("solid", fgColor="F0FDF4")

    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=len(headers))
    note = ws.cell(row=3, column=1, value=fuentes_nota)
    note.font = Font(italic=True, size=8, color="6B7280")
    note.fill = PatternFill("solid", fgColor="FEF9C3")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="plantilla_leads.xlsx"'},
    )


@router.post("/preview")
async def preview_file(
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user),
):
    """Parsea el archivo y devuelve columnas + primeras filas para mapeo."""
    content = await file.read()
    if not content:
        raise HTTPException(400, "El archivo está vacío.")
    if len(content) > MAX_MB * 1024 * 1024:
        raise HTTPException(400, f"El archivo supera el límite de {MAX_MB} MB.")

    columns, rows = _parse_file(content, file.filename or "file")
    return {
        "columns":    columns,
        "preview":    rows[:MAX_PREVIEW],
        "total_rows": len(rows),
    }


def _run_dry_run(content: bytes, filename: str, col_map: dict, current_user: TokenData) -> dict:
    """Ejecuta la validación completa del archivo sin insertar nada.

    SRP: un solo responsable para el dry-run — lo usan tanto
    /preview-validated (para la UI) como /download-errors (para el export).
    Devuelve el mismo shape que /preview-validated.

    Lanza HTTPException 400 si el archivo excede MAX_ROWS.
    """
    _, all_rows = _parse_file(content, filename or "file")

    if len(all_rows) > MAX_ROWS:
        raise HTTPException(
            400,
            f"El archivo tiene {len(all_rows)} filas. El maximo por importacion es {MAX_ROWS}.",
        )

    # Cargar catalogo de fuentes y catalogo de asesores activos para resolucion.
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, nombre FROM crm.fuentes WHERE activo = TRUE")
            fuentes_db: dict[str, int] = {r["nombre"].lower(): r["id"] for r in cur.fetchall()}

            cur.execute(
                """SELECT id::text AS id,
                          TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre,
                          email
                   FROM auth.users
                   WHERE is_active = TRUE AND role IN ('asesor', 'supervisor', 'admin')"""
            )
            users_db: dict[str, str] = {}
            for r in cur.fetchall():
                nombre = r["nombre"]
                email = r["email"]
                if nombre:
                    users_db[nombre.lower()] = r["id"]
                if email:
                    users_db[email.lower()] = r["id"]

            allowed_asesor_ids = set()
            role = current_user.role
            if role == "supervisor":
                cur.execute(
                    """
                    SELECT id::text AS id
                    FROM auth.users
                    WHERE id = %s::uuid AND is_active = TRUE
                    UNION
                    SELECT a.id::text AS id
                    FROM crm.equipos eq
                    JOIN auth.users a ON a.id = eq.asesor_id AND a.is_active = TRUE
                    WHERE eq.activo = TRUE AND eq.supervisor_id = %s::uuid
                    """,
                    (current_user.user_id, current_user.user_id),
                )
                allowed_asesor_ids = {row["id"] for row in cur.fetchall()}

    # V028: catálogo de calidad + flag de obligatoriedad, una sola consulta.
    from app.routers.settings import load_carga_masiva_config
    calidad_codigos, calidad_aliases = _load_calidad_catalog()
    calidad_requerida = bool(load_carga_masiva_config().get("calidad_requerida", False))

    # Primera pasada: validacion + dedupe dentro del archivo
    result_rows: list[dict] = []
    valid_phones_for_db_check: list[str] = []
    seen_in_file: set[str] = set()

    for idx, raw_row in enumerate(all_rows, start=2):  # fila 2 = primera fila de datos
        mapped = _apply_map(raw_row, col_map)
        cleaned, errors = _validate_row(
            mapped,
            calidad_codigos=calidad_codigos,
            calidad_aliases=calidad_aliases,
            calidad_requerida=calidad_requerida,
        )

        # Validar asesor por fila
        asesor_raw = cleaned.get("asesor_raw")
        if role != "asesor" and asesor_raw and asesor_raw.strip():
            resolved_id = _resolve_asesor(asesor_raw, users_db)
            if not resolved_id:
                errors.append(f"Asesor '{asesor_raw}' no reconocido o inactivo")
            elif role == "supervisor" and resolved_id not in allowed_asesor_ids:
                errors.append(f"El asesor '{asesor_raw}' no está dentro de tu equipo permitido")

        # El "telefono" puede venir normalizado o no segun si hubo errores.
        telefono_out = cleaned.get("telefono") or (
            str(mapped.get("telefono") or "").strip() or None
        )
        fuente_raw = cleaned.get("fuente_raw")
        fuente_matched = (
            _resolve_fuente(fuente_raw, fuentes_db) is not None if fuente_raw else None
        )

        fecha_iso = cleaned.get("fecha").isoformat() if cleaned.get("fecha") else None

        base_payload = {
            "row": idx,
            "nombres":   cleaned.get("nombres") if cleaned.get("nombres") != "Sin nombre" else None,
            "apellidos": cleaned.get("apellidos"),
            "telefono":  telefono_out,
            "email":     cleaned.get("email"),
            "dni":       cleaned.get("dni"),
            "fuente":    fuente_raw,
            "fuente_matched": fuente_matched,
            "codigo_convenio": cleaned.get("codigo_convenio"),
            # Conservamos campos extra del mapeo para que el export los pueda usar
            "campana":       cleaned.get("campana"),
            "observaciones": cleaned.get("observaciones"),
            # V027: campos de carga masiva (gerencia)
            "fecha":      fecha_iso,
            "ciudad":     cleaned.get("ciudad"),
            "proyecto":   cleaned.get("proyecto"),
            "estrategia": cleaned.get("estrategia"),
            "calidad":    cleaned.get("calidad"),
            "asesor":     asesor_raw,
        }

        if errors:
            result_rows.append({**base_payload, "status": "error", "errors": errors})
            continue

        phone = cleaned["telefono"]
        if phone in seen_in_file:
            result_rows.append({
                **base_payload,
                "status": "duplicate_file",
                "errors": ["Telefono duplicado en el archivo"],
            })
            continue
        seen_in_file.add(phone)
        valid_phones_for_db_check.append(phone)

        # Provisional: si no hay match contra DB lo marcamos valido.
        result_rows.append({**base_payload, "status": "valid", "errors": []})

    # Segunda pasada: marcar duplicados contra la DB
    existing_phones: set[str] = set()
    if valid_phones_for_db_check:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT telefono FROM crm.leads "
                    "WHERE telefono = ANY(%s) AND activo = TRUE",
                    (valid_phones_for_db_check,),
                )
                existing_phones = {r[0] for r in cur.fetchall()}

    if existing_phones:
        for r in result_rows:
            if r["status"] == "valid" and r.get("telefono") in existing_phones:
                r["status"] = "duplicate_db"
                r["errors"] = ["Ya existe en el CRM"]

    summary = {
        "valid":           sum(1 for r in result_rows if r["status"] == "valid"),
        "duplicates_file": sum(1 for r in result_rows if r["status"] == "duplicate_file"),
        "duplicates_db":   sum(1 for r in result_rows if r["status"] == "duplicate_db"),
        "errors":          sum(1 for r in result_rows if r["status"] == "error"),
    }

    return {
        "total_rows": len(all_rows),
        "summary":    summary,
        "rows":       result_rows,
    }


def _parse_column_map(column_map: str) -> dict:
    """Parsea el JSON del column_map. Lanza HTTPException 400 si es invalido."""
    try:
        return json.loads(column_map)
    except Exception:
        raise HTTPException(400, "column_map invalido.")


def _validate_upload_content(content: bytes) -> None:
    """Valida tamaño y presencia del contenido del upload."""
    if not content:
        raise HTTPException(400, "El archivo esta vacio.")
    if len(content) > MAX_MB * 1024 * 1024:
        raise HTTPException(400, f"El archivo supera el limite de {MAX_MB} MB.")


@router.post("/preview-validated")
async def preview_validated(
    file: UploadFile = File(...),
    column_map: str = Form(...),
    current_user: TokenData = Depends(get_current_user),
):
    """Dry-run de la importación: valida todas las filas y revisa duplicados
    contra la DB, SIN insertar nada. Permite al usuario ver exactamente qué
    pasara antes de confirmar (cuantos listos, duplicados, con error).

    Devuelve:
        {
          total_rows: N,
          summary: {valid, duplicates_file, duplicates_db, errors},
          rows: [{row, status, nombres, apellidos, telefono, email, dni,
                  fuente, fuente_matched, errors}]
        }
    """
    content = await file.read()
    _validate_upload_content(content)
    col_map = _parse_column_map(column_map)
    return _run_dry_run(content, file.filename or "file", col_map, current_user)


@router.post("/download-errors")
async def download_errors(
    file: UploadFile = File(...),
    column_map: str = Form(...),
    current_user: TokenData = Depends(get_current_user),
):
    """Re-valida el archivo y genera un Excel con solo las filas problemáticas
    (errores, duplicados en archivo, duplicados en CRM) agrupadas en hojas
    separadas. Permite al usuario corregir offline y volver a subir.

    Una hoja por categoría: solo se incluye si hay filas en esa categoría,
    para no confundir con hojas vacías.
    """
    content = await file.read()
    _validate_upload_content(content)
    col_map = _parse_column_map(column_map)
    result = _run_dry_run(content, file.filename or "file", col_map, current_user)

    rows_by_status = {
        "error":          [r for r in result["rows"] if r["status"] == "error"],
        "duplicate_file": [r for r in result["rows"] if r["status"] == "duplicate_file"],
        "duplicate_db":   [r for r in result["rows"] if r["status"] == "duplicate_db"],
    }

    sheet_titles = {
        "error":          "Errores",
        "duplicate_file": "Duplicados en archivo",
        "duplicate_db":   "Duplicados en CRM",
    }

    # Si no hay problemas devolvemos 400 — no tiene sentido generar un excel vacio
    total_problems = sum(len(v) for v in rows_by_status.values())
    if total_problems == 0:
        raise HTTPException(400, "No hay filas problemáticas para exportar.")

    from openpyxl.styles import Font, PatternFill, Alignment

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # quitamos la hoja por defecto "Sheet"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="334155")  # slate-700
    header_align = Alignment(horizontal="left", vertical="center")

    columns = [
        ("Fila",          "row",           8),
        ("Fecha",         "fecha",         18),
        ("Nombres",       "nombres",       22),
        ("Apellidos",     "apellidos",     22),
        ("Teléfono",      "telefono",      16),
        ("Email",         "email",         28),
        ("Ciudad",        "ciudad",        16),
        ("Proyecto",      "proyecto",      18),
        ("Estrategia",    "estrategia",    22),
        ("Calidad",       "calidad",       12),
        ("Asesor",        "asesor",        18),
        ("Observaciones", "observaciones", 30),
        ("Motivo",        "_motivo",       60),
    ]

    for status_key, sheet_name in sheet_titles.items():
        rows = rows_by_status[status_key]
        if not rows:
            continue
        ws = wb.create_sheet(title=sheet_name)

        # Cabecera
        for col_idx, (label, _, width) in enumerate(columns, start=1):
            cell = ws.cell(row=1, column=col_idx, value=label)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            ws.column_dimensions[cell.column_letter].width = width

        # Filas
        for row_idx, r in enumerate(rows, start=2):
            motivo = "; ".join(r.get("errors") or []) or sheet_name
            values = {
                "row":           r.get("row"),
                "fecha":         r.get("fecha") or "",
                "nombres":       r.get("nombres") or "",
                "apellidos":     r.get("apellidos") or "",
                "telefono":      r.get("telefono") or "",
                "email":         r.get("email") or "",
                "ciudad":        r.get("ciudad") or "",
                "proyecto":      r.get("proyecto") or "",
                "estrategia":    r.get("estrategia") or "",
                "calidad":       r.get("calidad") or "",
                "asesor":        r.get("asesor") or "",
                "observaciones": r.get("observaciones") or "",
                "_motivo":       motivo,
            }
            for col_idx, (_, key, _width) in enumerate(columns, start=1):
                ws.cell(row=row_idx, column=col_idx, value=values[key])

        ws.freeze_panes = "A2"  # cabecera fija al hacer scroll

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    # Nombre del archivo con timestamp para no pisar descargas anteriores
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    download_name = f"problemas_carga_{ts}.xlsx"

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


@router.get("/asesores-disponibles")
def asesores_disponibles(current_user: TokenData = Depends(get_current_user)):
    """Lista los usuarios válidos como destinatarios de la carga masiva según rol.
    - asesor:     solo él mismo (forzado en backend, el front lo muestra como banner).
    - supervisor: él mismo + asesores activos de su equipo (crm.equipos).
    - admin:      todos los asesores + supervisores activos.
    """
    role = current_user.role
    uid  = current_user.user_id

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if role == "asesor":
                cur.execute(
                    """SELECT id::text AS id,
                              TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre,
                              email, role
                       FROM auth.users WHERE id = %s::uuid""",
                    (uid,),
                )
            elif role == "supervisor":
                cur.execute(
                    """
                    SELECT id::text AS id,
                           TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre,
                           email, role
                    FROM auth.users
                    WHERE is_active = TRUE AND id = %s::uuid
                    UNION
                    SELECT a.id::text AS id,
                           TRIM(COALESCE(a.first_name,'') || ' ' || COALESCE(a.last_name,'')) AS nombre,
                           a.email, a.role
                    FROM crm.equipos eq
                    JOIN auth.users a ON a.id = eq.asesor_id AND a.is_active = TRUE
                    WHERE eq.activo = TRUE AND eq.supervisor_id = %s::uuid
                    ORDER BY nombre
                    """,
                    (uid, uid),
                )
            else:  # admin
                cur.execute(
                    """SELECT id::text AS id,
                              TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre,
                              email, role
                       FROM auth.users
                       WHERE is_active = TRUE AND role IN ('asesor','supervisor','admin')
                       ORDER BY role, nombre"""
                )
            items = cur.fetchall()

    return {"role": role, "items": items}


@router.post("")
async def importar(
    file: UploadFile = File(...),
    column_map: str = Form(...),
    target_asesor_id: str = Form(""),
    current_user: TokenData = Depends(get_current_user),
):
    """Importa leads con validaciones completas."""
    content = await file.read()
    if not content:
        raise HTTPException(400, "El archivo está vacío.")
    if len(content) > MAX_MB * 1024 * 1024:
        raise HTTPException(400, f"El archivo supera el límite de {MAX_MB} MB.")

    try:
        col_map: dict = json.loads(column_map)
    except Exception:
        raise HTTPException(400, "column_map inválido.")

    _, all_rows = _parse_file(content, file.filename or "file")

    if len(all_rows) > MAX_ROWS:
        raise HTTPException(
            400,
            f"El archivo tiene {len(all_rows)} filas. El máximo por importación es {MAX_ROWS}. "
            "Divida el archivo en partes más pequeñas.",
        )

    # ── Resolver y validar target_asesor_id según rol ──
    role = current_user.role
    target = (target_asesor_id or "").strip() or None

    if role == "asesor":
        # El asesor siempre se auto-asigna, sin importar lo que envíe el front.
        target = current_user.user_id
    else:
        # Literal "pool" = sin asignar (solo admin). No se valida contra DB.
        if target and target.lower() == "pool":
            if role != "admin":
                raise HTTPException(403, "Solo admin puede usar 'pool' (sin asignar).")
            target = None
        # Supervisor / admin: si viene un target, debe estar dentro de su scope permitido.
        elif target:
            with get_db() as conn:
                with conn.cursor() as cur:
                    if role == "supervisor":
                        cur.execute(
                            """
                            SELECT 1
                            FROM auth.users u
                            WHERE u.id = %s::uuid AND u.is_active = TRUE
                              AND (
                                    u.id = %s::uuid
                                    OR EXISTS (
                                        SELECT 1 FROM crm.equipos eq
                                        WHERE eq.activo = TRUE
                                          AND eq.supervisor_id = %s::uuid
                                          AND eq.asesor_id = u.id
                                    )
                              )
                            """,
                            (target, current_user.user_id, current_user.user_id),
                        )
                    else:  # admin
                        cur.execute(
                            "SELECT 1 FROM auth.users WHERE id = %s::uuid AND is_active = TRUE",
                            (target,),
                        )
                    if not cur.fetchone():
                        raise HTTPException(
                            403,
                            "El asesor seleccionado no está dentro de tu scope permitido.",
                        )
        elif role == "admin":
            # Admin sin target_asesor_id explícito: rechazar para evitar cargas huérfanas.
            raise HTTPException(
                400,
                "Debes elegir un asesor destino o seleccionar 'Sin asignar (pool)'.",
            )

    # Cargar catálogos desde DB
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM crm.estados_lead WHERE nombre = 'Nuevo' LIMIT 1")
            row = cur.fetchone()
            if not row:
                raise HTTPException(500, "Estado 'Nuevo' no encontrado. Contacta al administrador.")
            estado_nuevo_id: int = row["id"]

            cur.execute("SELECT id, nombre FROM crm.fuentes WHERE activo = TRUE")
            fuentes_db: dict[str, int] = {r["nombre"].lower(): r["id"] for r in cur.fetchall()}

            # V065: catalogo de sedes — codigo Y nombre lowercased apuntan
            # al mismo uuid, asi el user puede usar slug ("lima") o nombre
            # ("Clinica Lima Centro") indistintamente.
            cur.execute(
                "SELECT id::text AS id, codigo, nombre FROM crm.sedes WHERE activo = TRUE"
            )
            sedes_db: dict[str, str] = {}
            for r in cur.fetchall():
                sedes_db[r["codigo"].lower()] = r["id"]
                if r.get("nombre"):
                    sedes_db[r["nombre"].lower()] = r["id"]

            # Cargar catálogo de usuarios/asesores activos para resolución
            cur.execute(
                """SELECT id::text AS id,
                          TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre,
                          email
                   FROM auth.users
                   WHERE is_active = TRUE AND role IN ('asesor', 'supervisor', 'admin')"""
            )
            users_db: dict[str, str] = {}
            for r in cur.fetchall():
                nombre = r["nombre"]
                email = r["email"]
                if nombre:
                    users_db[nombre.lower()] = r["id"]
                if email:
                    users_db[email.lower()] = r["id"]

            allowed_asesor_ids = set()
            if role == "supervisor":
                cur.execute(
                    """
                    SELECT id::text AS id
                    FROM auth.users
                    WHERE id = %s::uuid AND is_active = TRUE
                    UNION
                    SELECT a.id::text AS id
                    FROM crm.equipos eq
                    JOIN auth.users a ON a.id = eq.asesor_id AND a.is_active = TRUE
                    WHERE eq.activo = TRUE AND eq.supervisor_id = %s::uuid
                    """,
                    (current_user.user_id, current_user.user_id),
                )
                allowed_asesor_ids = {row["id"] for row in cur.fetchall()}

    # V028: catálogo de calidad + flag de obligatoriedad (reutiliza helpers).
    from app.routers.settings import load_carga_masiva_config
    calidad_codigos, calidad_aliases = _load_calidad_catalog()
    calidad_requerida = bool(load_carga_masiva_config().get("calidad_requerida", False))

    # Validar todas las filas
    valid_rows: list[dict] = []
    error_rows: list[dict] = []
    duplicates_details: list[dict] = []
    seen_phones: set[str]  = set()

    for idx, raw_row in enumerate(all_rows, start=2):  # fila 2 = primera fila de datos
        mapped = _apply_map(raw_row, col_map)
        cleaned, errors = _validate_row(
            mapped,
            calidad_codigos=calidad_codigos,
            calidad_aliases=calidad_aliases,
            calidad_requerida=calidad_requerida,
        )

        # Validar y resolver asesor por fila
        asesor_raw = cleaned.get("asesor_raw")
        row_asesor_id = None
        if role == "asesor":
            row_asesor_id = current_user.user_id
        else:
            if asesor_raw and asesor_raw.strip():
                resolved_id = _resolve_asesor(asesor_raw, users_db)
                if not resolved_id:
                    errors.append(f"Asesor '{asesor_raw}' no reconocido o inactivo")
                elif role == "supervisor" and resolved_id not in allowed_asesor_ids:
                    errors.append(f"El asesor '{asesor_raw}' no está dentro de tu equipo permitido")
                else:
                    row_asesor_id = resolved_id
            else:
                row_asesor_id = target

        telefono_out = cleaned.get("telefono") or str(mapped.get("telefono") or "").strip() or None

        if errors:
            error_rows.append({
                "row": idx,
                "nombres": cleaned.get("nombres") if cleaned.get("nombres") != "Sin nombre" else mapped.get("nombres"),
                "apellidos": cleaned.get("apellidos") or mapped.get("apellidos"),
                "telefono": telefono_out,
                "email": cleaned.get("email") or mapped.get("email"),
                "dni": cleaned.get("dni") or mapped.get("dni"),
                "error": "; ".join(errors),
                "motivo": "; ".join(errors),
            })
            continue

        phone = cleaned["telefono"]

        # Duplicado dentro del mismo archivo
        if phone in seen_phones:
            duplicates_details.append({
                "row": idx,
                "nombres": cleaned.get("nombres") if cleaned.get("nombres") != "Sin nombre" else mapped.get("nombres"),
                "apellidos": cleaned.get("apellidos") or mapped.get("apellidos"),
                "telefono": phone,
                "email": cleaned.get("email") or mapped.get("email"),
                "dni": cleaned.get("dni") or mapped.get("dni"),
                "error": f"Teléfono duplicado en el archivo: {phone}",
                "motivo": f"Teléfono duplicado en el mismo archivo ({phone})",
                "tipo": "archivo",
            })
            continue
        seen_phones.add(phone)

        cleaned["row"] = idx
        cleaned["fuente_id"] = _resolve_fuente(cleaned.pop("fuente_raw", None), fuentes_db)
        cleaned.pop("asesor_raw", None)
        cleaned["asesor_id"] = row_asesor_id
        cleaned["estado_id"] = estado_nuevo_id
        # V065: resolver sede_codigo → sede_id (uuid). NULL si no hay match.
        cleaned["sede_id"] = _resolve_sede(cleaned.pop("sede_raw", None), sedes_db)
        valid_rows.append(cleaned)

    if not valid_rows:
        # Registrar en historial aunque no haya filas válidas (p.ej. todas con error o duplicados).
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    _ensure_carga_masiva_schema(cur)
                    cur.execute(
                        """
                        INSERT INTO crm.carga_masiva_historial
                            (uploaded_by, uploaded_by_nombre, filename,
                             total_rows, inserted, duplicates, errors,
                             duplicates_details, error_details)
                        VALUES (%s::uuid, (
                            SELECT TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,''))
                            FROM auth.users WHERE id = %s::uuid
                        ), %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                        """,
                        (
                            current_user.user_id, current_user.user_id,
                            file.filename or "archivo",
                            len(all_rows), 0, len(duplicates_details), len(error_rows),
                            json.dumps(duplicates_details),
                            json.dumps(error_rows),
                        ),
                    )
                conn.commit()
        except Exception as e:
            logger.error("Error registrando historial (sin filas válidas): %s", e)
        return {
            "inserted":  0,
            "duplicates": len(duplicates_details),
            "errors":    len(error_rows),
            "error_rows": error_rows,
        }

    # Verificar duplicados contra la DB (por teléfono)
    phones = [r["telefono"] for r in valid_rows]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT telefono FROM crm.leads "
                "WHERE telefono = ANY(%s) AND activo = TRUE",
                (phones,),
            )
            existing_phones: set[str] = {r[0] for r in cur.fetchall()}

    to_insert: list[dict] = []
    for row in valid_rows:
        if row["telefono"] in existing_phones:
            duplicates_details.append({
                "row": row.get("row", "—"),
                "nombres": row.get("nombres"),
                "apellidos": row.get("apellidos"),
                "telefono": row.get("telefono"),
                "email": row.get("email"),
                "dni": row.get("dni"),
                "motivo": f"Teléfono ya registrado en el CRM ({row.get('telefono')})",
                "tipo": "crm",
            })
        else:
            to_insert.append(row)

    dup_count = len(duplicates_details)

    # Inserción por lotes
    # Nota: si `fecha` viene en el archivo, sobrescribe created_at (y también
    # updated_at para dejar ambos consistentes con la fecha real de origen).
    # Si no viene, se usa el DEFAULT NOW() del schema.
    inserted = 0
    insert_errors = 0
    for row in to_insert:
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    fecha_override = row.get("fecha")
                    sede_id_val = row.get("sede_id")
                    if fecha_override:
                        cur.execute(
                            """
                            INSERT INTO crm.leads
                                (nombres, apellidos, telefono, email, dni,
                                 ciudad, proyecto, estrategia, calidad, codigo_convenio,
                                 campana, observaciones, fuente_id, estado_id, asesor_id,
                                 sede_id,
                                 created_at, updated_at, activo)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                    %s, %s, %s, %s, %s::uuid,
                                    CASE WHEN %s::text IS NULL THEN NULL ELSE %s::uuid END,
                                    %s, %s, TRUE)
                            ON CONFLICT DO NOTHING
                            """,
                            (
                                row["nombres"], row["apellidos"], row["telefono"],
                                row["email"],   row["dni"],
                                row.get("ciudad"), row.get("proyecto"),
                                row.get("estrategia"), row.get("calidad"), row.get("codigo_convenio"),
                                row["campana"], row["observaciones"],
                                row["fuente_id"], row["estado_id"], row.get("asesor_id"),
                                sede_id_val, sede_id_val,
                                fecha_override, fecha_override,
                            ),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO crm.leads
                                (nombres, apellidos, telefono, email, dni,
                                 ciudad, proyecto, estrategia, calidad, codigo_convenio,
                                 campana, observaciones, fuente_id, estado_id, asesor_id,
                                 sede_id, activo)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                    %s, %s, %s, %s, %s::uuid,
                                    CASE WHEN %s::text IS NULL THEN NULL ELSE %s::uuid END,
                                    TRUE)
                            ON CONFLICT DO NOTHING
                            """,
                            (
                                row["nombres"], row["apellidos"], row["telefono"],
                                row["email"],   row["dni"],
                                row.get("ciudad"), row.get("proyecto"),
                                row.get("estrategia"), row.get("calidad"), row.get("codigo_convenio"),
                                row["campana"], row["observaciones"],
                                row["fuente_id"], row["estado_id"], row.get("asesor_id"),
                                sede_id_val, sede_id_val,
                            ),
                        )
                conn.commit()
                inserted += 1
        except Exception as e:
            logger.error("Error insertando lead %s: %s", row.get("telefono"), e)
            insert_errors += 1
            error_rows.append({
                "row": row.get("row", "—"),
                "nombres": row.get("nombres"),
                "apellidos": row.get("apellidos"),
                "telefono": row.get("telefono"),
                "email": row.get("email"),
                "dni": row.get("dni"),
                "error": f"Error DB: {row.get('telefono')}",
                "motivo": f"Error DB: {str(e)}",
            })

    # Registrar en historial de cargas masivas
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                _ensure_carga_masiva_schema(cur)
                cur.execute(
                    """
                    INSERT INTO crm.carga_masiva_historial
                        (uploaded_by, uploaded_by_nombre, filename,
                         total_rows, inserted, duplicates, errors,
                         duplicates_details, error_details)
                    VALUES (%s::uuid, (
                        SELECT TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,''))
                        FROM auth.users WHERE id = %s::uuid
                    ), %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                    """,
                    (
                        current_user.user_id, current_user.user_id,
                        file.filename or "archivo",
                        len(all_rows), inserted, dup_count,
                        len(error_rows),
                        json.dumps(duplicates_details),
                        json.dumps(error_rows),
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.error("Error registrando historial de carga masiva: %s", e)

    return {
        "inserted":   inserted,
        "duplicates": dup_count,
        "errors":     len(error_rows),
        "error_rows": error_rows,
    }


@router.get("/historial")
def listar_historial(
    limit: int = 50,
    current_user: TokenData = Depends(get_current_user),
):
    """Lista las últimas cargas masivas realizadas.
    - asesor:     solo sus propias cargas.
    - supervisor: cargas propias + las de los asesores de su equipo (crm.equipos).
    - admin:      todas las cargas."""
    limit = max(1, min(limit, 200))
    role  = current_user.role
    uid   = current_user.user_id
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_carga_masiva_schema(cur)
            if role == "asesor":
                cur.execute(
                    """
                    SELECT id, uploaded_by_nombre, filename,
                           total_rows, inserted, duplicates, errors, uploaded_at
                    FROM crm.carga_masiva_historial
                    WHERE uploaded_by = %s::uuid
                    ORDER BY uploaded_at DESC
                    LIMIT %s
                    """,
                    (uid, limit),
                )
            elif role == "supervisor":
                cur.execute(
                    """
                    SELECT id, uploaded_by_nombre, filename,
                           total_rows, inserted, duplicates, errors, uploaded_at
                    FROM crm.carga_masiva_historial
                    WHERE uploaded_by = %s::uuid
                       OR uploaded_by IN (
                            SELECT eq.asesor_id
                            FROM crm.equipos eq
                            WHERE eq.activo = TRUE
                              AND eq.supervisor_id = %s::uuid
                       )
                    ORDER BY uploaded_at DESC
                    LIMIT %s
                    """,
                    (uid, uid, limit),
                )
            else:  # admin
                cur.execute(
                    """
                    SELECT id, uploaded_by_nombre, filename,
                           total_rows, inserted, duplicates, errors, uploaded_at
                    FROM crm.carga_masiva_historial
                    ORDER BY uploaded_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
    for r in rows:
        if r.get("uploaded_at"):
            r["uploaded_at"] = r["uploaded_at"].isoformat()
    return {"items": rows}


@router.get("/historial/{historial_id}/detalles")
def obtener_detalles_historial(
    historial_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Retorna los detalles estructurados de duplicados y errores de una carga específica."""
    role = current_user.role
    uid  = current_user.user_id
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_carga_masiva_schema(cur)
            if role == "asesor":
                cur.execute(
                    """
                    SELECT id, uploaded_by_nombre, filename,
                           total_rows, inserted, duplicates, errors, uploaded_at,
                           COALESCE(duplicates_details, '[]'::jsonb) AS duplicates_details,
                           COALESCE(error_details, '[]'::jsonb) AS error_details
                    FROM crm.carga_masiva_historial
                    WHERE id = %s AND uploaded_by = %s::uuid
                    """,
                    (historial_id, uid),
                )
            elif role == "supervisor":
                cur.execute(
                    """
                    SELECT id, uploaded_by_nombre, filename,
                           total_rows, inserted, duplicates, errors, uploaded_at,
                           COALESCE(duplicates_details, '[]'::jsonb) AS duplicates_details,
                           COALESCE(error_details, '[]'::jsonb) AS error_details
                    FROM crm.carga_masiva_historial
                    WHERE id = %s
                      AND (
                            uploaded_by = %s::uuid
                            OR uploaded_by IN (
                                SELECT eq.asesor_id
                                FROM crm.equipos eq
                                WHERE eq.activo = TRUE AND eq.supervisor_id = %s::uuid
                            )
                      )
                    """,
                    (historial_id, uid, uid),
                )
            else:  # admin
                cur.execute(
                    """
                    SELECT id, uploaded_by_nombre, filename,
                           total_rows, inserted, duplicates, errors, uploaded_at,
                           COALESCE(duplicates_details, '[]'::jsonb) AS duplicates_details,
                           COALESCE(error_details, '[]'::jsonb) AS error_details
                    FROM crm.carga_masiva_historial
                    WHERE id = %s
                    """,
                    (historial_id,),
                )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Registro no encontrado o sin permisos.")
            if row.get("uploaded_at"):
                row["uploaded_at"] = row["uploaded_at"].isoformat()
            return row


@router.delete("/historial/{historial_id}")
def eliminar_historial(
    historial_id: int,
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Elimina un registro del historial de cargas masivas.
    Solo admin y supervisor. El supervisor solo puede eliminar entradas
    de su propio equipo (o propias). NO elimina los leads ya importados."""
    role = current_user.role
    uid  = current_user.user_id
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if role == "supervisor":
                cur.execute(
                    """
                    DELETE FROM crm.carga_masiva_historial
                    WHERE id = %s
                      AND (
                            uploaded_by = %s::uuid
                            OR uploaded_by IN (
                                SELECT eq.asesor_id FROM crm.equipos eq
                                WHERE eq.activo = TRUE AND eq.supervisor_id = %s::uuid
                            )
                      )
                    """,
                    (historial_id, uid, uid),
                )
            else:  # admin
                cur.execute(
                    "DELETE FROM crm.carga_masiva_historial WHERE id = %s",
                    (historial_id,),
                )
            deleted = cur.rowcount
        conn.commit()
    if deleted == 0:
        raise HTTPException(404, "Registro no encontrado o fuera de tu scope.")
    return {"deleted": True, "id": historial_id}
