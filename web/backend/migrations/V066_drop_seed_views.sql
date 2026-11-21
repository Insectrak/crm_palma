-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V066 — Borrar vistas "Ejemplo:" auto-instaladas y desactivar seeding   ║
-- ║                                                                        ║
-- ║ V063 fase B (commit 2748ccb) instalaba vistas pre-armadas al primer   ║
-- ║ GET /api/views?scope=X del usuario, segun su rol. La idea era ayudar  ║
-- ║ a la descubribilidad de la feature, pero en la practica los users    ║
-- ║ no entendian de donde salian estas vistas y queria borrarlas pero    ║
-- ║ aparecian de nuevo al recargar.                                       ║
-- ║                                                                        ║
-- ║ Decision UAT: NO auto-instalar seeds. Que el user cree sus vistas    ║
-- ║ desde cero — el boton "+ Vista" es suficiente para que descubra la   ║
-- ║ feature al usarla.                                                    ║
-- ║                                                                        ║
-- ║ Esta migration:                                                       ║
-- ║   1. Borra las vistas seed creadas por V063 fase B (nombres exactos). ║
-- ║   2. La logica de seeding se remueve en el commit del backend.        ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- Lista de nombres EXACTOS que el seeder usaba. Si un user creo una vista
-- con uno de estos nombres manualmente, se borra tambien — es improbable,
-- y el riesgo de dejar seeds zombies es mayor que el de un falso positivo.
DELETE FROM crm.user_views
WHERE name IN (
    -- V063 fase B inicial (sin prefijo "Ejemplo:")
    'Mis leads activos',
    'Cola del equipo',
    'Sin contactar +24h',
    'Mi cola',
    'Todo sin asignar',
    -- V063.3 (con prefijo "Ejemplo:")
    'Ejemplo: Mis leads activos',
    'Ejemplo: Cola del equipo',
    'Ejemplo: Sin contactar +24h',
    'Ejemplo: Mi cola',
    'Ejemplo: Todo sin asignar'
);

COMMIT;
