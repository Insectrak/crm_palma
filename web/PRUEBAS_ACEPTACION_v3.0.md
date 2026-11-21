# Pruebas de Aceptacion — Web CRM Palma Rio v3.0

**Persona que prueba:** _______________
**Fecha:** _______________
**Navegador / version:** _______________
**URL probada:** `https://brighton-crm-brighton.l7weu8.easypanel.host`

> **Objetivo**: certificar que la web esta lista para que admin, supervisores y asesores la usen en produccion. Cada bloque debe terminar con todos los checkboxes marcados. Si un check falla, anotarlo en **Incidencias** al final.

---

## Antes de empezar

- [ ] Tres cuentas activas (pedir a Soporte si no las tienes):
  - **Admin**
  - **Supervisor** (Paola o Darwin)
  - **Asesor**
- [ ] Acceso a la APK del CRM en un celular para verificaciones cruzadas
- [ ] Limpia el cache del navegador antes de empezar (`Ctrl+Shift+Del` → ultima hora)
- [ ] Hard refresh con `Ctrl+Shift+R` para no caer en service worker viejo

---

## PARTE 1 — Login y sesion

**Prueba 1.1 — Pagina de login**

1. Abrir la URL en una ventana privada / incognito
2. Observar la pantalla

- [ ] Logo y nombre de marca visibles
- [ ] Campos email + contrasena vacios
- [ ] Boton "Ingresar" visible

**Prueba 1.2 — Login admin**

1. Ingresar credenciales del admin

- [ ] Entra al Dashboard
- [ ] El sidebar muestra: Dashboard, Leads, Agenda, Chat, Llamadas, Carga Masiva, Asignacion, Formularios, Reportes, Historicos, Reparto leads, Configuracion
- [ ] Esquina inferior izquierda muestra **Admin CRM · Admin** (rol activo)

**Prueba 1.3 — Logout y cambio de rol**

1. Click en `Cerrar sesion`
2. Login como **Supervisor**

- [ ] El menu se reduce: NO ve "Carga Masiva", "Reparto leads", "Formularios" (depende del proyecto, validar contra spec)
- [ ] Solo ve datos de su equipo

3. Logout, login como **Asesor**

- [ ] El menu se reduce aun mas (sin Asignacion, sin Reportes globales)
- [ ] Solo ve sus propios leads

**Prueba 1.4 — Sesion persistente**

1. Cerrar la pestana sin hacer logout
2. Reabrir la URL en una nueva pestana

- [ ] La sesion sigue activa, no pide login otra vez
- [ ] Si se vence el JWT, redirige automaticamente al login

---

## PARTE 2 — Dashboard

**Prueba 2.1 — KPIs**

- [ ] Numero de leads totales
- [ ] Leads del dia / semana / mes
- [ ] Conversion rate o porcentaje de avance
- [ ] Grafico de tendencia visible y se actualiza al cambiar el rango

**Prueba 2.2 — Tarjetas de actividad reciente**

- [ ] Ultimos contactos / llamadas se ven en orden cronologico
- [ ] Click en una tarjeta abre el detalle del lead correspondiente

---

## PARTE 3 — Leads

**Prueba 3.1 — Lista**

- [ ] Tabla paginada (cambiar de pagina funciona)
- [ ] Buscador por nombre / telefono / email
- [ ] Filtros por estado, fuente, asesor, calidad, fecha
- [ ] Ordenamiento por columna

**Prueba 3.2 — Vista de columnas (kanban)**

- [ ] Cambiar a vista kanban si existe
- [ ] Drag & drop de leads entre columnas (estados) funciona
- [ ] El cambio se persiste tras refrescar la pagina

**Prueba 3.3 — Crear lead**

1. `Nuevo lead`
2. Llenar nombre, telefono, email, fuente, asesor
3. Guardar

- [ ] Aparece en la lista inmediatamente
- [ ] Telefono duplicado: avisa antes de guardar (no crea silencioso)
- [ ] Validacion de telefono peruano (9 digitos)

**Prueba 3.4 — Detalle**

- [ ] Datos del lead, contactos, llamadas, agenda, archivos
- [ ] Editar campos del lead funciona y persiste
- [ ] Cambio de estado deja registro en historial

**Prueba 3.5 — Asignacion individual**

- [ ] Cambiar asesor desde el detalle (admin/supervisor) funciona
- [ ] El asesor antiguo deja de ver el lead, el nuevo lo recibe

**Prueba 3.6 — Asignacion masiva**

1. Seleccionar varios leads con checkbox
2. Click en "Asignar a..."
3. Elegir asesor

- [ ] Todos los leads cambian de asesor
- [ ] Si alguno falla, se reporta cuales si y cuales no (no falla silencioso)

---

## PARTE 4 — Agenda

**Prueba 4.1 — Vista calendario**

- [ ] Vista mes / semana / dia funciona
- [ ] Eventos coloreados por tipo (visita, llamada, etc.)
- [ ] Filtro por asesor (admin/supervisor)

