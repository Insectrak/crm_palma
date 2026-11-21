# Pruebas de Aceptación — Web CRM Palma Río v3.1

**Persona que prueba:** _______________
**Fecha:** _______________
**Navegador / versión:** _______________
**URL probada:** `https://brighton-crm-brighton.l7weu8.easypanel.host`

> **Objetivo**: certificar que la web está lista para que admin, supervisores y asesores la usen en producción. Cada bloque debe terminar con todos los checkboxes marcados. Si un check falla, anotarlo en **Incidencias** al final con severidad alta / media / baja.
>
> **Cambios desde v3.0**: integraciones (Meta / TikTok / WABAs), templates WhatsApp con vista previa + tooltip de error Meta, auditoría de paridad mobile/web (`MODULES.md`), coherencia semántica de KPIs (cumulativos vs exclusivos vs transversales), pantalla Históricos.

---

## Antes de empezar

- [ ] Tres cuentas activas (pedir a Soporte si no las tienes):
  - **Admin**
  - **Supervisor** (Paola o Darwin)
  - **Asesor**
- [ ] Acceso a la APK del CRM en un celular para verificaciones cruzadas
- [ ] Limpiar el cache del navegador antes de empezar (`Ctrl+Shift+Del` → última hora)
- [ ] Hard refresh con `Ctrl+Shift+R` para no caer en service worker viejo
- [ ] Abrir DevTools (F12) → tab Console + Network — dejar abierto durante toda la prueba para capturar errores

---

## PARTE 1 — Login y sesión

**Prueba 1.1 — Página de login**

1. Abrir la URL en una ventana privada / incógnito
2. Observar la pantalla

- [ ] Logo y nombre de marca visibles
- [ ] Campos email + contraseña vacíos
- [ ] Botón "Ingresar" visible
- [ ] Sin errores en consola

**Prueba 1.2 — Login admin**

1. Ingresar credenciales del admin

- [ ] Entra al Dashboard
- [ ] Sidebar muestra: Dashboard, Leads, Agenda, Chat, Llamadas, Carga Masiva, Asignación, Formularios, Reportes, Históricos, Reparto leads, Configuración, Integraciones
- [ ] Esquina inferior izquierda muestra **Admin CRM · Admin** (rol activo)

**Prueba 1.3 — Logout y cambio de rol**

1. Click en `Cerrar sesión`
2. Login como **Supervisor**

- [ ] Menú reducido: NO ve "Carga Masiva", "Reparto leads", "Integraciones"
- [ ] Solo ve datos de su equipo en Dashboard, Leads, Reportes

3. Logout, login como **Asesor**

- [ ] Menú reducido aún más (sin Asignación, sin Reportes globales, sin Integraciones, sin Históricos editable)
- [ ] Solo ve sus propios leads

**Prueba 1.4 — Sesión persistente**

1. Cerrar la pestaña sin hacer logout
2. Reabrir la URL en una nueva pestaña

- [ ] La sesión sigue activa, no pide login otra vez
- [ ] Si se vence el JWT (cambiar `ACCESS_TOKEN_EXPIRE_HOURS=0` no es viable; verificar pasivamente), redirige al login

---

## PARTE 2 — Dashboard

**Prueba 2.1 — KPIs principales**

- [ ] Número de leads totales
- [ ] Leads del día / semana / mes
- [ ] Tasa de conversión visible
- [ ] Gráfico de tendencia visible y se actualiza al cambiar el rango

**Prueba 2.2 — Coherencia semántica del pipeline (CRÍTICO post-v5.42.x)**

> ⚠️ **Regla nueva**: en cualquier card o lista de asesor donde se muestren conteos por estado, la suma de los estados disjuntos del pipeline **debe igualar** el total del header.

1. Click en "Asesores" o equivalente que muestre desglose por asesor
2. Para al menos 2 asesores con leads, sumar manualmente:

   ```
   total_header = nuevos + contactados + calificados + en_negociacion +
                  ganados + perdidos + no_interesado
   ```

