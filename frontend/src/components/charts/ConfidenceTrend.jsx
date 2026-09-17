/**
 * Milestone 8F.1 — Analysis Confidence Trend (Recharts area chart).
 *
 * One point per real History record, ordered oldest -> newest by the pure
 * builder in insightsData.js. X axis = analysis time, Y axis = decision
 * confidence %. With a single record the lone dot still renders (centered);
 * with none the parent shows the existing empty state instead.
 */
import { useMemo } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'

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

function TrendTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null
  return (
    <div className="chart-tooltip chart-tooltip-wide" role="status">
      <strong className="chart-tooltip-title">{point.title}</strong>
      <span className={`chart-tooltip-verdict ${point.prediction === 'Scam' ? 'verdict-scam' : 'verdict-legit'}`}>
        {point.prediction}
      </span>
      <span>Confidence: {point.confidencePct.toFixed(1)}%</span>
      <span>{fullDate(point.time)}</span>
    </div>
  )
}

export default function ConfidenceTrend({ series }) {
  const data = useMemo(() => (series || []).map((point) => ({
    ...point,
    confidencePct: Math.round(point.confidence * 1000) / 10,
  })), [series])
  if (!data.length) return null

  // Axis ticks: when every analysis happened on the same day, the
  // informative unit is the TIME of day; otherwise the date.
  const sameDay = data.length > 1 &&
    new Date(data[0].time).toDateString() === new Date(data[data.length - 1].time).toDateString()
  const tickLabel = sameDay ? shortTime : shortDate

  return (
    <div className="trend-wrap">
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={data} margin={{ top: 12, right: 18, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="confFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#e1833f" stopOpacity={0.22} />
              <stop offset="100%" stopColor="#e1833f" stopOpacity={0.02} />
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
          <Area
            type="monotone"
            dataKey="confidencePct"
            stroke="var(--primary)"
            strokeWidth={2}
            fill="url(#confFill)"
            dot={{ r: 3.5, fill: 'var(--primary-bright)', stroke: 'var(--bg)', strokeWidth: 1 }}
            activeDot={{ r: 5, fill: 'var(--primary-bright)', stroke: 'var(--bg)', strokeWidth: 1 }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
