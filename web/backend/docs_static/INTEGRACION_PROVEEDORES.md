# Integración de leads — API del CRM

> Documentación técnica para proveedores externos que ingestan leads al
> CRM (agencias, portales, partners, sistemas pre-calificadores con IA).

---

## Resumen

Endpoint REST que recibe un lead, valida tu API key, hace dedupe por teléfono
y asigna automáticamente a un asesor del equipo comercial. Una respuesta
exitosa significa que el lead quedó guardado y notificado al asesor.

| Concepto | Valor |
|---|---|
| **Base URL** | `{{CRM_BASE_URL}}` (te la entrega el admin del CRM) |
| **Endpoint** | `POST /api/ingest/leads` |
| **Auth** | Header `X-Api-Key: cli_xxxxxxxx_yyyyyyyy...` |
| **Content-Type** | `application/json` |
| **Codificación** | UTF-8 |

> **Nota:** en los ejemplos de este documento aparece el placeholder
> `{{CRM_BASE_URL}}`. Sustitúyelo por el dominio real del CRM al que
> integrarás (te lo provee el administrador del CRM cuando te entrega
> la API key). Si abres este documento desde el panel de Integraciones
> del CRM, el placeholder ya viene reemplazado automáticamente con
> el dominio activo.

---

## Autenticación

Cada request debe incluir el header:

```
X-Api-Key: cli_<prefix>_<secret>
```

Tu API key te la entrega el administrador del CRM. Tiene este formato:

```
cli_abcd1234_xY9KpL2HnVqRsTuWxYzAbCdEfGhIjKlMnO
```

**IMPORTANTE:**
- La key se muestra **una sola vez** al crearla. No se puede recuperar
  después. Si se pierde, debe regenerarse (la anterior queda invalidada).
- Nunca la compartas por canales no cifrados (Slack o email en texto plano).
  Usa un gestor de secretos (1Password, Bitwarden, Doppler, etc.).
- El servidor solo guarda un hash SHA-256 de la key — nadie en el equipo
  del CRM puede ver tu secret.

---

## Body de la petición

```json
{
  "fuente":             "string (obligatorio)",
  "telefono":           "string (obligatorio, identificador para dedupe)",

  "nombres":            "string (opcional)",
  "apellidos":          "string (opcional)",
  "nombre_completo":    "string (opcional, fallback si no separas nombre+apellido)",
  "apellido":           "string (opcional, alias singular para tu schema interno)",

  "email":              "string (opcional)",
  "dni":                "string (opcional)",
  "campana":            "string (opcional, nivel Campaign de Meta Ads)",
  "conjunto":           "string (opcional, nivel Ad Set de Meta Ads)",
  "anuncio":            "string (opcional, nivel Ad de Meta Ads)",
  "fuente_externa_id":  "string (opcional, tu ID interno del lead — clave de idempotencia)",
  "external_created_at":"string (opcional, ISO 8601 — timestamp REAL cuando el cliente llenó el form)",
  "form_name":          "string (opcional, nombre del formulario que llenó el cliente)",

  "nivel":              "string (opcional, 'Nuevo' | 'Contactado')",
  "asesor_telefono":    "string (opcional, pre-asignación a asesor por teléfono)",
  "resumen_ia":         "string (opcional, transcripción/resumen de conversación con tu IA)",

  "observaciones":      "string (opcional, comentarios libres)",
  "extra":              "object (opcional, campos custom — se guardan en datos_extra JSONB)"
}
```

### Campos

#### Identificación (obligatorios)

| Campo | Tipo | Notas |
|---|---|---|
| `fuente` | string | **Fuente de origen del lead** — el canal o medio desde donde vino el cliente (`instagram`, `facebook`, `tiktok`, `whatsapp`, `manual`, `referido`, etc.). Debe coincidir (case-insensitive) con un valor del catálogo de fuentes del CRM, sino se rechaza con 400. Tu identificación como proveedor se preserva automáticamente vía la API key — **no se pierde quién entregó el lead**. |
| `telefono` | string | **Clave de dedupe.** Si ya existe ese teléfono en el CRM, se devuelve `duplicated:true` con el ID del lead existente. Acepta formatos `+51999888777`, `999888777`, `+51 999 888 777`. |

