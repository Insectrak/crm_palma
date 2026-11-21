/**
 * Tests del componente Dialog (modal reusable).
 *
 * Cubre comportamiento crítico:
 *  - Render condicional según prop `open`
 *  - Cierre por tecla Escape
 *  - Cierre al hacer click directamente en el overlay
 *  - **Anti close-on-text-drag**: si el `mousedown` empezó dentro del modal
 *    (ej: usuario seleccionando texto), `mouseup` afuera NO debe cerrar.
 *
 * El último caso es regresión documentada del bug del 26/5/2026 reportado
 * por Soporte. Si alguien regresiona ese fix, este test lo caza.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Dialog, DialogHeader, DialogContent } from '@/components/ui/dialog'


describe('Dialog', () => {
  it('no renderiza nada cuando open=false', () => {
    const { container } = render(
      <Dialog open={false} onClose={() => {}}>
        <DialogContent>contenido</DialogContent>
      </Dialog>
    )
    expect(container.firstChild).toBeNull()
  })

  it('renderiza el contenido cuando open=true', () => {
    render(
      <Dialog open={true} onClose={() => {}}>
        <DialogContent>contenido del modal</DialogContent>
      </Dialog>
    )
    expect(screen.getByText('contenido del modal')).toBeInTheDocument()
  })

  it('llama onClose cuando se presiona Escape', () => {
    const onClose = vi.fn()
    render(
      <Dialog open={true} onClose={onClose}>
        <DialogContent>contenido</DialogContent>
      </Dialog>
    )
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('llama onClose al hacer click directo en el overlay', () => {
    const onClose = vi.fn()
    render(
      <Dialog open={true} onClose={onClose}>
        <DialogContent>contenido</DialogContent>
      </Dialog>
    )
    // El overlay es el div con bg-black/50 — el padre del contenido del modal.
    const overlay = screen.getByText('contenido').closest('.fixed')
    // Simulamos un click completo: pointerdown + click en el overlay mismo
    fireEvent.pointerDown(overlay, { target: overlay })
    fireEvent.click(overlay, { target: overlay })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('NO cierra cuando se hace click en el contenido interno (no overlay)', () => {
    const onClose = vi.fn()
    render(
      <Dialog open={true} onClose={onClose}>
        <DialogContent>contenido interno</DialogContent>
      </Dialog>
    )
    const inner = screen.getByText('contenido interno')
    fireEvent.pointerDown(inner)
    fireEvent.click(inner)
    expect(onClose).not.toHaveBeenCalled()
  })

  // ──────────────────────────────────────────────────────────────────────
  // Regresión: bug del 26/5/2026 (drag-to-close-on-text-select)
  // ──────────────────────────────────────────────────────────────────────

  it('NO cierra cuando pointerdown empezó en contenido y mouseup ocurrió en overlay (drag-out)', () => {
    const onClose = vi.fn()
    render(
      <Dialog open={true} onClose={onClose}>
        <DialogContent>contenido con input</DialogContent>
      </Dialog>
    )
    const inner = screen.getByText('contenido con input')
    const overlay = inner.closest('.fixed')

    // Simulamos: usuario seleccionando texto desde el input (dentro)
    // y arrastrando el cursor hasta soltar afuera (overlay).
    fireEvent.pointerDown(inner)             // empieza la selección
    fireEvent.click(overlay, { target: overlay })  // soltó afuera

    // ❌ ANTES del fix: onClose era llamado (drag-to-close bug)
    // ✅ DESPUÉS del fix: NO debe cerrar porque el pointerdown fue dentro
    expect(onClose).not.toHaveBeenCalled()
  })

  // ──────────────────────────────────────────────────────────────────────
  // DialogHeader X button
  // ──────────────────────────────────────────────────────────────────────

  it('DialogHeader muestra botón X que llama onClose', () => {
    const onClose = vi.fn()
    render(
      <Dialog open={true} onClose={() => {}}>
        <DialogHeader onClose={onClose}>Título del modal</DialogHeader>
      </Dialog>
    )
    expect(screen.getByText('Título del modal')).toBeInTheDocument()
    const closeBtn = screen.getByRole('button')
    fireEvent.click(closeBtn)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('DialogHeader sin onClose no renderiza botón X', () => {
    render(
      <Dialog open={true} onClose={() => {}}>
        <DialogHeader>Título sin botón</DialogHeader>
      </Dialog>
    )
    expect(screen.queryByRole('button')).toBeNull()
  })
})
