/**
 * Milestone 8F.1 — Most Common Warning Signs (Recharts horizontal bars).
 *
 * Counts come from the saved evidence maps exactly as before (pure
 * aggregation in insightsData.js), sorted highest count first. Severity is
 * always shown as TEXT (tooltip + count label) — never color-only. Real
 * category names are never truncated: the label column is sized for the
 * longest approved category ("Excessive Capitalization").
 */
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { titleCaseCategory } from '../../insightsData.js'

// Continuity with the 7E severity tints: high -> coral, medium -> amber
// caution, low -> burnt orange. Severity is ALSO always shown as text.
const SEVERITY_COLORS = { high: 'var(--scam)', medium: 'var(--caution)', low: 'var(--primary)' }

function BarsTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const flag = payload[0]?.payload
  if (!flag) return null
  return (
    <div className="chart-tooltip" role="status">
      <strong>{titleCaseCategory(flag.category)}</strong>
      <span>Detected: {flag.count} {flag.count === 1 ? 'time' : 'times'}</span>
      {flag.severity && <span>Severity: {titleCaseCategory(flag.severity)}</span>}
    </div>
  )
}

export default function WarningBars({ flags }) {
  const data = flags || []
  if (!data.length) return null
  const max = data[0].count || 1

  return (
    <div className="bars-wrap">
      <ResponsiveContainer width="100%" height={Math.max(160, data.length * 42 + 40)}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 46, bottom: 0, left: 4 }}>
          <CartesianGrid stroke="var(--border)" strokeOpacity={0.55} strokeDasharray="3 6" horizontal={false} />
          <XAxis
            type="number"
            domain={[0, max]}
            allowDecimals={false}
            tick={{ fill: 'var(--muted-light)', fontSize: 12 }}
            stroke="var(--border-strong)"
            tickMargin={8}
          />
          <YAxis
            type="category"
            dataKey="category"
            tickFormatter={titleCaseCategory}
            tick={{ fill: 'var(--muted)', fontSize: 12.5 }}
            stroke="var(--border-strong)"
            width={188}
          />
          <Tooltip content={<BarsTooltip />} cursor={{ fill: 'var(--primary-soft)' }} />
          <Bar dataKey="count" barSize={18} radius={[0, 4, 4, 0]} isAnimationActive={false}>
            {data.map((flag) => (
              <Cell key={flag.category} fill={SEVERITY_COLORS[flag.severity] || 'var(--primary)'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
