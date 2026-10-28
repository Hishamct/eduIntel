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
  customColor,
  customBg
}) {
  const variantStyles = {
    'on-track': {
      bg: '#DCFCE7',
      text: '#15803D',
      defaultLabel: 'ON-TRACK'
    },
    'needs-attention': {
      bg: '#FEF3C7',
      text: '#B45309',
      defaultLabel: 'NEEDS-ATTENTION'
    },
    'flagged-at-risk': {
      bg: '#FEE2E2',
      text: '#B91C1C',
      defaultLabel: 'FLAGGED-AT-RISK'
    },
    'low-risk': {
      bg: '#DCFCE7',
      text: '#15803D',
      defaultLabel: 'LOW RISK'
    },
    'medium-risk': {
      bg: '#FEF3C7',
      text: '#B45309',
      defaultLabel: 'MEDIUM RISK'
    },
    'high-risk': {
      bg: '#FEE2E2',
      text: '#B91C1C',
      defaultLabel: 'HIGH RISK'
    },
    'info': {
      bg: '#E0F2FE',
      text: '#0369A1',
      defaultLabel: 'INFO'
    }
  };

  const current = variantStyles[variant] || variantStyles['on-track'];
  const backgroundColor = customBg || current.bg;
  const textColor = customColor || current.text;
  const displayText = label || current.defaultLabel;

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '3px 10px',
        backgroundColor: backgroundColor,
        color: textColor,
        fontFamily: 'var(--font-body)',
        fontSize: '11px',
        fontWeight: 700,
        letterSpacing: '0.04em',
        borderRadius: '9999px',
        textTransform: 'uppercase',
        lineHeight: 1.2,
        whiteSpace: 'nowrap',
        boxShadow: '0 1px 2px rgba(0, 0, 0, 0.02)'
      }}
    >
      {displayText}
    </span>
  );
}
