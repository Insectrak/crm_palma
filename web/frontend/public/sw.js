/**
 * Service Worker — DESACTIVADO (2026-06-15)
 *
 * Decisión: el SW estaba causando bugs persistentes de cache stale
 * (bundles JS viejos servidos después de deploys) — síntoma reportado
 * por el usuario: placeholders con "null" textual que no se actualizan
 * después de Implementar, aunque el deploy en server sea nuevo.
 *
 * Estrategia: este SW al instalarse se AUTODESTRUYE — desregistra todos
 * los clientes (browsers con SW vivo) y borra todas las caches. Una vez
 * que todos los clientes hagan reload, este SW deja de existir y el
 * browser pega directo al server siempre (comportamiento clásico sin PWA).
 *
 * El archivo SE QUEDA acá para que browsers viejos que pidan /sw.js
 * reciban 200 OK con un SW válido que se autodestruye, en vez de 404
 * (que dejaría el SW viejo corriendo indefinidamente).
 *
 * Si en el futuro queremos PWA real, ver git log de este archivo y
 * restaurar la versión `palmacrm-v5` con cache estratégica.
 */

self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', async (event) => {
  event.waitUntil((async () => {
    // 1. Borrar TODAS las caches que cualquier versión anterior haya creado.
    const keys = await caches.keys()
    await Promise.all(keys.map((k) => caches.delete(k)))
    // 2. Auto-desregistrarse — al próximo load del cliente ya no hay SW.
    await self.registration.unregister()
    // 3. Forzar a todos los clientes activos a recargar — toman el bundle
    //    nuevo del server directo sin pasar por SW.
    const clients = await self.clients.matchAll({ type: 'window' })
    clients.forEach((client) => client.navigate(client.url))
  })())
})

// Sin handler fetch: el browser usa la red directo. Eso es lo que queremos.