- [ ] La suma cuadra (margen 0)
- [ ] Si en la pantalla aparecen métricas tipo "sin contacto" o "acción vencida", están **separadas visualmente** del pipeline (banner aparte, header tipo "Alertas operativas") con label que aclare que **no suman al total**
- [ ] No se mezclan campos cumulativos (`leads_contactados` = todos no-Nuevo) con exclusivos (`leads_calificados`, etc.) en la misma fila

**Prueba 2.3 — Tarjetas de actividad reciente**

- [ ] Últimos contactos / llamadas en orden cronológico
- [ ] Click en una tarjeta abre el detalle del lead

**Prueba 2.4 — Distribuciones (charts)**

- [ ] "Leads por estado" muestra barras con conteos coherentes
- [ ] "Leads por fuente" muestra distribución
- [ ] Los totales coinciden con los KPIs principales

---

## PARTE 3 — Leads

**Prueba 3.1 — Lista**

- [ ] Tabla paginada (cambiar de página funciona)
- [ ] Buscador por nombre / teléfono / email
- [ ] Filtros por estado, fuente, asesor, calidad, fecha, antecedentes
- [ ] Empty state cuando no hay resultados muestra **"Limpiar filtros"** (no desaparecen los filtros al filtrar a 0)
- [ ] Ordenamiento por columna

**Prueba 3.2 — Vista de columnas (kanban)**

- [ ] Cambiar a vista kanban si existe
- [ ] Drag & drop entre columnas funciona
- [ ] El cambio se persiste tras refrescar

**Prueba 3.3 — Crear lead**

1. `Nuevo lead`
2. Llenar nombre, teléfono, email, fuente, asesor
3. Guardar

- [ ] Aparece en la lista inmediatamente
- [ ] Teléfono duplicado: avisa antes de guardar
- [ ] Validación de teléfono peruano (9 dígitos)

**Prueba 3.4 — Detalle**

- [ ] Datos del lead, contactos, llamadas, agenda, archivos
- [ ] Editar campos del lead funciona y persiste
- [ ] Cambio de estado deja registro en historial
- [ ] Tabs internas (Info / Contactos / Llamadas / Notas) funcionan sin recargar página

**Prueba 3.5 — Asignación individual**

- [ ] Cambiar asesor desde el detalle (admin/supervisor) funciona
- [ ] El asesor antiguo deja de ver el lead, el nuevo lo recibe

**Prueba 3.6 — Asignación masiva**

1. Seleccionar varios leads con checkbox
2. Click en "Asignar a..."
3. Elegir asesor / supervisor

- [ ] Para **supervisor**, el dropdown muestra `Equipo: <Yo>` con sus asesores Y `Otros supervisores` con los demás supervisores activos (cross-derivación). Coherente con APK.
- [ ] Todos los leads cambian de asesor
- [ ] Si alguno falla, se reporta cuáles sí y cuáles no (no falla silencioso)

**Prueba 3.7 — Exportar a Excel**

- [ ] Botón "Excel" funciona (admin/supervisor)
- [ ] El archivo descargado incluye los filtros aplicados
- [ ] Si el total > umbral, pide confirmación antes de exportar

---

## PARTE 4 — Agenda

**Prueba 4.1 — Vista calendario**

- [ ] Vista mes / semana / día funciona (o solo mes según implementación actual)
- [ ] Eventos coloreados por tipo (visita, llamada, etc.)
- [ ] Filtro por asesor (admin/supervisor)

**Prueba 4.2 — Crear cita**

1. Click en una fecha vacía
2. Asociar a un lead, fecha, hora, tipo
3. Guardar

- [ ] Aparece en el calendario
- [ ] No deja crear con fecha pasada
- [ ] No deja crear sin lead asociado

**Prueba 4.3 — Editar / cancelar cita**

- [ ] Click en una cita abre el modal de edición
- [ ] Cancelar la cita la marca como tal (no la borra)

---

## PARTE 5 — Asignación de leads

**Prueba 5.1 — Filtros de leads sin asesor**

- [ ] Aparecen los leads con `asesor = NULL`
- [ ] Filtros por fuente, fecha, calidad
- [ ] Empty state contextual: si filtraste a 0 resultados los filtros siguen visibles + botón "Limpiar filtros"

**Prueba 5.2 — Asignar a asesores activos del equipo**