#### Datos del cliente

| Campo | Tipo | Notas |
|---|---|---|
| `nombres` | string | Primer nombre o nombre simple del cliente. |
| `apellidos` | string | Apellidos del cliente. |
| `nombre_completo` | string | **Fallback** si tu sistema no separa nombre+apellido. Si se manda, el CRM hace split automático en el primer espacio. |
| `apellido` | string | Alias singular. Si tu schema interno usa "apellido" en singular (típico en algunos proveedores), se acepta — el CRM lo trata como `apellidos` cuando este último viene vacío. |
| `email` | string | Si no es un email válido, se devuelve 400. |
| `dni` | string | Documento de identidad. **Dato sensible bajo Ley 29733 (Perú)** — solo enviar con consentimiento explícito del cliente. |

#### Atribución de marketing (jerarquía Meta Ads)

Si tu fuente es Facebook/Instagram Lead Ads o un proveedor que opera Meta Ads, te recomendamos enviar los **3 niveles de la jerarquía** para que los reportes de attribution funcionen bien:

| Campo | Tipo | Notas |
|---|---|---|
| `campana` | string | Nivel **Campaign** de Meta Ads. Ej: `Promo Mayo 2026`. |
| `conjunto` | string | Nivel **Ad Set** de Meta Ads. Ej: `Geolocalizado + interés 25-45`. |
| `anuncio` | string | Nivel **Ad** de Meta Ads. Ej: `LEAD AD - FACHADA`. |
| `fuente_externa_id` | string | Tu ID interno del lead (Meta `leadgen_id`, TikTok `lead_id`, etc.). Se usa también como **clave de idempotencia** — si reintegrás dos veces el mismo `fuente_externa_id`, no se crea duplicado y tampoco se infla el contador de reactivaciones. |
| `external_created_at` | string ISO 8601 | **Timestamp REAL** de cuándo el cliente llenó tu formulario (no cuándo lo enviás al CRM). Formato `"2026-05-13T14:32:18Z"` o con offset `"2026-05-13T09:32:18-05:00"`. Habilita el **Backfill Protection** del CRM: si re-entregás un lead viejo, no se cuenta como una reactivación falsa. |
| `form_name` | string | Nombre del formulario que llenó el cliente. Aparece en la ficha del lead. |

> **💡 Recomendación importante (Idempotencia + Backfill Protection):**
> Aunque ambos campos son opcionales, **enviar siempre los dos** `fuente_externa_id` + `external_created_at` evita que reintentos, re-polling o re-imports inflen falsamente el contador de "reactivaciones" del cliente. El CRM solo cuenta una reactivación cuando el `fuente_externa_id` es nuevo Y el `external_created_at` es posterior a la creación del lead en el CRM.

#### Lead pre-calificado (proveedores con IA)

Si tu sistema **pre-calificó al cliente con una IA** antes de entregarlo al CRM (proveedores tipo lead nurturing automatizado), agrega estos campos para que el asesor humano vea el contexto al abrir el lead:

| Campo | Tipo | Notas |
|---|---|---|
| `nivel` | string | Estado inicial declarado por tu sistema. **Allowlist estricta**: solo `"Nuevo"` o `"Contactado"`. Cualquier otro valor se ignora y el lead entra como `Nuevo`. NO se permite saltar a estados terminales (Ganado/Perdido) — eso lo decide el asesor humano. |
| `asesor_telefono` | string | **Pre-asignación.** Si tu sistema decide qué asesor del equipo comercial maneja el lead (ej. tu IA lo emparejó con un asesor específico), envía aquí su teléfono. El CRM busca por sufijo de 9 dígitos en el directorio de asesores activos. Si encuentra match → asigna directo. Si no → cae al routing automático normal del CRM. |
| `resumen_ia` | string | Transcripción o resumen de la conversación previa con tu IA. Se muestra al asesor humano en la ficha del lead, en una sección destacada con icono 🤖. Texto libre, multilínea, máx. ~5KB. |

