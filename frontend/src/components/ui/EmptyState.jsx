import React from 'react';
import './ui.css';

/**
 * EmptyState Component
 *
 * @param {Object} props
 * @param {string} [props.icon="assignment_late"] - Symbol icon name
 * @param {string} [props.title="No recent assignments"]
 * @param {string} [props.message="All academic tasks for the current semester have been processed and archived."]
 * @param {string} [props.actionLabel] - Optional button text
 * @param {function(): void} [props.onAction] - Action button click handler
 */
export default function EmptyState({
  icon = "assignment_late",
  title = "No recent assignments",
  message = "All academic tasks for the current semester have been processed and archived.",
  actionLabel,
  onAction
}) {
  return (
    <div
      className="edu-card"
      style={{
        padding: '32px 24px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        height: '100%',
        minHeight: '220px'
      }}
    >
      {/* Icon Ring */}
      <div
        style={{
          width: '64px',
          height: '64px',
          borderRadius: '50%',
          backgroundColor: '#FAFAF7',
          border: '2px dashed #E5E5E1',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: '16px'
        }}
      >
        <span
          className="material-symbols-outlined"
          style={{ fontSize: '32px', color: 'rgba(95, 103, 116, 0.4)' }}
        >
          {icon}
        </span>
      </div>

      {/* Heading */}
      <h5
        className="edu-font-heading"
        style={{
          fontSize: '18px',
          fontWeight: 600,
          color: '#1B2330',
          margin: 0
        }}
      >
        {title}
      </h5>

      {/* Message Description */}
      <p
        style={{
          fontSize: '13px',
          color: '#5F6774',
          marginTop: '8px',
          maxWidth: '280px',
          lineHeight: '1.4',
          fontFamily: 'var(--font-body)'
        }}
      >
        {message}
      </p>

      {/* Optional Action Button */}
      {actionLabel && (
        <button
          onClick={onAction}
          className="edu-btn-secondary"
          style={{ marginTop: '16px' }}
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}