**Prueba 4.2 — Crear cita**

1. Click en una fecha vacia
2. Asociar a un lead, fecha, hora, tipo
3. Guardar

- [ ] Aparece en el calendario
- [ ] No deja crear con fecha pasada
- [ ] No deja crear sin lead asociado

**Prueba 4.3 — Editar / cancelar cita**

- [ ] Click en una cita abre el modal de edicion
- [ ] Cancelar la cita la marca como tal (no la borra)

---

## PARTE 5 — Asignacion de leads

**Prueba 5.1 — Filtros de leads sin asesor**

- [ ] Aparecen los leads con asesor NULL
- [ ] Filtros por fuente, fecha, calidad

**Prueba 5.2 — Asignar a asesores activos del equipo**

- [ ] Solo lista asesores activos
- [ ] Si supervisor: solo lista los suyos. Si admin: todos.

**Prueba 5.3 — Reasignacion masiva**

- [ ] Seleccionar lote, asignar
- [ ] Confirmacion clara antes de aplicar
- [ ] Resumen post-asignacion (X exitos, Y errores)

---

## PARTE 6 — Reportes

**Prueba 6.1 — Reportes disponibles**

- [ ] Reporte de leads por asesor
- [ ] Reporte de conversion por fuente
- [ ] Reporte de llamadas por asesor (con duracion total y promedio)
- [ ] Reporte de citas y cumplimiento

**Prueba 6.2 — Exportacion**

- [ ] Boton "Exportar a Excel" o CSV funciona
- [ ] Los datos del archivo coinciden con lo mostrado en pantalla
- [ ] Filtros aplicados se respetan en la exportacion

---

## PARTE 7 — Chat WhatsApp (CRITICO)

**Prueba 7.1 — Lista de conversaciones**

- [ ] Aparece la lista con preview, ultima fecha, badge de no leidos
- [ ] Filtros por estado (abierto/archivado), por asesor
- [ ] Buscador funciona

**Prueba 7.2 — Conversacion con ventana 24h abierta**

1. Abrir un chat con cliente que escribio hace menos de 24h

- [ ] Chip verde "Ventana 24h abierta"
- [ ] TextInput libre habilitado
- [ ] Envio de texto funciona, aparece como saliente

**Prueba 7.3 — Conversacion fuera de ventana 24h**

- [ ] Chip rojo "Fuera de ventana 24h"
- [ ] TextInput libre **bloqueado**
- [ ] Solo aparece boton "Enviar template"

**Prueba 7.4 — Primer contacto cold (CRITICO)**

1. Buscar un lead cuyo numero NUNCA haya escrito al CRM
2. Abrir su chat

- [ ] La conversacion nueva muestra estado "primer contacto" o equivalente
- [ ] **NO permite escribir texto libre**
- [ ] Solo puede mandar template aprobado

**Prueba 7.5 — Modal de templates**

1. Click en "Enviar template"

- [ ] La lista carga templates del WABA correcta segun la linea de la conversacion (multi-WABA)
- [ ] Si no hay templates: mensaje **especifico** segun el `reason` que devuelva el backend
- [ ] Boton **Reintentar** aparece si fue error transitorio

**Prueba 7.6 — Envio de template con variables**

1. Seleccionar template con `{{1}}`, `{{2}}`
2. Llenar variables
3. Preview en vivo

- [ ] El preview es identico al mensaje que se mandara
- [ ] No envia si faltan variables
- [ ] Tras enviar, el template aparece como mensaje saliente

**Prueba 7.7 — IA Clasificador (admin)**

1. Llega un nuevo chat de WhatsApp
2. Verificar que el clasificador IA asigne categoria

- [ ] La conversacion aparece con la categoria correcta (interesado/info/spam/etc.)
- [ ] Click derecho o menu permite re-clasificar manual

**Prueba 7.8 — Multi-numero (multi-linea WhatsApp Business)**

> Solo si la cuenta tiene mas de un numero registrado.

- [ ] Se puede elegir desde que numero responder
- [ ] Templates filtrados por numero
- [ ] Conversaciones de cada numero se ven separadas

---

## PARTE 8 — Carga Masiva (admin)

**Prueba 8.1 — Importar CSV**

1. Pegar lista o subir archivo
2. Mapear columnas
3. Validar previa
4. Confirmar

- [ ] Resumen claro: X registros validos, Y con errores
- [ ] Errores explican exactamente que falla en cada fila
- [ ] Tras importar, los leads aparecen en la lista
- [ ] Telefonos duplicados se manejan segun la regla configurada (sobreescribir / saltar / crear nuevo)

**Prueba 8.2 — Historial de cargas**

- [ ] Aparece la carga reciente con fecha, asesor, total
- [ ] Click muestra los leads de esa carga

---

## PARTE 9 — Formularios publicos (admin)

**Prueba 9.1 — Crear formulario**

1. `Formularios → Nuevo`
2. Definir campos visibles (nombre, telefono, email, mensaje)
3. Configurar fuente y asesor por defecto
4. Generar link publico

