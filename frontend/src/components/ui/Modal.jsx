import React, { useEffect } from 'react';
import './ui.css';

/**
 * Modal / Dialog Component
 *
 * @param {Object} props
 * @param {boolean} props.isOpen - Whether modal is visible
 * @param {function(): void} props.onClose - Close action handler
 * @param {string} [props.title="Confirmation"] - Modal header title
 * @param {React.ReactNode} [props.description] - Main message body
 * @param {string} [props.icon="warning"] - Header icon symbol
 * @param {'warning'|'danger'|'info'|'success'} [props.iconVariant='warning']
 * @param {string} [props.primaryLabel="CONFIRM ACTION"]
 * @param {function(): void} [props.onPrimary]
 * @param {string} [props.secondaryLabel="CANCEL"]
 * @param {function(): void} [props.onSecondary]
 * @param {string} [props.footerNote] - Small metadata note displayed at the bottom
 */
export default function Modal({
  isOpen = false,
  onClose,
  title = "De-enrollment Confirmation",
  description = "Are you sure you want to proceed with this action?",
  icon = "warning",
  iconVariant = "danger",
  primaryLabel = "CONFIRM WITHDRAWAL",
  onPrimary,
  secondaryLabel = "CANCEL ACTION",
  onSecondary,
  footerNote = "LOGGED UNDER: ADMIN_SECURE_AUTH"
}) {
  // Handle escape key
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape' && isOpen && onClose) {
        onClose();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const iconColors = {
    warning: { bg: 'rgba(217, 146, 46, 0.1)', color: '#D9922E' },
    danger: { bg: 'rgba(178, 58, 46, 0.1)', color: '#B23A2E' },
    info: { bg: 'rgba(38, 65, 94, 0.1)', color: '#26415E' },
    success: { bg: 'rgba(60, 140, 93, 0.1)', color: '#3C8C5D' }
  };

  const currentIconStyle = iconColors[iconVariant] || iconColors.warning;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px'
      }}
    >
      {/* Backdrop Overlay */}
      <div
        onClick={onClose}
        style={{
          position: 'absolute',
          inset: 0,
          backgroundColor: 'rgba(38, 65, 94, 0.3)',
          backdropFilter: 'blur(4px)',
          WebkitBackdropFilter: 'blur(4px)'
        }}
      />

      {/* Modal Dialog Card */}
      <div
        style={{
          position: 'relative',
          width: '100%',
          maxWidth: '440px',
          backgroundColor: '#FFFFFF',
          border: '1px solid #E5E5E1',
          borderRadius: '4px',
          boxShadow: '0 10px 25px -5px rgba(38, 65, 94, 0.15)',
          overflow: 'hidden',
          zIndex: 101
        }}
      >
        <div style={{ padding: '24px' }}>
          {/* Top Bar: Icon + Close button */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
            <div
              style={{
                width: '44px',
                height: '44px',
                borderRadius: '50%',
                backgroundColor: currentIconStyle.bg,
                color: currentIconStyle.color,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: '26px' }}>
                {icon}
              </span>
            </div>
            <button
              onClick={onClose}
              style={{
                background: 'transparent',
                border: 'none',
                color: '#5F6774',
                cursor: 'pointer',
                padding: '4px',
                borderRadius: '4px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#F1F1ED')}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
            >
              <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>
                close
              </span>
            </button>
          </div>

          {/* Title & Description */}
          <h3
            className="edu-font-heading"
            style={{
              fontSize: '20px',
              fontWeight: 600,
              color: '#1B2330',
              margin: '0 0 8px 0'
            }}
          >
            {title}
          </h3>
          <div
            style={{
              fontSize: '14px',
              color: '#5F6774',
              lineHeight: '1.5',
              fontFamily: 'var(--font-body)'
            }}
          >
            {description}
          </div>

          {/* Action Button Pair */}
          <div style={{ marginTop: '24px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <button
              onClick={onPrimary}
              style={{
                width: '100%',
                padding: '12px',
                backgroundColor: iconVariant === 'danger' ? '#B23A2E' : '#26415E',
                color: '#FFFFFF',
                border: 'none',
                borderRadius: '4px',
                fontFamily: 'var(--font-body)',
                fontSize: '11px',
                fontWeight: 700,
                letterSpacing: '0.05em',
                textTransform: 'uppercase',
                cursor: 'pointer',
                transition: 'filter 0.15s ease'
              }}
              onMouseEnter={(e) => (e.currentTarget.style.filter = 'brightness(1.1)')}
              onMouseLeave={(e) => (e.currentTarget.style.filter = 'none')}
            >
              {primaryLabel}
            </button>
            <button
              onClick={onSecondary || onClose}
              className="edu-btn-secondary"
              style={{
                width: '100%',
                padding: '12px',
                border: '1px solid #E5E5E1',
                color: '#5F6774',
                fontSize: '11px'
              }}
            >
              {secondaryLabel}
            </button>
          </div>
        </div>

        {/* Optional Footer Note */}
        {footerNote && (
          <div
            style={{
              padding: '8px 16px',
              backgroundColor: '#E8E8E5',
              borderTop: '1px solid #E5E5E1',
              textAlign: 'center',
              fontSize: '10px',
              fontFamily: 'var(--font-mono)',
              color: '#5F6774',
              letterSpacing: '0.05em'
            }}
          >
            {footerNote}
          </div>
        )}
      </div>
    </div>
  );
}