#### Otros

| Campo | Tipo | Notas |
|---|---|---|
| `observaciones` | string | Texto libre. Aparece en la ficha del lead, separado del `resumen_ia`. |
| `extra` | object | Campos custom propios de tu integración (ej. `{"habitaciones": "sí", "presupuesto_max": 250000}`). Se guardan en `datos_extra` (JSONB) y se muestran al asesor en la ficha como bloque JSON. |

---

## Idempotency-Key (recomendado)

Si tu sistema reintenta peticiones (timeouts de red, etc.), agrega el
header `Idempotency-Key`:

```
Idempotency-Key: lead-12345-2026-05-05
```

Si el servidor recibe el mismo `Idempotency-Key` dentro de las próximas
24 horas, devuelve exactamente la misma respuesta sin crear un lead
nuevo. Recomendado: usa tu propio `lead_id` interno + fecha.

---

## Comportamiento al reenviar un lead duplicado

Si reenvías un lead cuyo teléfono **ya existe** en el CRM, **nunca se crea
un lead nuevo**. El CRM verifica antes de cualquier escritura y decide
qué hacer según el contexto. Esta sección explica los 6 escenarios
reales y exactamente qué campos toca (y cuáles no).

### Los 6 escenarios

| # | Cuándo aplica | Qué hace el CRM | Respuesta |
|---|---|---|---|
| **1. Re-import** | Reenvías el **mismo `fuente_externa_id`** que ya procesaste antes | Skip completo. No toca nada del lead. | `200` + `duplicated:true, reason:"fext_already_processed", skipped:true` |
| **2. Lead eliminado** | El `fuente_externa_id` apunta a un lead **soft-deleted** del CRM | Skip. NO resucita leads eliminados por reintento de tu polling. | `200` + `duplicated:true, reason:"fext_lead_deleted", skipped:true` |
| **3. Re-submission del día** | Mismo teléfono, lead **creado hoy** (zona horaria America/Lima) | Skip. Es ruido del polling, no reactivación real. | `200` + `duplicated:true, reason:"same_day_resubmission", skipped:true` |
| **4. Backfill viejo** | Mandas `external_created_at` **anterior o igual** a la fecha de creación del lead | Skip. El evento del proveedor es viejo, no cuenta como reactivación. | `200` + `duplicated:true, backfill_skip:true` |
| **5. Recontacto real** | Mismo teléfono + lead creado en día anterior + `fuente_externa_id` nuevo | Registra evento de recontacto, rellena campos vacíos del lead, notifica al asesor original. | `200` + `duplicated:true, recontacto:true, estrategia:"mantener_asesor", recontacto_id:N` |
| **6. Lead nuevo** | El teléfono **no existe** en el CRM | Crea el lead, lo asigna y notifica. | `201` + `duplicated:false, id, asesor_id, supervisor_id` |

### Qué campos se actualizan en el caso 5 (recontacto real)

El CRM es **conservador a propósito**: si el asesor humano ya editó la
ficha del lead, no se pisa lo que él trabajó. En un recontacto solo se
rellenan campos que estén **vacíos** en el lead original:

| Campo del lead | Se actualiza solo si... |
|---|---|
| `email` | el lead tenía `email` vacío o `NULL` |
| `nombres` | el lead tenía `nombres` vacío, `NULL` o decía literalmente `"Sin nombre"` |
| `apellidos` | el lead tenía `apellidos` vacío o `NULL` |

**Nada más del lead se modifica** — aunque lo mandes en el payload.

### Qué NO se actualiza nunca

Estos campos del lead original quedan intactos en cualquier reenvío,
incluso si tu payload trae valores distintos:

- `telefono` — es la clave de dedupe, por definición ya coincide.
- `fuente_id` — la fuente del lead original se preserva (la fuente del recontacto queda en `crm.lead_recontactos`, aparte).
- `estado_id` — el estado del pipeline lo controla el asesor humano, no el ingest.
- `supervisor_id` y `asesor_id` — la asignación se mantiene (ver siguiente sub-sección).
- `dni`, `campana`, `anuncio`, `conjunto`, `observaciones`, `resumen_ia`, `datos_extra` — todo lo que el lead ya tenía queda como está.

