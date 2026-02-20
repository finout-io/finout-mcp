import Highcharts from 'highcharts'
import HighchartsReact from 'highcharts-react-official'
import { Card } from '@mantine/core'

const COLORS = [
  '#38B28E', '#4B9BFF', '#FF8C42', '#C678DD',
  '#FFD632', '#61AFEF', '#98C379', '#E06C75',
  '#56B6C2', '#D19A66',
]

const parseCost = (s: unknown): number => {
  if (typeof s === 'number') return s
  if (typeof s !== 'string') return 0
  return parseFloat(s.replace(/[$,]/g, '')) || 0
}

const labelStyle = { color: '#C1C2C5', fontSize: '11px' }
const isDateLike = (s: string) => /^\d{4}-\d{2}-\d{2}/.test(s)

// ── chart builders ────────────────────────────────────────────────────────────

function makeBarColumnOptions(
  type: 'bar' | 'column',
  title: string,
  categories: string[],
  series: Highcharts.SeriesOptionsType[],
): Highcharts.Options {
  return {
    chart: { type, height: 280, backgroundColor: 'transparent' },
    colors: COLORS,
    credits: { enabled: false },
    title: { text: title, style: { color: '#C1C2C5', fontSize: '13px' } },
    xAxis: {
      categories,
      labels: { style: labelStyle },
      lineColor: '#373A40',
      tickColor: '#373A40',
    },
    yAxis: {
      gridLineColor: '#373A40',
      labels: {
        style: labelStyle,
        formatter: function (this: Highcharts.AxisLabelsFormatterContextObject): string {
          return `$${Number(this.value).toLocaleString()}`
        },
      },
      title: { text: undefined },
    },
    plotOptions: {
      bar: { colorByPoint: series.length === 1 },
      column: { colorByPoint: series.length === 1 },
    },
    legend: { itemStyle: { color: '#C1C2C5' }, enabled: series.length > 1 },
    tooltip: { valuePrefix: '$' },
    series,
  }
}

function makeStackedBarOptions(
  title: string,
  categories: string[],
  series: Highcharts.SeriesOptionsType[],
): Highcharts.Options {
  return {
    chart: { type: 'column', height: 320, backgroundColor: 'transparent' },
    colors: COLORS,
    credits: { enabled: false },
    title: { text: title, style: { color: '#C1C2C5', fontSize: '13px' } },
    xAxis: {
      categories,
      labels: { style: labelStyle, rotation: -45 },
      lineColor: '#373A40',
      tickColor: '#373A40',
    },
    yAxis: {
      gridLineColor: '#373A40',
      labels: {
        style: labelStyle,
        formatter: function (this: Highcharts.AxisLabelsFormatterContextObject): string {
          return `$${Number(this.value).toLocaleString()}`
        },
      },
      title: { text: undefined },
    },
    plotOptions: {
      column: { stacking: 'normal' },
    },
    legend: { itemStyle: { color: '#C1C2C5' } },
    tooltip: { valuePrefix: '$', shared: true },
    series,
  }
}

function makePieOptions(
  title: string,
  points: Array<{ name: string; y: number }>,
): Highcharts.Options {
  return {
    chart: { type: 'pie', height: 320, backgroundColor: 'transparent' },
    colors: COLORS,
    credits: { enabled: false },
    title: { text: title, style: { color: '#C1C2C5', fontSize: '13px' } },
    tooltip: {
      formatter: function (this: Highcharts.Point): string {
        const pct = ((this as unknown as { percentage?: number }).percentage ?? 0).toFixed(1)
        const cost = (this.y ?? 0).toLocaleString()
        return `<b>${String(this.name ?? '')}</b>: <b>$${cost}</b> (${pct}%)`
      },
    },
    plotOptions: {
      pie: {
        dataLabels: {
          enabled: points.length <= 8,
          format: '{point.name}: {point.percentage:.1f}%',
          style: { color: '#C1C2C5', fontSize: '10px', textOutline: 'none' },
          distance: 15,
        },
        showInLegend: points.length > 8,
      },
    },
    legend: { itemStyle: { color: '#C1C2C5', fontSize: '11px' } },
    series: [{ type: 'pie', name: 'Cost', data: points }],
  }
}

