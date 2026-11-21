# Migraciones SQL — guía y convenciones

Este directorio contiene las migraciones SQL del CRM. Se aplican
automáticamente al arranque del backend via `app/db_migrator.py`.

---

## Convención de nombres

### Patrón estricto

```
V<numero>[_<sub>]_<descripcion_snake_case>.sql
```

**Ejemplos válidos:**
- `V070_chat_asesor_inherit_from_lead.sql` → versión `V070`
- `V070_1_chat_asesor_inherit_by_phone.sql` → versión `V070_1` (sub-migración)
- `V070_2_chat_asesor_robust_inherit.sql` → versión `V070_2`
- `V071_user_notification_prefs.sql` → versión `V071`

### Regla crítica (V070.60 — bug histórico)

**Cada versión es ÚNICA en el tracker.** Si ya existe `V071_base.sql`,
NO crear otro `V071_otra_feature.sql` — colisionarían en la clave
`V071` del tracker y la segunda migración se silenciaría en producción.

El migrator detecta colisiones al arranque (V070.64) y lanza
`RuntimeError` con mensaje explícito antes de aplicar nada.

**Si necesitas un hotfix sobre una versión ya en producción:**
- Crear con sub-número: `V071_2_fix_xxx.sql`, `V071_3_otro_xxx.sql`
- NO renombrar la migración base — eso rompe el tracker en deploys
  ya aplicados.

---

## Estado actual (mayo 2026)

### Archivos presentes
Ver `ls web/backend/migrations/V*.sql` para la lista actual.

### Gaps de numeración (intencionales o eliminados)

Las siguientes versiones NO existen en este directorio. Documentación
del por qué (cuando se sabe) para evitar confusión al onboardear:

| Versión faltante | Razón |
|---|---|
| `V001_create_users.sql` | Existe, pero con nombre legacy `001_create_users.sql` (numeración antigua sin "V"). Se mantiene para compat con tracker viejo. NO renombrar. |
| `V002` – `V039` | Migrations del MVP original aplicadas vía scripts manuales en 2024-2025 antes de introducir el auto-migrator. Esquema base ya está en producción. Nunca se versionaron en este directorio. |
| `V049`, `V050` | Reservadas en su momento para features que se mergearon dentro de otras migraciones (V048 + V051). Skip intencional. |
| `V054` | Renombrada como `V053_provider_lead_fields.sql` antes de mergear el PR. Skip intencional. |
| `V057` | Saltada por error de typo en PR original. Sin migración en este número — el siguiente PR usó V058. Skip aceptado. |
| `V060`, `V061` | Refactor descartado de webhook outbound (V058 + V059 cubrieron el alcance). Skip intencional. |
| `V064` | Renombrada como `V065_sedes.sql` para alinear con la fecha del PR de release. Skip intencional. |
| `V069` | Refactor de chat-asesor descartado (V070 + V070_1/2/3 cubrieron el alcance). Skip intencional. |

### Idempotencia obligatoria

Toda migración nueva DEBE ser idempotente:
- `CREATE TABLE IF NOT EXISTS ...`
- `ADD COLUMN IF NOT EXISTS ...`
- `CREATE INDEX IF NOT EXISTS ...`
- `INSERT ... ON CONFLICT DO NOTHING`
- `DROP TABLE IF EXISTS ...`

Razón: el `auto_migrator` tiene un tracker (`crm.schema_migrations`) que
NO debería re-aplicar migraciones ya corridas. Pero si por alguna razón
se ejecuta dos veces (rebuild de DB, restore, ambiente nuevo, etc.), no
debe fallar.

### Defense in depth

Algunas migraciones críticas (V068.4 — columna `external_created_at`)
tienen un **safety net** en `bootstrap.py` (función `ensure_*_schema()`)
que se ejecuta en cada arranque. Esto cubre el caso de que el migrator
falle por algún motivo (bug del regex, archivo corrupto, etc).

---

## Workflow para agregar una migración nueva

1. Mirar el último número existente: `ls V*.sql | sort | tail -5`
2. Crear archivo con el **siguiente número libre** y descripción:
   - Si es feature nueva → `V<N+1>_descripcion_snake.sql`
   - Si es hotfix sobre una migración reciente → `V<N>_<sub>_descripcion.sql`
3. Escribir DDL **idempotente** (ver arriba).
4. Probar localmente: levantar el backend, verificar que `[migrator] OK V<N>` aparece en logs.
5. Commit con mensaje: `db(V<N>): descripcion + por_qué`
6. Push → EasyPanel re-deploya → migrator la aplica en producción.

### Si tu migración tarda más de 30s

Aplicarla manualmente en una ventana de mantenimiento. El auto-migrator
bloquea el startup del backend hasta que termina. Para migraciones largas
(ej. `UPDATE ... SET` sobre tablas grandes), considerar:
- Hacer la migración estructural primero (rápido)
- Hacer el backfill de datos en un script separado, idealmente en
  batches con `LIMIT/OFFSET` o con `CTE` recursiva.

---

## Troubleshooting

### "COLISION DE VERSION" al startup
El migrator detectó dos archivos con la misma clave (V070.64). Renombrá
uno de los dos con sub-versión. Mensaje en logs:
```
[migrator] COLISION DE VERSION: 'V071' aparece en dos archivos:
'V071_base.sql' y 'V071_otra.sql'. Renombra uno con sub-version
(ej: V071_2_descripcion.sql)
```

### "FAILED V<N>" al startup
La migración tiró error SQL. Mirar el log completo. El migrator detiene
la cadena pero el backend SIGUE arrancando con migraciones parciales
aplicadas — corregir y redeployar lo antes posible.

### Una migración no se aplicó pero el tracker dice OK
Caso histórico (V068_4): el regex viejo del migrator no distinguía
sub-versiones, las silenciaba. Fix aplicado en V070.60. Si dudas si una
migración corrió, comprobar manualmente:

```sql
SELECT * FROM crm.schema_migrations WHERE version = 'V068_4';
```

Si no aparece, re-aplicar manualmente la migración (es idempotente, no
romperá nada).