### Asignación del asesor en recontacto

El principio del CRM es: **el asesor que invirtió tiempo en el lead se
queda con el lead**. Por defecto, la asignación no cambia. Solo hay una
excepción operativa:

| Condición del asesor original | Qué pasa |
|---|---|
| Sigue activo (`is_active = TRUE`) | Se mantiene. Recibe push: *"{Cliente} volvió a interesarse vía {fuente}"*. |
| Ya no está activo (`is_active = FALSE`) | Se libera el lead (`asesor_id = NULL`) y entra al pool del supervisor para reasignar en el siguiente turno. |

### Dónde queda registrado el recontacto

Cada evento del caso 5 se persiste en una tabla de auditoría aparte
(`crm.lead_recontactos`) con: fuente del recontacto, campaña, tu
`fuente_externa_id`, asesor mantenido / anterior, estrategia aplicada y
razón. Así puedes ver el historial completo de touchpoints del cliente
sin que ningún reenvío sobrescriba la información trabajada del lead
original.

### Cómo evitar contadores inflados de reactivaciones

Manda siempre `fuente_externa_id` + `external_created_at`. Con esos dos
campos el CRM puede distinguir entre:

- Re-polling o reintento de tu sistema → casos 1, 2 o 4 → **skip silencioso**.
- Cliente que llenó un formulario nuevo o respondió otro anuncio → caso 5 → **recontacto real** registrado.

Sin esos campos, el CRM no puede diferenciar y un re-poll del mismo
lead puede contarse como reactivación que no ocurrió.

---

## Respuestas

### 201 — lead creado

```json
{
  "duplicated":    false,
  "id":            12345,
  "mode":          "round_robin",
  "asesor_id":     "uuid-del-asesor-asignado",
  "supervisor_id": "uuid-del-supervisor-asignado"
}
```

### 200 — lead duplicado (mismo teléfono ya existía)

```json
{
  "duplicated": true,
  "id":          12345,
  "mode":        "duplicate"
}
```

> El lead **no se crea** ni se reasigna. Esto es seguro: puedes reintentar
> sin riesgo de duplicar.

### 400 — datos inválidos

```json
{ "detail": "telefono es requerido" }
```

### 401 — auth falló

```json
{ "detail": "API key invalida." }
{ "detail": "API key revocada." }
{ "detail": "API key expirada." }
```

### 403 — IP no autorizada

```json
{ "detail": "IP 200.10.20.30 no esta en la whitelist." }
```

### 429 — rate limit excedido

```json
{ "detail": "Rate limit excedido (60/min). Intenta en 60s." }
```

Espera 60 segundos antes del siguiente request.

### 500 — error interno

```json
{ "detail": "..." }
```

Reintenta con backoff exponencial (1s, 2s, 4s, 8s).

---

## Ejemplos

### curl (Linux/Mac/PowerShell)

```bash
curl -X POST {{CRM_BASE_URL}}/api/ingest/leads \
  -H "X-Api-Key: cli_abcd1234_xY9KpL2HnVqRsTuWxYzAbCdEfGhIjKlMnO" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: lead-12345" \
  -d '{
    "fuente": "inmuebles24",
    "telefono": "+51 999 888 777",
    "nombres": "Juan",
    "apellidos": "Pérez",
    "email": "juan@ejemplo.com",
    "campana": "promo-mayo-2026",
    "fuente_externa_id": "INM-99887",
    "external_created_at": "2026-05-13T14:32:18Z",
    "observaciones": "Interesado en 3 dorms, presupuesto 250k USD"
  }'
```

### Python (requests)

