import React from 'react';
import './ui.css';

/**
 * ChatBubbles Component
 *
 * @param {Object} props
 * @param {string} [props.title="Support Interaction"]
 * @param {Array<{id: string, text: string, timestamp: string, senderType: 'student'|'institution', senderName?: string}>} [props.messages]
 */
export default function ChatBubbles({
  title = "Support Interaction",
  messages = [
    {
      id: '1',
      senderType: 'student',
      senderName: 'Marcus Thorne',
      text: "I'm having trouble accessing the curriculum for Advanced Analytics II. Can you verify my permissions?",
      timestamp: "10:42 AM"
    },
    {
      id: '2',
      senderType: 'institution',
      senderName: 'Academic Advisory',
      text: "Request received, Marcus. Our records show your enrollment is pending department head approval. I've sent a follow-up ping to Dr. Vance.",
      timestamp: "10:45 AM"
    }
  ]
}) {
  return (
    <div
      className="edu-card"
      style={{
        padding: '24px',
        display: 'flex',
        flexDirection: 'column',
        gap: '20px'
      }}
    >
      {/* Container Header */}
      {title && (
        <h4
          className="edu-font-heading"
          style={{
            margin: 0,
            fontSize: '16px',
            fontWeight: 600,
            color: '#1B2330',
            borderBottom: '1px solid #E5E5E1',
            paddingBottom: '12px'
          }}
        >
          {title}
        </h4>
      )}

      {/* Messages Thread */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {messages.map((msg) => {
          const isInstitution = msg.senderType === 'institution';

          return (
            <div
              key={msg.id}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: '12px',
                flexDirection: isInstitution ? 'row-reverse' : 'row'
              }}
            >
              {/* Avatar Icon */}
              <div
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '50%',
                  backgroundColor: isInstitution ? '#26415E' : '#E8E8E5',
                  color: isInstitution ? '#FFFFFF' : '#5F6774',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0
                }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>
                  {isInstitution ? 'school' : 'person'}
                </span>
              </div>

              {/* Message Bubble Card */}
              <div
                style={{
                  maxWidth: '80%',
                  backgroundColor: isInstitution ? 'rgba(38, 65, 94, 0.08)' : '#F4F4F1',
                  border: `1px solid ${isInstitution ? 'rgba(38, 65, 94, 0.2)' : '#E5E5E1'}`,
                  borderRadius: '8px',
                  borderTopLeftRadius: !isInstitution ? 0 : '8px',
                  borderTopRightRadius: isInstitution ? 0 : '8px',
                  padding: '12px 14px'
                }}
              >
                {msg.senderName && (
                  <p
                    style={{
                      fontSize: '10px',
                      fontWeight: 700,
                      letterSpacing: '0.05em',
                      textTransform: 'uppercase',
                      color: isInstitution ? '#26415E' : '#5F6774',
                      margin: '0 0 4px 0',
                      fontFamily: 'var(--font-body)'
                    }}
                  >
                    {msg.senderName}
                  </p>
                )}
                <p
                  style={{
                    fontSize: '13px',
                    lineHeight: '1.4',
                    color: isInstitution ? '#26415E' : '#1B2330',
                    margin: 0,
                    fontFamily: 'var(--font-body)'
                  }}
                >
                  {msg.text}
                </p>
                <p
                  style={{
                    fontSize: '9px',
                    color: '#5F6774',
                    marginTop: '6px',
                    textAlign: isInstitution ? 'left' : 'right',
                    margin: '6px 0 0 0',
                    fontFamily: 'var(--font-mono)'
                  }}
                >
                  {msg.timestamp}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