function makeLineOptions(
  title: string,
  categories: string[],
  data: number[],
): Highcharts.Options {
  return {
    chart: { type: 'line', height: 280, backgroundColor: 'transparent' },
    colors: COLORS,
    credits: { enabled: false },
    title: { text: title, style: { color: '#C1C2C5', fontSize: '13px' } },
    xAxis: {
      categories,
      labels: { style: labelStyle, rotation: -45 },
      lineColor: '#373A40',
      tickColor: '#373A40',
    },
    yAxis: {
      gridLineColor: '#373A40',
      labels: {
        style: labelStyle,
        formatter: function (this: Highcharts.AxisLabelsFormatterContextObject): string {
          return `$${Number(this.value).toLocaleString()}`
        },
      },
      title: { text: undefined },
    },
    legend: { itemStyle: { color: '#C1C2C5' } },
    tooltip: { valuePrefix: '$' },
    series: [{ type: 'line', name: 'Cost', data, showInLegend: false }],
  }
}

// ── shape detection ───────────────────────────────────────────────────────────

/** Try to build a stacked bar from nested-children data on each service row. */
function tryStackedFromNested(
  rows: Array<Record<string, unknown>>,
  title: string,
): Highcharts.Options | null {
  // Look for a sub-array field on the first item
  const NESTED_KEYS = ['children', 'data', 'breakdown', 'items', 'daily', 'series']
  const nestedKey = NESTED_KEYS.find((k) => Array.isArray(rows[0][k]))
  if (!nestedKey) return null

  const firstNested = rows[0][nestedKey] as Array<Record<string, unknown>>
  if (firstNested.length < 2) return null

  // Find date and cost field names inside the nested items
  const DATE_KEYS = ['date', 'name', 'x', 'period', 'xAxis', 'timestamp']
  const COST_KEYS = ['cost', 'totalCost', 'value', 'y', 'amount']
  const dateField = DATE_KEYS.find((f) => firstNested[0] && f in firstNested[0])
  const costField = COST_KEYS.find((f) => firstNested[0] && f in firstNested[0])
  if (!dateField || !costField) return null

  // Collect all dates across all service rows
  const allDates = new Set<string>()
  for (const row of rows) {
    const nested = row[nestedKey] as Array<Record<string, unknown>>
    for (const n of nested) allDates.add(String(n[dateField] ?? ''))
  }
  const dates = Array.from(allDates).sort()

  const series: Highcharts.SeriesOptionsType[] = rows.slice(0, 10).map((r) => {
    const nested = r[nestedKey] as Array<Record<string, unknown>>
    const costByDate: Record<string, number> = {}
    for (const n of nested) costByDate[String(n[dateField] ?? '')] = parseCost(n[costField])
    return { type: 'column' as const, name: String(r.name), data: dates.map((d) => costByDate[d] ?? 0) }
  })

  return makeStackedBarOptions(title, dates, series)
}

/** Try to build a stacked bar from a flat list where service names repeat per date. */
function tryStackedFromFlat(
  rows: Array<Record<string, unknown>>,
  title: string,
): Highcharts.Options | null {
  const uniqueNames = new Set(rows.map((r) => String(r.name)))
  if (uniqueNames.size >= rows.length) return null // no duplicates → not a 2D flat list

  // Find which field holds the date
  const DATE_KEYS = ['date', 'xAxis', 'x', 'period', 'timestamp']
  const dateField = DATE_KEYS.find((f) => rows[0] && f in rows[0] && rows[0][f] !== undefined)
  if (!dateField) return null

  const services = Array.from(uniqueNames).filter((n) => n !== 'Total')
  const dateSet = new Set<string>()
  for (const r of rows) dateSet.add(String(r[dateField] ?? ''))
  const dates = Array.from(dateSet).sort()

  const costMap: Record<string, Record<string, number>> = {}
  for (const r of rows) {
    const svc = String(r.name)
    const d = String(r[dateField] ?? '')
    if (!costMap[svc]) costMap[svc] = {}
    costMap[svc][d] = r.totalCost as number
  }

  const series: Highcharts.SeriesOptionsType[] = services.slice(0, 10).map((svc) => ({
    type: 'column' as const,
    name: svc,
    data: dates.map((d) => costMap[svc]?.[d] ?? 0),
  }))

  return makeStackedBarOptions(title, dates, series)
}