- [ ] Solo lista asesores activos
- [ ] Si supervisor: muestra su equipo + sección "Otros supervisores"
- [ ] Si admin: muestra todos los equipos agrupados por supervisor

**Prueba 5.3 — Reasignación masiva**

- [ ] Seleccionar lote, asignar
- [ ] Confirmación clara antes de aplicar
- [ ] Resumen post-asignación (X éxitos, Y errores)

---

## PARTE 6 — Reportes

**Prueba 6.1 — Reportes disponibles** (admin/supervisor)

- [ ] Por asesor
- [ ] Por fuente
- [ ] Tiempo de respuesta (SLA <1h, <24h)
- [ ] Embudo de conversión
- [ ] Estancados (sin contacto > N días)
- [ ] Por campañas
- [ ] Actividad diaria

**Prueba 6.2 — Coherencia semántica de las tablas (CRÍTICO)**

> Mismo principio que Dashboard: las columnas deben ser claramente disjuntas o, si no lo son, el header debe ser explícito.

1. Tab "Por Asesor": revisar que las columnas estén bien etiquetadas
2. Para 2 asesores con datos, sumar manualmente las columnas disjuntas:

   - [ ] `nuevos` (= total - contactados) + `calificados` + `en_negociacion` + `ganados` + `perdidos` ≈ total
   - [ ] La columna `contactados` es **cumulativa** (todo lo que no es Nuevo) y debe estar etiquetada como tal o no estar al lado de los exclusivos
   - [ ] `sin_contactar` es transversal y está claramente diferenciado

**Prueba 6.3 — Exportación**

- [ ] Botón "Exportar a Excel" funciona en cada tab
- [ ] Datos del archivo coinciden con lo mostrado
- [ ] Filtros aplicados se respetan en la exportación
- [ ] Rate limit: a la 4ta exportación rápida, el sistema avisa "máximo 3 cada 5 minutos"

**Prueba 6.4 — Reporte de salud de integraciones** (admin)

- [ ] `/api/reportes/integraciones` muestra estado de Meta, TikTok, WhatsApp
- [ ] Eventos recientes (24h) listados con OK/error
- [ ] Latencia promedio del polling

---

## PARTE 7 — Chat WhatsApp (CRÍTICO)

**Prueba 7.1 — Lista de conversaciones**

- [ ] Aparece la lista con preview, última fecha, badge de no leídos
- [ ] Filtros por estado (potenciales/revisar/archivados/sin clasificar/delegar)
- [ ] Buscador funciona
- [ ] Filtros adicionales por etiqueta + por línea WhatsApp (si hay multi-WABA)

**Prueba 7.2 — Conversación con ventana 24h abierta**

1. Abrir un chat con cliente que escribió hace menos de 24h

- [ ] Chip verde "Ventana 24h abierta"
- [ ] TextInput libre habilitado
- [ ] Envío de texto funciona, aparece como saliente con ✓ y luego ✓✓

**Prueba 7.3 — Conversación fuera de ventana 24h (CRÍTICO)**

- [ ] Chip ámbar "Fuera de ventana 24h — solo templates"
- [ ] TextInput libre **bloqueado**
- [ ] Aparece botón **"Enviar plantilla aprobada"**

**Prueba 7.4 — Modal de templates**

1. Click en "Enviar plantilla aprobada"

- [ ] El modal carga las plantillas APPROVED de la WABA correcta según la línea de la conversación (multi-WABA)
- [ ] `hello_world` y otros templates demo de Meta NO aparecen (filtrados en backend desde v5.40.x)
- [ ] Si no hay templates, se muestra mensaje contextual con motivo: WABA no registrada / Meta API error / sin templates aprobados / solo demo

**Prueba 7.5 — Envío de template con variables**

1. Seleccionar template con `{{1}}`, `{{2}}`
2. Llenar variables

- [ ] El preview en burbuja verde se actualiza al toque mientras escribís
- [ ] Si una variable está vacía, el botón "Enviar" queda deshabilitado
- [ ] Al enviar, sale toast verde y el mensaje aparece como outbound en el chat

**Prueba 7.6 — Tooltip de error Meta (post-v5.40.9, CRÍTICO)**

> Si Meta marca un mensaje como `failed` vía webhook, el indicador `!` rojo en el mensaje saliente debe ser interactivo.

