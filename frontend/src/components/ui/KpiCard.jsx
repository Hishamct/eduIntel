import React from 'react';
import './ui.css';

/**
 * KpiCard Component
 *
 * @param {Object} props
 * @param {string} props.title - Metric title / category label
 * @param {string|number} props.value - Large numeric / stat value
 * @param {string} [props.trend] - Percentage or rate change text (e.g. "+2.4%")
 * @param {'up'|'down'} [props.trendDirection='up'] - Direction for trend indicator color & icon
 * @param {number} [props.progressPercent] - Optional progress bar percentage (0 to 100)
 * @param {string} [props.progressColor] - Custom progress bar fill color (defaults based on trend or primary)
 */
export default function KpiCard({
  title = "Active Students",
  value = "12,842",
  trend = "+2.4%",
  trendDirection = 'up',
  progressPercent = 78,
  progressColor
}) {
  const isUp = trendDirection === 'up';
  const trendColor = isUp ? '#3C8C5D' : '#B23A2E';
  const trendIcon = isUp ? 'trending_up' : 'trending_down';

  const barFillColor = progressColor || (isUp ? '#26415E' : '#D9922E');

  return (
    <div
      className="edu-card"
      style={{
        padding: '20px',
        position: 'relative',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between'
      }}
    >
      {/* Top Header Row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <p
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: '11px',
            fontWeight: 700,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
            color: '#5F6774',
            margin: 0
          }}
        >
          {title}
        </p>
        {trend && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              fontWeight: 600,
              color: trendColor,
              display: 'flex',
              alignItems: 'center',
              gap: '4px'
            }}
          >
            {trend}
            <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>
              {trendIcon}
            </span>
          </span>
        )}
      </div>

      {/* Main Metric Value */}
      <h3
        className="edu-font-heading"
        style={{
          fontSize: '32px',
          fontWeight: 600,
          lineHeight: '40px',
          letterSpacing: '-0.02em',
          color: '#1B2330',
          margin: '12px 0 0 0'
        }}
      >
        {value}
      </h3>

      {/* Bottom Accent Progress Bar */}
      {typeof progressPercent === 'number' && (
        <div
          style={{
            position: 'absolute',
            bottom: 0,
            left: 0,
            width: '100%',
            height: '4px',
            backgroundColor: 'rgba(38, 65, 94, 0.1)'
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${Math.min(100, Math.max(0, progressPercent))}%`,
              backgroundColor: barFillColor,
              transition: 'width 0.6s ease'
            }}
          />
        </div>
      )}
    </div>
  );
}
