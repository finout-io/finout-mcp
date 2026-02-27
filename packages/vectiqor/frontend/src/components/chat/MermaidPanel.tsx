import { useEffect, useRef, useState } from 'react'
import { ActionIcon, Box, Card, Group, Text } from '@mantine/core'
import mermaid from 'mermaid'

mermaid.initialize({ startOnLoad: false, theme: 'dark' })

interface Transform { x: number; y: number; scale: number }

function parseMermaidDiagram(output: unknown): string | null {
  let data: unknown = output
  if (typeof data === 'string') {
    try { data = JSON.parse(data) } catch { return null }
  }
  if (data && typeof data === 'object') {
    const o = data as Record<string, unknown>
    if (typeof o.mermaid_diagram === 'string') return o.mermaid_diagram
  }
  return null
}

export function MermaidPanel({ output }: { output: unknown }) {
  const diagram = parseMermaidDiagram(output)
  const mermaidRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ sx: number; sy: number; tx: number; ty: number } | null>(null)
  const [tf, setTf] = useState<Transform>({ x: 0, y: 0, scale: 1 })
  const [dragging, setDragging] = useState(false)

  useEffect(() => {
    if (!diagram || !mermaidRef.current) return
    const el = mermaidRef.current
    el.removeAttribute('data-processed')
    el.innerHTML = diagram
    mermaid.run({ nodes: [el] }).then(() => {
      const svg = el.querySelector('svg')
      if (!svg) return
      // Build viewBox from fixed pixel dimensions if not already set
      if (!svg.getAttribute('viewBox')) {
        const w = parseFloat(svg.getAttribute('width') ?? '0')
        const h = parseFloat(svg.getAttribute('height') ?? '0')
        if (w > 0 && h > 0) svg.setAttribute('viewBox', `0 0 ${w} ${h}`)
      }
      // Make fluid — Mermaid often sets an inline max-width that must be cleared
      svg.setAttribute('width', '100%')
      svg.style.maxWidth = 'none'
      svg.style.display = 'block'
    })
    setTf({ x: 0, y: 0, scale: 1 })
  }, [diagram])

  if (!diagram) return null

  return (
    <Card
      withBorder mt="sm" p="xs"
      style={{ background: 'rgba(0,0,0,0.2)', border: '1px solid #373A40' }}
    >
      <Group justify="flex-end" mb={4} gap="xs">
        <Text size="xs" c="dimmed" style={{ opacity: 0.5 }}>scroll to zoom · drag to pan</Text>
        <ActionIcon
          size="xs" variant="subtle" title="Reset view"
          onClick={() => setTf({ x: 0, y: 0, scale: 1 })}
        >
          ⊙
        </ActionIcon>
      </Group>

      <Box
        style={{ overflow: 'hidden', cursor: dragging ? 'grabbing' : 'grab', userSelect: 'none' }}
        onWheel={(e) => {
          e.preventDefault()
          const factor = e.deltaY < 0 ? 1.12 : 0.89
          setTf(p => ({ ...p, scale: Math.max(0.2, Math.min(6, p.scale * factor)) }))
        }}
        onMouseDown={(e) => {
          setDragging(true)
          drag.current = { sx: e.clientX, sy: e.clientY, tx: tf.x, ty: tf.y }
        }}
        onMouseMove={(e) => {
          if (!drag.current) return
          setTf(p => ({
            ...p,
            x: drag.current!.tx + e.clientX - drag.current!.sx,
            y: drag.current!.ty + e.clientY - drag.current!.sy,
          }))
        }}
        onMouseUp={() => { setDragging(false); drag.current = null }}
        onMouseLeave={() => { setDragging(false); drag.current = null }}
      >
        <div style={{ transformOrigin: '0 0', transform: `translate(${tf.x}px,${tf.y}px) scale(${tf.scale})`, width: '100%' }}>
          <div ref={mermaidRef} className="mermaid" />
        </div>
      </Box>
    </Card>
  )
}