```python
import requests
from datetime import datetime, timezone

URL = "{{CRM_BASE_URL}}/api/ingest/leads"
HEADERS = {
    "X-Api-Key": "cli_abcd1234_xY9KpL2HnVqRsTuWxYzAbCdEfGhIjKlMnO",
    "Content-Type": "application/json",
    "Idempotency-Key": f"lead-{my_internal_id}",
}
payload = {
    "fuente": "inmuebles24",
    "telefono": "+51 999 888 777",
    "nombres": "Juan",
    "apellidos": "Pérez",
    "email": "juan@ejemplo.com",
    "campana": "promo-mayo-2026",
    "fuente_externa_id": str(my_internal_id),
    # Timestamp REAL de cuando el cliente lleno tu form (no cuando lo envias al CRM)
    "external_created_at": form_submitted_at.astimezone(timezone.utc).isoformat(),
}

r = requests.post(URL, json=payload, headers=HEADERS, timeout=10)
r.raise_for_status()
data = r.json()
if data["duplicated"]:
    print(f"Lead ya existía con id={data['id']}")
else:
    print(f"Lead creado id={data['id']} asignado a asesor {data['asesor_id']}")
```

### Node.js (fetch)

```js
const res = await fetch(
  "{{CRM_BASE_URL}}/api/ingest/leads",
  {
    method: "POST",
    headers: {
      "X-Api-Key": "cli_abcd1234_xY9KpL2HnVqRsTuWxYzAbCdEfGhIjKlMnO",
      "Content-Type": "application/json",
      "Idempotency-Key": `lead-${myInternalId}`,
    },
    body: JSON.stringify({
      fuente: "inmuebles24",
      telefono: "+51 999 888 777",
      nombres: "Juan",
      apellidos: "Pérez",
      email: "juan@ejemplo.com",
      campana: "promo-mayo-2026",
      fuente_externa_id: String(myInternalId),
      // Timestamp REAL del lead en tu sistema (ISO 8601, recomendado)
      external_created_at: formSubmittedAt.toISOString(),
    }),
  }
)
const data = await res.json()
if (!res.ok) throw new Error(data.detail)
console.log(data)
```

### PowerShell

```powershell
$headers = @{
  "X-Api-Key" = "cli_abcd1234_xY9KpL2HnVqRsTuWxYzAbCdEfGhIjKlMnO"
  "Idempotency-Key" = "lead-12345"
}
$body = @{
  fuente = "inmuebles24"
  telefono = "+51 999 888 777"
  nombres = "Juan"
  apellidos = "Perez"
  email = "juan@ejemplo.com"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "{{CRM_BASE_URL}}/api/ingest/leads" `
  -Method Post `
  -Headers $headers `
  -Body $body `
  -ContentType "application/json"
```

---

### Ejemplo completo: proveedor con IA pre-calificadora

Si tu sistema operó leads de Facebook/Instagram Lead Ads, los pre-calificó con IA y nos los entregás al CRM:

```bash
curl -X POST {{CRM_BASE_URL}}/api/ingest/leads \
  -H "X-Api-Key: cli_abcd1234_xY9KpL2HnVqRsTuWxYzAbCdEfGhIjKlMnO" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 1533626621867548" \
  -d '{
    "fuente":              "instagram",
    "telefono":            "+51999888777",
    "nombres":             "María",
    "apellidos":           "García",
    "email":               "maria.garcia@ejemplo.com",
    "dni":                 "10607829",

    "campana":             "Promo Mayo 2026",
    "conjunto":            "Geolocalizado + interés 25-45",
    "anuncio":             "LEAD AD - FACHADA",
    "fuente_externa_id":   "1533626621867548",
    "external_created_at": "2026-05-13T14:32:18Z",
    "form_name":           "Formulario informativo Mayo",

    "nivel":               "Contactado",
    "asesor_telefono":     "51987291111",
    "resumen_ia":          "El cliente mostró interés inicial por el proyecto, preguntando características clave del producto y solicitando información de precios.",

    "extra": {
      "preferencia":       "premium",
      "presupuesto_max":   "250000"
    }
  }'
```

**Qué pasa en el CRM al recibir esto:**