1. Forzar un fallo (ej. enviar template a número que no tiene WhatsApp)
2. Esperar a que el `!` rojo aparezca al lado del timestamp
3. **Hover sobre el `!`** (en mobile sería tap)

- [ ] Aparece tooltip con `Codigo Meta: <N> — <descripción>`
- [ ] Para errores conocidos (131058, 131042, 132001, 132000, 131026, 100), el mensaje es accionable (no JSON crudo)

**Prueba 7.7 — Primer contacto cold (lead que nunca escribió)**

1. Buscar un lead cuyo número NUNCA haya escrito al CRM (ej. lead recién importado de TikTok/Facebook)
2. Abrir su chat desde el detalle del lead

- [ ] Si la conv no existe, se crea pero el textbox está bloqueado
- [ ] Solo se permite enviar template aprobado para iniciar
- [ ] Endpoint `/send` con texto libre devuelve 409 con mensaje claro "Primer contacto: este número nunca te ha escrito. Envía un template aprobado primero."

**Prueba 7.8 — IA Clasificador**

1. Llega un nuevo chat de WhatsApp
2. Verificar que el clasificador IA asigne categoría

- [ ] La conversación aparece con la categoría correcta (interesado/info/spam/etc.)
- [ ] Botón "Reclasificar" permite re-correr el modelo manualmente
- [ ] Si Ollama está caído, los chats quedan en `failed` — se reintentan con botón

**Prueba 7.9 — Multi-WABA + multi-número**

> Solo si hay >1 WABA o >1 número registrado.

- [ ] Sidebar muestra filtro por línea (`wa_number_id`)
- [ ] Templates filtrados por WABA del número activo
- [ ] Conversaciones de cada número se ven separadas
- [ ] Al enviar, el `phone_number_id` correcto se usa según la conv

---

## PARTE 8 — Históricos (NUEVO en v3.1)

**Prueba 8.1 — Listado**

- [ ] Lista paginada de leads históricos (50 por página)
- [ ] Buscador funciona
- [ ] Filtros por proyecto, canal, estado
- [ ] Stats arriba (total leads, total proyectos)

**Prueba 8.2 — Visibilidad por rol**

- [ ] Admin ve todos los históricos
- [ ] Supervisor ve los del equipo
- [ ] Asesor ve solo los suyos

---

## PARTE 9 — Carga Masiva (admin)

**Prueba 9.1 — Importar CSV**

1. Pegar lista o subir archivo
2. Mapear columnas
3. Validar previa
4. Confirmar

- [ ] Resumen claro: X registros válidos, Y con errores
- [ ] Errores explican exactamente qué falla en cada fila
- [ ] Tras importar, los leads aparecen en la lista
- [ ] Teléfonos duplicados se manejan según la regla configurada

**Prueba 9.2 — Plantilla y errores descargables**

- [ ] Botón "Descargar plantilla" funciona
- [ ] Botón "Descargar errores" tras una carga con fallos funciona

**Prueba 9.3 — Historial de cargas**

- [ ] Aparece la carga reciente con fecha, asesor, total
- [ ] Click muestra los leads de esa carga

---

## PARTE 10 — Formularios públicos (admin/supervisor)

**Prueba 10.1 — Crear formulario**

1. `Formularios → Nuevo`
2. Definir campos visibles (nombre, teléfono, email, mensaje)
3. Configurar fuente y asesor por defecto
4. Generar link público

- [ ] Link funciona en una ventana privada (sin login)
- [ ] Submit del formulario crea un lead nuevo en el CRM
- [ ] Anti-spam (honeypot + min_submit_seconds + rate limit por IP) funciona

**Prueba 10.2 — Editar / archivar formulario**

- [ ] Cambios se reflejan en el link público al recargar
- [ ] Archivar: el link queda inactivo
- [ ] Ver QR + descargar PNG funciona

---

## PARTE 11 — Configuración

**Prueba 11.1 — Empresa → General**

- [ ] Estado de los servicios (API, BD) verde
- [ ] Botón "Verificar" actualiza el estado

**Prueba 11.2 — Empresa → Marca**