- [ ] Link funciona en una ventana privada (sin login)
- [ ] Submitting el formulario crea un lead nuevo en el CRM

**Prueba 9.2 — Editar / archivar formulario**

- [ ] Cambios se reflejan en el link publico al recargar
- [ ] Archivar: el link queda inactivo

---

## PARTE 10 — Configuracion (admin/supervisor)

**Prueba 10.1 — Empresa → General**

- [ ] Estado de los servicios (API, BD) verde
- [ ] Boton "Verificar" actualiza el estado

**Prueba 10.2 — Empresa → Marca**

- [ ] Cambiar nombre comercial → se refleja en header inmediatamente
- [ ] Subir logo (PNG / SVG) → aparece en sidebar
- [ ] Subir favicon → cambia el del navegador
- [ ] Cambiar colores → se aplican a botones y links

**Prueba 10.3 — Equipo → Usuarios**

- [ ] Crear, editar, desactivar usuarios funciona
- [ ] Reset de contrasena envia mail (si SMTP configurado)
- [ ] Asignar rol funciona

**Prueba 10.4 — Equipo → Equipos**

- [ ] Asignar asesores a supervisores con drag & drop o picker
- [ ] El cambio se refleja inmediatamente en quien ve a quien

**Prueba 10.5 — Pipeline → Estados / Calidad / Fuentes / Campanas / Etiquetas**

Probar al menos uno de cada:

- [ ] Crear nuevo registro
- [ ] Editar
- [ ] Reordenar (si tiene drag handle)
- [ ] Eliminar (si tiene leads asociados, debe avisar antes)

**Prueba 10.6 — Comunicacion → Contactos (Tipos / Resultados)**

- [ ] CRUD de tipos de contacto
- [ ] CRUD de resultados de contacto
- [ ] Toggle "Asesor puede editar/eliminar" funciona

**Prueba 10.7 — Comunicacion → Categorias Chat**

- [ ] CRUD de categorias / chips de respuesta rapida

**Prueba 10.8 — Comunicacion → IA Clasificador**

- [ ] Ver la config actual del modelo y umbrales
- [ ] Probar con un mensaje de ejemplo: el clasificador devuelve la categoria esperada
- [ ] Health check del proveedor IA verde

**Prueba 10.9 — Comunicacion → Notificaciones Push**

- [ ] Editar template de cada evento
- [ ] Variables disponibles se listan
- [ ] Mandar push de prueba → llega al celular del admin

**Prueba 10.10 — Comunicacion → Sincronizacion movil (NUEVO)**

1. `Configuracion → Comunicacion → Sincronizacion movil`

- [ ] El input numerico carga el valor actual del backend
- [ ] Cambiar a 10 → guardar → toast verde "Guardado…"
- [ ] Probar valores fuera de rango (3, 200) → error claro
- [ ] Presets 10 / 30 / 60 funcionan
- [ ] Verificacion cruzada con APK: tras guardar, una APK abierta sincroniza con el nuevo intervalo en el siguiente foreground

**Prueba 10.11 — Comunicacion → Correo (SMTP)**

- [ ] Form de SMTP carga la config actual
- [ ] Boton "Enviar correo de prueba" llega al destinatario
- [ ] Si falla: error claro (no generico)

**Prueba 10.12 — Mi cuenta → Seguridad**

- [ ] Cambiar contrasena funciona
- [ ] Validacion de longitud / fortaleza
- [ ] Tras cambio, logout automatico o aviso

---

## PARTE 11 — Reparto de leads (admin)

**Prueba 11.1 — Configurar rotacion**

- [ ] Lista asesores activos del equipo
- [ ] Toggle activo/inactivo por asesor
- [ ] Cambio se persiste

**Prueba 11.2 — Verificacion en webhook**

> Si esta integrado con n8n.

- [ ] Mandar un lead simulado al webhook de ingesta → llega al asesor que toca segun rotacion

---

## PARTE 12 — Smoke checks finales

- [ ] No hay errores en la consola del navegador (F12) durante la sesion completa
- [ ] No hay errores 500 en pestana Network
- [ ] La app responde en menos de 2 segundos en cada navegacion
- [ ] El logout deja la pagina de login limpia (sin datos del usuario anterior)
- [ ] Funciona correctamente en Chrome, Firefox y Edge (al menos uno por team)

---

## Incidencias encontradas

| # | Prueba | Que paso | Severidad (alta/media/baja) |
|---|--------|----------|-----------------------------|
|   |        |          |                             |
|   |        |          |                             |
|   |        |          |                             |

---

## Veredicto

- [ ] Todas las pruebas marcadas → **Web aprobada para produccion**
- [ ] Hay incidencias de severidad alta → **NO desplegar, esperar fix**
- [ ] Hay incidencias de severidad media/baja → **Desplegar con observacion, fix en proxima version**

**Firma de quien prueba:** _______________
**Fecha:** _______________
