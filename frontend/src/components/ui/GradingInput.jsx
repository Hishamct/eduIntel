import React, { useState, useEffect } from 'react';
import './ui.css';

/**
 * GradingInput Component
 * Reusable scoring and feedback input card for evaluation tasks.
 *
 * @param {Object} props
 * @param {string} [props.studentName="Student"]
 * @param {string} [props.studentInitials="ST"]
 * @param {string} [props.assignmentTitle="Assessment"]
 * @param {string} [props.submissionNote=""]
 * @param {number} [props.maxScore=100]
 * @param {number|string} [props.initialScore=""]
 * @param {string} [props.initialFeedback=""]
 * @param {string} [props.attachmentName=""]
 * @param {function({score: number|string, feedback: string, publishImmediately: boolean, notifyStudent: boolean}): void} [props.onSave]
 * @param {function(): void} [props.onDiscard]
 */
export default function GradingInput({
  studentName = "Student",
  studentInitials = "ST",
  assignmentTitle = "Assessment",
  submissionNote = "Submitted On-Time",
  maxScore = 100,
  initialScore = "",
  initialFeedback = "",
  attachmentName = "",
  onSave,
  onDiscard
}) {
  const [score, setScore] = useState(initialScore);
  const [feedback, setFeedback] = useState(initialFeedback);
  const [publishImmediately, setPublishImmediately] = useState(false);
  const [notifyStudent, setNotifyStudent] = useState(true);

  useEffect(() => {
    setScore(initialScore);
    setFeedback(initialFeedback);
  }, [initialScore, initialFeedback, studentName]);

  const handleSave = () => {
    if (onSave) {
      onSave({
        score,
        feedback,
        publishImmediately,
        notifyStudent
      });
    }
  };

  return (
    <div className="edu-card" style={{ padding: '24px' }}>
      {/* Top Bar: Student info & Attachment */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '20px',
          paddingBottom: '16px',
          borderBottom: '1px solid #E5E5E1',
          flexWrap: 'wrap',
          gap: '12px'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div
            style={{
              width: '44px',
              height: '44px',
              borderRadius: '4px',
              backgroundColor: '#26415E',
              color: '#FFFFFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontFamily: 'var(--font-heading)',
              fontSize: '16px',
              fontWeight: 700
            }}
          >
            {studentInitials}
          </div>
          <div>
            <h4
              className="edu-font-heading"
              style={{ fontSize: '18px', fontWeight: 600, color: '#1B2330', margin: 0 }}
            >
              Grading: {studentName}
            </h4>
            <p style={{ fontSize: '12px', color: '#5F6774', margin: '2px 0 0 0' }}>
              Item: <strong>{assignmentTitle}</strong> • {submissionNote}
            </p>
          </div>
        </div>

        {attachmentName && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span className="material-symbols-outlined" style={{ fontSize: '18px', color: '#5F6774' }}>
              attach_file
            </span>
            <span style={{ fontSize: '13px', color: '#26415E', fontWeight: 600, cursor: 'pointer' }}>
              {attachmentName}
            </span>
          </div>
        )}
      </div>

      {/* Main Grid: Assign Score & Feedback */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 200px), 1fr))',
          gap: '20px',
          marginBottom: '20px'
        }}
      >
        {/* Score Input */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <label
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: '11px',
              fontWeight: 700,
              letterSpacing: '0.05em',
              textTransform: 'uppercase',
              color: '#5F6774'
            }}
          >
            Assign Score
          </label>
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              gap: '8px',
              backgroundColor: '#F4F4F1',
              border: '1px solid #26415E',
              borderRadius: '4px',
              padding: '12px 16px'
            }}
          >
            <input
              type="number"
              value={score}
              onChange={(e) => setScore(e.target.value)}
              placeholder="0"
              style={{
                width: '70px',
                backgroundColor: 'transparent',
                border: 'none',
                outline: 'none',
                fontFamily: 'var(--font-heading)',
                fontSize: '28px',
                fontWeight: 700,
                color: '#26415E',
                textAlign: 'center'
              }}
            />
            <span
              className="edu-font-heading"
              style={{ fontSize: '20px', fontWeight: 600, color: '#5F6774' }}
            >
              / {maxScore}
            </span>
          </div>
        </div>

        {/* Feedback Input */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', gridColumn: 'span 2' }}>
          <label
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: '11px',
              fontWeight: 700,
              letterSpacing: '0.05em',
              textTransform: 'uppercase',
              color: '#5F6774'
            }}
          >
            Feedback & Observations
          </label>
          <textarea
            rows={4}
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="Provide qualitative assessment, rubric observations, or revision notes..."
            style={{
              width: '100%',
              backgroundColor: '#F4F4F1',
              border: '1px solid #E5E5E1',
              borderRadius: '4px',
              padding: '12px',
              fontSize: '14px',
              fontFamily: 'var(--font-body)',
              color: '#1B2330',
              outline: 'none',
              resize: 'vertical'
            }}
            onFocus={(e) => (e.target.style.borderColor = '#26415E')}
            onBlur={(e) => (e.target.style.borderColor = '#E5E5E1')}
          />
        </div>
      </div>

      {/* Footer Controls */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingTop: '16px',
          borderTop: '1px solid #E5E5E1',
          flexWrap: 'wrap',
          gap: '16px'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '12px', color: '#5F6774', fontWeight: 500 }}>
            <input
              type="checkbox"
              checked={publishImmediately}
              onChange={(e) => setPublishImmediately(e.target.checked)}
              style={{ accentColor: '#26415E' }}
            />
            Publish immediately
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '12px', color: '#5F6774', fontWeight: 500 }}>
            <input
              type="checkbox"
              checked={notifyStudent}
              onChange={(e) => setNotifyStudent(e.target.checked)}
              style={{ accentColor: '#26415E' }}
            />
            Notify student via email
          </label>
        </div>

        <div style={{ display: 'flex', gap: '12px' }}>
          {onDiscard && (
            <button onClick={onDiscard} className="edu-btn-secondary" style={{ padding: '8px 16px' }}>
              DISCARD
            </button>
          )}
          <button
            onClick={handleSave}
            className="edu-btn-primary"
            style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 20px' }}
          >
            SAVE GRADES
            <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>
              save
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