// ── main ──────────────────────────────────────────────────────────────────────

function buildOptions(output: unknown): Highcharts.Options | null {
  let data: unknown = output
  if (typeof data === 'string') {
    try {
      data = JSON.parse(data)
    } catch {
      return null
    }
  }
  if (!data || typeof data !== 'object') return null
  const o = data as Record<string, unknown>

  // Shape 1: query_costs with group_by
  // API: { time_period, group_by: [...], data: [{name, totalCost}, ...] }
  if (Array.isArray(o.data) && Array.isArray(o.group_by) && (o.group_by as unknown[]).length > 0) {
    const rows = (o.data as Array<Record<string, unknown>>)
      .filter((r) => r.name !== undefined && r.name !== 'Total' && typeof r.totalCost === 'number')
      .slice(0, 30)
    if (rows.length < 2) return null

    const names = rows.map((r) => String(r.name))
    const costs = rows.map((r) => r.totalCost as number)
    const period = typeof o.time_period === 'string' ? o.time_period : ''
    const title = period ? `Costs — ${period}` : 'Costs by Group'

    // 2D breakdown: stacked bar (nested children or flat duplicates)
    const stacked = tryStackedFromNested(rows, title) ?? tryStackedFromFlat(rows, title)
    if (stacked) return stacked

    // 1D time-series: line chart
    if (names.every(isDateLike)) return makeLineOptions(title, names, costs)

    // 1D categorical: pie chart
    return makePieOptions(title, rows.slice(0, 15).map((r) => ({ name: String(r.name), y: r.totalCost as number })))
  }

  // Shape 2: compare_costs with group_by
  // { current_total, breakdown_by_group: [{name, current_cost, comparison_cost}, ...] }
  if ('current_total' in o && Array.isArray(o.breakdown_by_group)) {
    const groups = o.breakdown_by_group as Array<Record<string, unknown>>
    if (groups.length === 0) return null
    return makeBarColumnOptions(
      'column',
      'Cost Comparison',
      groups.map((g) => String(g.name ?? '')),
      [
        { type: 'column', name: 'Current', data: groups.map((g) => parseCost(g.current_cost)) },
        { type: 'column', name: 'Previous', data: groups.map((g) => parseCost(g.comparison_cost)) },
      ],
    )
  }

  // Shape 3: get_waste_recommendations
  // { recommendations: [{resource, potential_monthly_savings}, ...] }
  if (Array.isArray(o.recommendations)) {
    const recs = (o.recommendations as Array<Record<string, unknown>>)
      .slice(0, 10)
      .sort((a, b) => parseCost(b.potential_monthly_savings) - parseCost(a.potential_monthly_savings))
    if (recs.length === 0) return null
    return makeBarColumnOptions(
      'bar',
      'Waste Recommendations — Monthly Savings',
      recs.map((r) => String(r.resource ?? '')),
      [{ type: 'bar', name: 'Savings', data: recs.map((r) => parseCost(r.potential_monthly_savings)), showInLegend: false }],
    )
  }

  // Shape 4: get_anomalies
  // { anomalies: [{service, cost_impact}, ...] }
  if (Array.isArray(o.anomalies)) {
    const anomalies = o.anomalies as Array<Record<string, unknown>>
    if (anomalies.length === 0) return null
    const byService: Record<string, number> = {}
    for (const a of anomalies) {
      const svc = String(a.service ?? 'Unknown')
      byService[svc] = (byService[svc] ?? 0) + parseCost(a.cost_impact)
    }
    const entries = Object.entries(byService).sort((a, b) => b[1] - a[1])
    return makeBarColumnOptions(
      'column',
      'Cost Anomalies by Service',
      entries.map(([svc]) => svc),
      [{ type: 'column', name: 'Cost Impact', data: entries.map(([, v]) => v), showInLegend: false }],
    )
  }

  return null
}

export function ChartPanel({ output }: { output: unknown }) {
  const options = buildOptions(output)
  if (!options) return null
  return (
    <Card
      withBorder
      mt="sm"
      p="xs"
      style={{ background: 'rgba(0,0,0,0.2)', border: '1px solid #373A40' }}
    >
      <HighchartsReact highcharts={Highcharts} options={options} />
    </Card>
  )
}
