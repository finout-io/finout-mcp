import { useEffect, useRef, useState } from 'react'
import { ActionIcon, Box, Card, Group, SegmentedControl, Text } from '@mantine/core'
import mermaid from 'mermaid'

mermaid.initialize({
  startOnLoad: false,
  theme: 'base',
  themeVariables: {
    lineColor: '#94a3b8',
    primaryColor: '#e0f2fe',
    primaryTextColor: '#1e293b',
    primaryBorderColor: '#94a3b8',
    secondaryColor: '#f0fdf4',
    secondaryTextColor: '#1e293b',
    secondaryBorderColor: '#94a3b8',
    tertiaryColor: '#fef3c7',
    tertiaryTextColor: '#1e293b',
    tertiaryBorderColor: '#94a3b8',
    edgeLabelBackground: '#ffffff',
    fontSize: '14px',
  },
})

interface Transform { x: number; y: number; scale: number }

interface DiagramData {
  summary: string
  detail: string | null
}

function parseMermaidDiagram(output: unknown): DiagramData | null {
  let data: unknown = output
  if (typeof data === 'string') {
    try { data = JSON.parse(data) } catch { return null }
  }
  if (data && typeof data === 'object') {
    const o = data as Record<string, unknown>
    if (typeof o.mermaid_diagram === 'string') {
      return {
        summary: o.mermaid_diagram,
        detail: typeof o.mermaid_diagram_detail === 'string' ? o.mermaid_diagram_detail : null,
      }
    }
  }
  return null
}

export function MermaidPanel({ output }: { output: unknown }) {
  const diagramData = parseMermaidDiagram(output)
  const [view, setView] = useState<'summary' | 'detail'>('summary')
  const diagram = diagramData ? (view === 'detail' && diagramData.detail ? diagramData.detail : diagramData.summary) : null
  const mermaidRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ sx: number; sy: number; tx: number; ty: number } | null>(null)
  const [tf, setTf] = useState<Transform>({ x: 0, y: 0, scale: 1 })
  const [dragging, setDragging] = useState(false)

  useEffect(() => {
    if (!diagram || !mermaidRef.current) return
    let cancelled = false
    const el = mermaidRef.current
    el.removeAttribute('data-processed')
    el.innerHTML = diagram
    mermaid.run({ nodes: [el] })
      .then(() => {
        if (cancelled || !el.isConnected) return
        const svg = el.querySelector('svg')
        if (!svg) return
        if (!svg.getAttribute('viewBox')) {
          const w = parseFloat(svg.getAttribute('width') ?? '0')
          const h = parseFloat(svg.getAttribute('height') ?? '0')
          if (w > 0 && h > 0) svg.setAttribute('viewBox', `0 0 ${w} ${h}`)
        }
        svg.setAttribute('width', '100%')
        svg.style.maxWidth = 'none'
        svg.style.display = 'block'
        // Thicken lines for better visibility
        svg.querySelectorAll('.flowchart-link, .edge-pattern-solid, path.path').forEach((path) => {
          ;(path as SVGElement).style.strokeWidth = '2px'
        })
      })
      .catch(() => {}) // element may be detached before async render completes
    setTf({ x: 0, y: 0, scale: 1 })
    return () => { cancelled = true }
  }, [diagram])

  if (!diagramData) return null

  return (
    <Card
      withBorder mt="sm" p="xs"
      style={{ background: '#ffffff', border: '1px solid #e2e8f0' }}
    >
      <Group justify="flex-end" mb={4} gap="xs">
        {diagramData.detail && (
          <SegmentedControl
            size="xs"
            value={view}
            onChange={(v) => setView(v as 'summary' | 'detail')}
            data={[
              { label: 'Summary', value: 'summary' },
              { label: 'Detail', value: 'detail' },
            ]}
          />
        )}
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