1. Se valida la API key + IP whitelist + rate limit + idempotencia.
2. Se busca por `telefono`. Si ya existe un lead activo con ese teléfono, **no se crea duplicado** — se intenta re-engagement (Lead Recapture pattern) y se devuelve `duplicated:true`.
3. Se parsean nombres con tolerancia (`nombres + apellidos`, fallback a `nombre_completo`, fallback a `apellido` singular).
4. Se persisten todos los campos en `crm.leads` (nombres, telefono, email, dni, campana, **conjunto**, **anuncio**, fuente_externa_id, form_name, **resumen_ia**) y los campos custom en `datos_extra` JSONB.
5. **Atribución de origen**: `fuente` se mapea al canal real (Instagram, en este ejemplo) y queda guardada para que aparezca en la columna **"Fuente"** del CRM. **Tu identidad como proveedor** se preserva por separado, así el CRM puede mostrar reportes de "leads por fuente" vs "leads por proveedor".
6. El estado inicial es `Contactado` (porque `nivel` está en la allowlist).
7. Si `asesor_telefono` matchea un asesor activo del CRM, se asigna directo a ese asesor. Si no matchea (campo vacío o teléfono no encontrado) cae al routing automático normal.
8. Push notification al asesor asignado.
9. El asesor humano abre el lead y ve la transcripción de tu IA en una sección destacada con icono 🤖, antes de hacer el primer contacto.

---

## Buenas prácticas

1. **Reintentos:** ante 5xx o timeout, usa backoff exponencial
   (1s, 2s, 4s, 8s, 16s) hasta 5 intentos. Después detente.
2. **Idempotency-Key siempre:** evita duplicar al reintentar.
3. **No registres la X-Api-Key en logs.** Si la guardas en archivos de
   log, enmascárala como `cli_xxxxxxxx_***`.
4. **Rota la key periódicamente.** Cada 6 a 12 meses, solicita al CRM
   un regenerate.
5. **Valida los teléfonos antes de enviar.** El formato E.164
   (`+51999888777`) minimiza falsos duplicados por whitespace o formato.
6. **Si tu IP es estática**, solicita al CRM que la agregue al
   `ip_whitelist` de tu key — capa extra de seguridad.

---

## Soporte

| Caso | Contacto |
|---|---|
| Problemas con la key (regenerar, revocar, IP whitelist) | Administrador del CRM |
| Errores 5xx persistentes | Soporte técnico del CRM |
| Cambios de campos o nuevas integraciones | Administrador del CRM |

---

**Versión del documento:** 1.5 · Mayo 2026

**Cambios:**
- v1.5 (2026-05-07) — Terminología UI unificada a **"Fuente"** en toda
  la documentación, web y mobile. Se eligió "Fuente" por ser semánticamente
  correcta para todos los items del catálogo (incluye plataformas
  digitales como Facebook/Instagram, pero también canales offline como
  referidos y ferias). Es el estándar de la industria (Salesforce,
  Zoho, Microsoft Dynamics).
- v1.4 (revertido) — intento previo de usar "Plataforma" en UI.
  Inexacto cuando el catálogo incluye items que no son plataformas
  (referido, feria, manual, etc.).
- v1.3 (2026-05-07) — Corregida la semántica del campo `fuente`. Ahora
  representa el canal de origen del lead (instagram/facebook/tiktok/etc.),
  no el slug del proveedor. La atribución al proveedor se preserva
  automáticamente vía `api_client_id`. Esto unifica el modelo con los
  demás drivers (carga masiva, formularios, Meta nativo, etc.) y
  permite reportes correctos por canal.
- v1.2 (2026-05-07) — Documento generalizado: removidas referencias
  hardcodeadas a empresa cliente y dominio específico de deploy. Ahora
  usa el placeholder `{{CRM_BASE_URL}}` que se reemplaza dinámicamente
  cuando el doc se sirve desde el panel de Integraciones del CRM.
- v1.1 (2026-05-07) — V053: nuevos campos opcionales para proveedores con
  IA pre-calificadora: `dni`, `conjunto`, `anuncio`, `nombre_completo`,
  `apellido` (singular), `nivel`, `asesor_telefono`, `resumen_ia`, `extra`.
  Retrocompatible: integraciones existentes siguen funcionando sin cambios.
- v1.0 — Primera versión.
