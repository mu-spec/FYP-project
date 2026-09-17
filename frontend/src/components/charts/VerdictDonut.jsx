import { useState } from 'react'
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts'
import { toPercent01 } from '../../insightsData.js'

const COLORS = { Scam: 'var(--scam)', Legitimate: 'var(--legit)' }

/**
 * Milestone 8F.1 — Verdict Distribution donut (Recharts).
 *
 * Real Scam/Legitimate counts from the signed-in user's History only.
 * Semantic colors stay the approved tokens: scam -> coral, legitimate ->
 * sage. The center shows the total number of analyses; the legend shows
 * count + percentage and doubles as the keyboard focus target. Hovering a
 * slice OR focusing a legend item shows the same tooltip — rendered by this
 * component at a fixed spot, so it can never escape the viewport.
 */
export default function VerdictDonut({ distribution }) {
  const [activeIndex, setActiveIndex] = useState(null)
  const { total, scam, legitimate } = distribution || {}
  if (!total) return null

  const slices = [
    { name: 'Scam', value: scam.count, share: scam.share },
    { name: 'Legitimate', value: legitimate.count, share: legitimate.share },
  ].filter((slice) => slice.value > 0)
  const active = activeIndex !== null ? slices[activeIndex] : null

  return (
    <div className="donut-wrap">
      <div className="donut-chart">
        <ResponsiveContainer width="100%" height={240}>
          <PieChart>
            <Pie
              data={slices}
              dataKey="value"
              nameKey="name"
              innerRadius="66%"
              outerRadius="92%"
              startAngle={90}
              endAngle={-270}
              paddingAngle={slices.length > 1 ? 2 : 0}
              stroke="var(--bg)"
              strokeWidth={2}
              isAnimationActive={false}
              activeIndex={activeIndex ?? undefined}
              onMouseEnter={(_, index) => setActiveIndex(index)}
              onMouseLeave={() => setActiveIndex(null)}
            >
              {slices.map((slice) => (
                <Cell key={slice.name} fill={COLORS[slice.name]} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="donut-center" aria-hidden="true">
          <strong>{total.toLocaleString()}</strong>
          <span>Total analyses</span>
        </div>
        {active && (
          <div className="chart-tooltip donut-tooltip" role="status">
            <strong>{active.name}</strong>
            <span>
              {active.value} analys{active.value === 1 ? 'is' : 'es'} · {toPercent01(active.share)} of all
            </span>
          </div>
        )}
      </div>
      <ul className="donut-legend">
        {[{ name: 'Scam', ...scam }, { name: 'Legitimate', ...legitimate }].map((item) => {
          const sliceIndex = slices.findIndex((slice) => slice.name === item.name)
          return (
            <li key={item.name}>
              <button
                type="button"
                className={`donut-legend-item${activeIndex === sliceIndex ? ' is-active' : ''}`}
                onMouseEnter={() => sliceIndex >= 0 && setActiveIndex(sliceIndex)}
                onMouseLeave={() => setActiveIndex(null)}
                onFocus={() => sliceIndex >= 0 && setActiveIndex(sliceIndex)}
                onBlur={() => setActiveIndex(null)}
              >
                <span className={`legend-dot ${item.name === 'Scam' ? 'dot-scam' : 'dot-legit'}`} />
                {item.name} · {item.count} ({toPercent01(item.share)})
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