- [ ] Cambiar nombre comercial → se refleja en header inmediatamente
- [ ] Subir logo (PNG / SVG) → aparece en sidebar
- [ ] Subir favicon → cambia el del navegador
- [ ] Cambiar colores → se aplican a botones y links

**Prueba 11.3 — Equipo → Usuarios**

- [ ] Crear, editar, desactivar usuarios funciona
- [ ] Reset de contraseña envía mail (si SMTP configurado)
- [ ] Asignar rol funciona

**Prueba 11.4 — Equipo → Equipos**

- [ ] Asignar asesores a supervisores con drag & drop o picker
- [ ] El cambio se refleja inmediatamente en quién ve a quién

**Prueba 11.5 — Pipeline → Estados / Calidad / Fuentes / Campañas / Etiquetas**

Probar al menos uno de cada:

- [ ] Crear nuevo registro
- [ ] Editar
- [ ] Reordenar (si tiene drag handle)
- [ ] Eliminar (avisa si tiene leads asociados)

**Prueba 11.6 — Comunicación → Contactos (Tipos / Resultados)**

- [ ] CRUD de tipos de contacto
- [ ] CRUD de resultados de contacto
- [ ] Toggle "Asesor puede editar/eliminar" funciona

**Prueba 11.7 — Comunicación → Categorías Chat**

- [ ] CRUD de categorías / chips de respuesta rápida

**Prueba 11.8 — Comunicación → IA Clasificador**

- [ ] Ver la config actual del modelo y umbrales
- [ ] Probar con un mensaje de ejemplo
- [ ] Health check del proveedor IA verde

**Prueba 11.9 — Comunicación → Notificaciones Push (CRÍTICO post-v5.42.x)**

1. Estado FCM:

- [ ] Card "Habilitado": Sí
- [ ] Card "Credencial": muestra preview enmascarado
- [ ] Card "Origen de la credencial": **claramente etiquetado**:
  - ✓ verde "Cargada desde la UI" si está en DB
  - ⚠️ ámbar "Cargada desde .env" si solo está en env
- [ ] Si hubo `last_error`, se muestra banner rojo con el mensaje

2. Probar envío:
- [ ] Botón "Probar envío" abre modal/confirma → llega push al admin

3. Editor de plantillas:
- [ ] CRUD de cada evento (lead asignado, cambio de estado, contacto, mensaje chat)
- [ ] Variables disponibles se listan
- [ ] Probar evento → llega push con la plantilla actual

**Prueba 11.10 — Comunicación → Sincronización móvil**

- [ ] Input numérico carga el valor actual
- [ ] Cambiar a 10 → guardar → toast verde
- [ ] Valores fuera de rango (3, 200) → error claro
- [ ] Presets 10 / 30 / 60 funcionan
- [ ] APK abierta en otro celular sincroniza con el nuevo intervalo en el siguiente foreground

**Prueba 11.11 — Comunicación → Correo (SMTP)**

- [ ] Form de SMTP carga la config actual
- [ ] Botón "Enviar correo de prueba" llega al destinatario
- [ ] Si falla: error claro

**Prueba 11.12 — Mi cuenta → Seguridad**

- [ ] Cambiar contraseña funciona
- [ ] Validación de longitud / fortaleza
- [ ] Tras cambio, logout automático o aviso

---

## PARTE 12 — Integraciones (NUEVO en v3.1, admin only)

**Prueba 12.1 — Tab Meta (Lead Ads)**

- [ ] App ID, App Secret, Verify Token, Ads Access Token guardados muestran preview enmascarado
- [ ] Cuentas registradas (páginas con Page Access Token) listadas
- [ ] "Suscribir webhook" funciona (one-shot, registra la página en la app)
- [ ] Ver historial de eventos (24h) — última suscripción aparece como `ok`

**Prueba 12.2 — Tab TikTok (Lead Gen)**

- [ ] App ID, App Secret guardados
- [ ] Botón "Conectar con TikTok" abre OAuth (si app_id y app_secret están)
- [ ] Cuentas registradas: advertiser ID, access token (preview), nombre del advertiser
- [ ] Botón **"Probar ahora"** sobre cada cuenta → muestra resultado del poll (`fetched: N, created: M`)
- [ ] Sección **"Cadencia del polling automático"** (post-v5.40.x):
  - [ ] Input numérico con valor actual (default 10)
  - [ ] Presets rápidos 5m / 10m / 15m / 30m
  - [ ] Validación rango 5-60
  - [ ] Guardar muestra toast OK
