import * as core from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'

// Named imports, not namespace imports, so the bundler drops every chart and component
// the report does not use. Chart.tsx loads this module on the first chart. The charts set
// `aria: { enabled: false }` because <Figure> provides the table view.
core.use([LineChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, SVGRenderer])

export { core }
