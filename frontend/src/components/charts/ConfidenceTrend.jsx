/**
 * Milestones 8F.1 + 8F.2A — Analysis Confidence Trend (Recharts area chart).
 *
 * One point per REAL History record, ordered oldest -> newest by the pure
 * builder in insightsData.js. X axis = analysis time, Y axis = decision
 * confidence % (0–100). Nothing here invents data: no interpolation between
 * records, no padding, no synthetic peaks — the smooth `monotone` curve only
 * controls how the line is drawn BETWEEN exact real values, and every marker
 * on the chart maps 1:1 to a History row.
 *
 * 8F.2A presentation layer: premium signal-style look — soft gradient fill,
 * restrained glow (a wider low-opacity stroke of the SAME series behind the
 * crisp line), clean per-record markers with an emphasized "Latest" point,
 * a themed tooltip showing that exact record, and compact Highest / Lowest /
 * Average chips computed from the same series. With a single record the lone
 * dot still renders; with none the component shows the empty state.
 */
import { useMemo } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { toPercent01, computeTrendSummary } from '../../insightsData.js'

function shortDate(ms) {
  if (!Number.isFinite(ms)) return ''
  return new Date(ms).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function shortTime(ms) {
  if (!Number.isFinite(ms)) return ''
  return new Date(ms).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

function fullDate(ms) {
  if (!Number.isFinite(ms)) return ''
  return new Date(ms).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/**
 * Tooltip for a hovered REAL point — every value comes straight from the
 * matching History record carried on the chart point (never recomputed,
 * never renamed internals).
 */
function TrendTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null
  return (
    <div className="chart-tooltip chart-tooltip-wide trend-tooltip" role="status">
      <strong className="chart-tooltip-title">{point.title}</strong>
      <span className="trend-tooltip-meta">
        <span className={`chart-tooltip-verdict ${point.prediction === 'Scam' ? 'verdict-scam' : 'verdict-legit'}`}>
          {point.prediction}
        </span>
        <span className="trend-tooltip-confidence">Confidence: <strong>{point.confidencePct.toFixed(1)}%</strong></span>
      </span>
      <span className="trend-tooltip-date">{fullDate(point.time)}</span>
    </div>
  )
}

/**
 * Marker for one REAL record: small clean dot normally, slightly larger for
 * the newest record (labelled "Latest"). Rendered once per History row —
 * never for interpolated positions.
 */
function TrendDot({ cx, cy, index, dataLength }) {
  if (!Number.isFinite(cx) || !Number.isFinite(cy)) return null
  const isLatest = index === dataLength - 1
  return (
    <g>
      <circle
        className="trend-dot"
        cx={cx}
        cy={cy}
        r={isLatest ? 5 : 3.5}
        fill="var(--primary-bright)"
        stroke="var(--surface)"
        strokeWidth={isLatest ? 2 : 1.5}
      />
      {isLatest && (
        <text x={cx} y={cy - 10} textAnchor="middle" fontSize={10} fontWeight={700} fill="var(--primary-dark)">
          Latest
        </text>
      )}
    </g>
  )
}

export default function ConfidenceTrend({ series }) {
  const data = useMemo(() => (series || []).map((point) => ({
    ...point,
    confidencePct: Math.round(point.confidence * 1000) / 10,
  })), [series])
  // Summary chips read the SAME real points the curve draws.
  const summary = useMemo(() => computeTrendSummary(data), [data])

  if (!data.length) {
    return (
      <div className="trend-empty" role="status">
        <strong>No confidence data yet.</strong>
        <p>Analyze a job to begin building your confidence trend.</p>
      </div>
    )
  }

  // Axis ticks: when every analysis happened on the same day, the
  // informative unit is the TIME of day; otherwise the date.
  const sameDay = data.length > 1 &&
    new Date(data[0].time).toDateString() === new Date(data[data.length - 1].time).toDateString()
  const tickLabel = sameDay ? shortTime : shortDate

  return (
    <div className="trend-wrap">
      <div className="trend-chips" aria-label="Confidence summary">
        <div className="trend-chip"><span>Highest</span><strong>{toPercent01(summary.highest)}</strong></div>
        <div className="trend-chip"><span>Lowest</span><strong>{toPercent01(summary.lowest)}</strong></div>
        <div className="trend-chip"><span>Average</span><strong>{toPercent01(summary.average)}</strong></div>
      </div>
      <ResponsiveContainer width="100%" height={250}>
        <AreaChart data={data} margin={{ top: 22, right: 24, bottom: 4, left: 0 }}>
          <defs>
            <linearGradient id="confFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#F0E933" stopOpacity={0.20} />
              <stop offset="55%" stopColor="#F0E933" stopOpacity={0.06} />
              <stop offset="100%" stopColor="#F0E933" stopOpacity={0.01} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--border)" strokeOpacity={0.55} strokeDasharray="3 6" vertical={false} />
          <XAxis
            dataKey="time"
            /* One slot per real analysis, evenly spaced (dashboards render
               per-analysis trends this way when many share a day). Ticks are
               real dates from the records; the tooltip carries the exact
               timestamp. */
            tickFormatter={tickLabel}
            interval="preserveStartEnd"
            minTickGap={12}
            tick={{ fill: 'var(--muted-light)', fontSize: 12 }}
            stroke="var(--border-strong)"
            tickMargin={8}
          />
          <YAxis
            domain={[0, 100]}
            tickFormatter={(value) => `${value}%`}
            tick={{ fill: 'var(--muted-light)', fontSize: 12 }}
            stroke="var(--border-strong)"
            width={44}
            tickCount={5}
          />
          <Tooltip content={<TrendTooltip />} cursor={{ stroke: 'var(--border-strong)', strokeDasharray: '3 6' }} />
          {/* Restrained glow: the same real series drawn wider + fainter
              behind the crisp line. No extra points, no neon. */}
          <Area
            type="monotone"
            dataKey="confidencePct"
            stroke="var(--primary)"
            strokeWidth={7}
            strokeOpacity={0.14}
            fill="none"
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />
          <Area
            type="monotone"
            dataKey="confidencePct"
            stroke="var(--primary)"
            strokeWidth={2}
            fill="url(#confFill)"
            dot={<TrendDot dataLength={data.length} />}
            activeDot={{ r: 6, fill: 'var(--primary-bright)', stroke: 'var(--bg)', strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