- [ ] Sección **"Backfill manual"**: ejecutar con N días → muestra resumen `traídos / nuevos / duplicados`

**Prueba 12.3 — Tab WhatsApp Business**

- [ ] **Cuentas Empresariales (WABA)**: lista de WABAs registradas con preview de tokens
- [ ] Crear WABA nueva: WABA ID + display name + access_token + app_secret + verify_token
- [ ] **Líneas WhatsApp Business**: lista de números, cada uno asociado a una WABA
- [ ] Default activo es claro (badge)
- [ ] **Diagnóstico WhatsApp**: ping a `/api/whatsapp/diagnostics` muestra estado del webhook

---

## PARTE 13 — Reparto de leads (admin)

**Prueba 13.1 — Configurar rotación**

- [ ] Lista asesores activos del equipo
- [ ] Toggle activo/inactivo por asesor
- [ ] Cambio se persiste

**Prueba 13.2 — Verificación en webhook**

> Si está integrado con n8n.

- [ ] Mandar un lead simulado al webhook de ingesta → llega al asesor que toca según rotación
- [ ] Push notification llega al asesor en su APK

---

## PARTE 14 — Paridad mobile/web (NUEVO en v3.1)

> Verificar que las capacidades críticas de la web también están disponibles en la APK del CRM. Referencia: `MODULES.md` en la raíz del repo.

**Prueba 14.1 — Para roles supervisor y asesor**, abrir la APK y comparar:

- [ ] Lista de leads coincide con la web (mismo total, mismos filtros operativos)
- [ ] Detalle de lead permite mismo set de operaciones (editar, cambiar estado, agregar contacto)
- [ ] Asignación cross-supervisor disponible en mobile (post-v5.41.0)
- [ ] Históricos visible en mobile (post-v5.42.0)
- [ ] Reportes de tiempo de respuesta + estancados + funnel + campañas en mobile (post-v5.42.0)
- [ ] Dashboard distribuciones por estado/fuente en mobile (post-v5.42.0)
- [ ] Tooltip de error Meta al tocar burbuja `!` rojo en mobile (post-v5.42.0)

---

## PARTE 15 — Smoke checks finales

- [ ] No hay errores en la consola del navegador (F12) durante la sesión completa
- [ ] No hay 4xx/5xx inesperados en la pestaña Network (las únicas 4xx/5xx aceptables son las intencionales: rate limits 429 al exceder, 409 al primer contacto cold, 401 si la sesión expira durante la prueba)
- [ ] La app responde en menos de 2 segundos en cada navegación
- [ ] El logout deja la página de login limpia (sin datos del usuario anterior)
- [ ] Funciona correctamente en Chrome, Firefox y Edge (al menos uno por team)
- [ ] CI de GitHub Actions del último commit en main: 🟢 verde

---

## Incidencias encontradas

| # | Prueba | Qué pasó | Severidad (alta/media/baja) | Asignado a |
|---|--------|----------|------------------------------|------------|
|   |        |          |                              |            |
|   |        |          |                              |            |
|   |        |          |                              |            |

**Severidad — criterios:**
- **Alta**: bloquea uso productivo de la pantalla / corrupción de datos / pérdida de leads / inconsistencia que confunde al usuario al punto de no entender el dato (ej. sumas que no cuadran)
- **Media**: workaround molesto pero la feature core funciona (ej. tarda 5s, falta un confirm dialog, copy ambiguo)
- **Baja**: cosmético, no afecta funcionalidad (alineación, color, copy menor)

---

## Veredicto

- [ ] Todas las pruebas marcadas → **Web aprobada para producción**
- [ ] Hay incidencias de severidad alta → **NO desplegar, esperar fix**
- [ ] Hay incidencias de severidad media/baja → **Desplegar con observación, fix en próxima versión**

**Firma de quien prueba:** _______________
**Fecha:** _______________
**Versión web aprobada:** v3.1 / commit: _______________
