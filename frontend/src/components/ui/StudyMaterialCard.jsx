import React from 'react';
import './ui.css';

/**
 * StudyMaterialCard Component
 *
 * @param {Object} props
 * @param {string} [props.title="Advanced Calculus & Linear Algebra Notes"]
 * @param {string} [props.subject="MATHEMATICS"] - Subject tag text
 * @param {'pdf'|'docx'|'video'|'slide'} [props.fileType="pdf"] - Format icon
 * @param {string} [props.date="Oct 14, 2026"]
 * @param {string} [props.fileSize="4.2 MB"]
 * @param {function(): void} [props.onDownload]
 * @param {function(): void} [props.onView]
 */
export default function StudyMaterialCard({
  title = "Advanced Calculus & Linear Algebra Notes",
  subject = "MATHEMATICS",
  fileType = "pdf",
  date = "Oct 14, 2026",
  fileSize = "4.2 MB",
  onDownload,
  onView
}) {
  // Determine icon & color theme based on fileType
  const typeConfigs = {
    pdf: { icon: 'picture_as_pdf', color: '#B23A2E', bg: 'rgba(178, 58, 46, 0.1)', tag: 'PDF' },
    docx: { icon: 'description', color: '#26415E', bg: 'rgba(38, 65, 94, 0.1)', tag: 'DOCX' },
    video: { icon: 'play_circle', color: '#C97A2B', bg: 'rgba(201, 122, 43, 0.1)', tag: 'VIDEO' },
    slide: { icon: 'slideshow', color: '#D9922E', bg: 'rgba(217, 146, 46, 0.1)', tag: 'SLIDES' }
  };

  const config = typeConfigs[fileType?.toLowerCase()] || typeConfigs.pdf;

  return (
    <div
      className="edu-card"
      style={{
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        position: 'relative',
        transition: 'transform 0.15s ease, box-shadow 0.15s ease'
      }}
    >
      {/* Top Meta Bar: Subject tag & File Type pill */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <span
          style={{
            fontSize: '10px',
            fontWeight: 700,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
            color: '#26415E',
            backgroundColor: '#F0F4F8',
            padding: '3px 8px',
            borderRadius: '2px',
            fontFamily: 'var(--font-body)'
          }}
        >
          {subject}
        </span>

        <span
          style={{
            fontSize: '10px',
            fontWeight: 700,
            color: config.color,
            backgroundColor: config.bg,
            padding: '2px 6px',
            borderRadius: '2px',
            fontFamily: 'var(--font-mono)'
          }}
        >
          {config.tag}
        </span>
      </div>

      {/* Main Content Area: Icon + Title */}
      <div style={{ display: 'flex', gap: '14px', alignItems: 'flex-start', marginBottom: '16px' }}>
        <div
          style={{
            width: '40px',
            height: '40px',
            borderRadius: '4px',
            backgroundColor: config.bg,
            color: config.color,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0
          }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: '24px' }}>
            {config.icon}
          </span>
        </div>

        <div>
          <h4
            className="edu-font-heading"
            style={{
              fontSize: '15px',
              fontWeight: 600,
              color: '#1B2330',
              margin: '0 0 4px 0',
              lineHeight: '1.3'
            }}
          >
            {title}
          </h4>
          <p
            style={{
              fontSize: '11px',
              color: '#5F6774',
              margin: 0,
              fontFamily: 'var(--font-mono)'
            }}
          >
            {date} • {fileSize}
          </p>
        </div>
      </div>

      {/* Footer Action Buttons */}
      <div
        style={{
          display: 'flex',
          gap: '8px',
          paddingTop: '12px',
          borderTop: '1px solid #E5E5E1'
        }}
      >
        {onView && (
          <button
            onClick={onView}
            className="edu-btn-secondary"
            style={{ flex: 1, padding: '8px 12px', fontSize: '11px' }}
          >
            VIEW
          </button>
        )}
        <button
          onClick={onDownload}
          className="edu-btn-primary"
          style={{
            flex: 1,
            padding: '8px 12px',
            fontSize: '11px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '6px'
          }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>
            download
          </span>
          DOWNLOAD
        </button>
      </div>
    </div>
  );
}
