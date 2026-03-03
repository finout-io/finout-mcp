import Highcharts from 'highcharts'
import HighchartsReact from 'highcharts-react-official'
import { Card } from '@mantine/core'

const COLORS = [
  '#38B28E', '#4B9BFF', '#FF8C42', '#C678DD',
  '#FFD632', '#61AFEF', '#98C379', '#E06C75',
  '#56B6C2', '#D19A66',
]

const labelStyle = { color: '#C1C2C5', fontSize: '11px' }

interface ChartSeries {
  name: string
  data: number[]
  color?: string
  y_axis?: number
}

type ChartType = 'bar' | 'line' | 'pie' | 'column'

interface RenderChartData {
  title: string
  chart_type: ChartType
  categories: string[]
  series: ChartSeries[]
  colors?: string[]
  y_axes?: Array<{
    label: string
    opposite?: boolean
    min?: number
    max?: number
  }>
  x_label?: string | null
  y_label?: string | null
}

const parseJsonSafely = (raw: string): unknown | null => {
  const trimmed = raw.trim()
  if (!trimmed) return null

  try {
    return JSON.parse(trimmed)
  } catch {
    // Continue with more permissive parsing below.
  }

  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)\s*```/i)
  if (fenced?.[1]) {
    try {
      return JSON.parse(fenced[1])
    } catch {
      // Continue
    }
  }

  const objectish = trimmed.match(/(\{[\s\S]*\}|\[[\s\S]*\])/)
  if (objectish?.[1]) {
    try {
      return JSON.parse(objectish[1])
    } catch {
      // Fall through
    }
  }

  return null
}

const VALID_TYPES: Set<ChartType> = new Set(['bar', 'line', 'pie', 'column'])

const isCostLikeLabel = (label?: string | null): boolean => {
  const text = (label ?? '').toLowerCase()
  if (!text) return true // Preserve old default behavior.
  return text.includes('$') || /(cost|savings|impact|spend|expense|amount)/.test(text)
}

const formatValue = (value: number, currency: boolean): string => {
  if (currency) return `$${value.toLocaleString()}`
  return value.toLocaleString()
}

const normalizeChartData = (candidate: RenderChartData): RenderChartData | null => {
  if (!VALID_TYPES.has(candidate.chart_type)) return null
  if (!Array.isArray(candidate.categories) || candidate.categories.length === 0) return null
  if (!Array.isArray(candidate.series) || candidate.series.length === 0) return null

  const categories = candidate.categories.map((c) => String(c))
  const expectedLen = categories.length

  const series = candidate.series
    .filter((s) => s && typeof s.name === 'string' && Array.isArray(s.data))
    .map((s) => ({
      name: s.name,
      data: s.data
        .slice(0, expectedLen)
        .map((v) => (typeof v === 'number' && Number.isFinite(v) ? v : Number(v)))
        .map((v) => (Number.isFinite(v) ? v : 0)),
      color: typeof s.color === 'string' && s.color.trim().length > 0 ? s.color : undefined,
      y_axis:
        typeof s.y_axis === 'number' && Number.isInteger(s.y_axis) && s.y_axis >= 0
          ? s.y_axis
          : undefined,
    }))
    .filter((s) => s.data.length === expectedLen)

  if (series.length === 0) return null

  const colors = Array.isArray(candidate.colors)
    ? candidate.colors.filter((c): c is string => typeof c === 'string' && c.trim().length > 0)
    : undefined

  const yAxes = Array.isArray(candidate.y_axes)
    ? candidate.y_axes
        .filter((axis) => axis && typeof axis.label === 'string' && axis.label.trim().length > 0)
        .map((axis) => ({
          label: axis.label,
          opposite: typeof axis.opposite === 'boolean' ? axis.opposite : false,
          min: typeof axis.min === 'number' ? axis.min : undefined,
          max: typeof axis.max === 'number' ? axis.max : undefined,
        }))
    : undefined

  if (candidate.chart_type === 'pie' && series.length > 1) {
    return {
      ...candidate,
      categories,
      series: [series[0]],
      colors,
      y_axes: yAxes,
    }
  }

  return {
    ...candidate,
    categories,
    series,
    colors,
    y_axes: yAxes,
  }
}

function parseChartData(output: unknown): RenderChartData | null {
  let data: unknown = output
  if (typeof data === 'string') {
    data = parseJsonSafely(data)
  }
  if (!data || typeof data !== 'object') return null

  const o = data as Record<string, unknown>
  if (
    typeof o.title !== 'string' ||
    typeof o.chart_type !== 'string' ||
    !Array.isArray(o.categories) ||
    !Array.isArray(o.series)
  ) {
    return null
  }

  return normalizeChartData(o as unknown as RenderChartData)
}

function buildOptions(chart: RenderChartData): Highcharts.Options {
  const { title, chart_type, categories, series, colors, y_axes, x_label, y_label } = chart
  const yTitle = y_label ?? 'Cost ($)'
  const currencyLike = isCostLikeLabel(yTitle)
  const palette = colors && colors.length > 0 ? colors : COLORS

  if (chart_type === 'pie') {
    const points = categories.map((name, i) => ({
      name,
      y: series[0]?.data[i] ?? 0,
    }))
    return {
      chart: { type: 'pie', height: 320, backgroundColor: 'transparent' },
      colors: palette,
      credits: { enabled: false },
      title: { text: title, style: { color: '#C1C2C5', fontSize: '13px' } },
      tooltip: {
        formatter: function (this: Highcharts.Point): string {
          const pct = ((this as unknown as { percentage?: number }).percentage ?? 0).toFixed(1)
          const value = formatValue(this.y ?? 0, currencyLike)
          return `<b>${String(this.name ?? '')}</b>: <b>${value}</b> (${pct}%)`
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
      series: [{ type: 'pie', name: series[0]?.name ?? 'Cost', data: points }],
    }
  }

  if (chart_type === 'line') {
    const hasMultiAxis = Array.isArray(y_axes) && y_axes.length > 0
    const hcSeries: Highcharts.SeriesOptionsType[] = series.map((s) => ({
      type: 'line' as const,
      name: s.name,
      data: s.data,
      color: s.color,
      yAxis: hasMultiAxis ? (s.y_axis ?? 0) : 0,
      showInLegend: series.length > 1,
    }))

    const lineYAxis: Highcharts.YAxisOptions | Highcharts.YAxisOptions[] = hasMultiAxis
      ? y_axes.map((axis, idx) => ({
          gridLineColor: '#373A40',
          labels: {
            style: labelStyle,
            formatter: function (this: Highcharts.AxisLabelsFormatterContextObject): string {
              const axisLabel = y_axes[idx]?.label ?? yTitle
              return formatValue(Number(this.value), isCostLikeLabel(axisLabel))
            },
          },
          title: { text: axis.label, style: { color: '#C1C2C5' } },
          opposite: axis.opposite ?? false,
          min: axis.min,
          max: axis.max,
        }))
      : {
          gridLineColor: '#373A40',
          labels: {
            style: labelStyle,
            formatter: function (this: Highcharts.AxisLabelsFormatterContextObject): string {
              return formatValue(Number(this.value), currencyLike)
            },
          },
          title: { text: yTitle, style: { color: '#C1C2C5' } },
        }

    return {
      chart: { type: 'line', height: 280, backgroundColor: 'transparent' },
      colors: palette,
      credits: { enabled: false },
      title: { text: title, style: { color: '#C1C2C5', fontSize: '13px' } },
      xAxis: {
        categories,
        labels: { style: labelStyle, rotation: -45 },
        lineColor: '#373A40',
        tickColor: '#373A40',
        title: x_label ? { text: x_label, style: { color: '#C1C2C5' } } : undefined,
      },
      yAxis: lineYAxis,
      legend: { itemStyle: { color: '#C1C2C5' } },
      tooltip: {
        formatter: function (this: Highcharts.Point): string {
          const axisRef = this.series.options.yAxis
          const axisIndex = typeof axisRef === 'number' ? axisRef : 0
          const axisLabel = hasMultiAxis ? y_axes?.[axisIndex]?.label : yTitle
          return `<b>${this.series.name}</b>: ${formatValue(this.y ?? 0, isCostLikeLabel(axisLabel))}`
        },
      },
      series: hcSeries,
    }
  }

  // bar or column
  const hcType = chart_type === 'bar' ? 'bar' : 'column'
  const hcSeries: Highcharts.SeriesOptionsType[] = series.map((s) => ({
    type: hcType as 'bar' | 'column',
    name: s.name,
    data: s.data,
    color: s.color,
  }))

  return {
    chart: { type: hcType, height: 280, backgroundColor: 'transparent' },
    colors: palette,
    credits: { enabled: false },
    title: { text: title, style: { color: '#C1C2C5', fontSize: '13px' } },
    xAxis: {
      categories,
      labels: { style: labelStyle },
      lineColor: '#373A40',
      tickColor: '#373A40',
      title: x_label ? { text: x_label, style: { color: '#C1C2C5' } } : undefined,
    },
    yAxis: {
      gridLineColor: '#373A40',
      labels: {
        style: labelStyle,
        formatter: function (this: Highcharts.AxisLabelsFormatterContextObject): string {
          return formatValue(Number(this.value), currencyLike)
        },
      },
      title: { text: yTitle, style: { color: '#C1C2C5' } },
    },
    plotOptions: {
      bar: { colorByPoint: series.length === 1 },
      column: { colorByPoint: series.length === 1 },
    },
    legend: { itemStyle: { color: '#C1C2C5' }, enabled: series.length > 1 },
    tooltip: {
      formatter: function (this: Highcharts.Point): string {
        return `<b>${this.series.name}</b>: ${formatValue(this.y ?? 0, currencyLike)}`
      },
    },
    series: hcSeries,
  }
}

export function ChartPanel({ output }: { output: unknown }) {
  const chart = parseChartData(output)
  if (!chart) return null
  const options = buildOptions(chart)
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
