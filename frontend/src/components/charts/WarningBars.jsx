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
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LabelList,
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

  // Severity keys actually present in the user's real evidence maps —
  // rendered as text (never color-only), no invented categories.
  const severities = [...new Set(data.map((flag) => flag.severity).filter(Boolean))]
  return (
    <div className="bars-wrap">
      <ResponsiveContainer width="100%" height={Math.max(160, data.length * 44 + 34)}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, bottom: 0, left: 4 }}>
          {/* Count labels at the right end of each bar make a numeric x axis
              redundant — the axis is hidden, the counts stay exact. */}
          <XAxis type="number" domain={[0, max]} allowDecimals={false} hide />
          <YAxis
            type="category"
            dataKey="category"
            tickFormatter={titleCaseCategory}
            tick={{ fill: 'var(--ink)', fontSize: 12.5, fontWeight: 600 }}
            stroke="var(--border-strong)"
            width={188}
          />
          <Tooltip content={<BarsTooltip />} cursor={{ fill: 'var(--primary-soft)' }} />
          <Bar dataKey="count" barSize={16} radius={[0, 6, 6, 0]} isAnimationActive={false}>
            {data.map((flag) => (
              <Cell key={flag.category} fill={SEVERITY_COLORS[flag.severity] || 'var(--primary)'} />
            ))}
            <LabelList
              dataKey="count"
              position="right"
              offset={10}
              fill="var(--ink-strong)"
              fontSize={12}
              fontWeight={700}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      {severities.length > 0 && (
        <div className="bars-severity">
          {severities.map((severity) => (
            <span className="bars-severity-item" key={severity}>
              <span
                className="legend-dot"
                style={{ background: SEVERITY_COLORS[severity] || 'var(--primary)' }}
              />
              {titleCaseCategory(severity)} severity
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
