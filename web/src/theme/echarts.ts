import { SERIES, SEQUENTIAL, token } from './tokens'

/**
 * The ECharts theme, built from tokens.css at runtime so light and dark stay in one place.
 * Rules it encodes (docs/design.md): recessive axes and hairline grid, 2 px lines, no area
 * gradients, text in ink tokens, tabular figures, categorical colours in fixed order.
 */
export function pulseTheme(): Record<string, unknown> {
  const ink = token('ink')
  const muted = token('muted')
  const rule = token('rule')
  const font = token('font-text')
  const axis = {
    axisLine: { show: true, lineStyle: { color: rule } },
    axisTick: { show: false },
    axisLabel: { color: muted, fontSize: 12, fontFamily: font },
    splitLine: { show: true, lineStyle: { color: rule, width: 1, type: 'solid' } },
    nameTextStyle: { color: muted, fontSize: 12 },
  }
  return {
    color: SERIES.map(token),
    backgroundColor: 'transparent',
    textStyle: { color: ink, fontFamily: font, fontSize: 14 },
    title: { textStyle: { color: ink, fontSize: 16, fontWeight: 600 }, subtextStyle: { color: muted, fontSize: 14 } },
    legend: { textStyle: { color: muted, fontSize: 12 }, icon: 'roundRect', itemWidth: 12, itemHeight: 4, itemGap: 16 },
    tooltip: {
      backgroundColor: token('paper'),
      borderColor: rule,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: ink, fontSize: 13 },
      extraCssText: 'box-shadow:none;border-radius:2px;font-variant-numeric:tabular-nums;',
      axisPointer: { lineStyle: { color: muted, width: 1 }, crossStyle: { color: muted } },
    },
    grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
    categoryAxis: { ...axis, splitLine: { show: false } },
    valueAxis: { ...axis, axisLine: { show: false } },
    timeAxis: { ...axis, splitLine: { show: false } },
    line: { lineStyle: { width: 2 }, endLabel: { color: muted, fontSize: 12, fontFamily: font, textBorderWidth: 0 }, symbol: 'circle', symbolSize: 8, showSymbol: false, smooth: false, emphasis: { lineStyle: { width: 2 } } },
    bar: { barMaxWidth: 24, itemStyle: { borderRadius: [4, 4, 0, 0] } },
    visualMap: { inRange: { color: SEQUENTIAL.map(token) }, textStyle: { color: muted } },
    markLine: { lineStyle: { color: muted, type: 'dashed', width: 1 }, label: { color: muted }, symbol: 'none' },
  }
}
