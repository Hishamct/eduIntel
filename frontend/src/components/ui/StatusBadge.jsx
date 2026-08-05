import React from 'react';
import './ui.css';

/**
 * StatusBadge Component
 *
 * @param {Object} props
 * @param {'on-track'|'needs-attention'|'flagged-at-risk'} [props.variant='on-track'] - Badge variant identifier
 * @param {string} [props.label] - Display label (defaults to variant string uppercase)
 * @param {string} [props.customColor] - Override fill color if needed
 */
export default function StatusBadge({
  variant = 'on-track',
  label,
  customColor
}) {
  const variantStyles = {
    'on-track': {
      bg: '#3C8C5D',
      defaultLabel: 'ON-TRACK'
    },
    'needs-attention': {
      bg: '#D9922E',
      defaultLabel: 'NEEDS-ATTENTION'
    },
    'flagged-at-risk': {
      bg: '#B23A2E',
      defaultLabel: 'FLAGGED-AT-RISK'
    }
  };

  const current = variantStyles[variant] || variantStyles['on-track'];
  const backgroundColor = customColor || current.bg;
  const displayText = label || current.defaultLabel;

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '4px 12px',
        backgroundColor: backgroundColor,
        color: '#FFFFFF',
        fontFamily: 'var(--font-mono)',
        fontSize: '10px',
        fontWeight: 700,
        letterSpacing: '0.05em',
        borderRadius: '9999px',
        textTransform: 'uppercase',
        lineHeight: 1,
        whiteSpace: 'nowrap',
        boxShadow: '0 1px 2px rgba(0, 0, 0, 0.05)'
      }}
    >
      {displayText}
    </span>
  );
}
