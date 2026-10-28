import React from 'react';
import './ui.css';

/**
 * Sidebar Navigation Component - Option 1 Light Glassmorphic Theme
 */
export const PORTAL_NAV_ITEMS = {
  admin: [
    { id: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
    { id: 'ai-assistant', label: 'AI Assistant', icon: 'smart_toy' },
    { id: 'llm-usage', label: 'LLM Usage', icon: 'receipt_long' },       
    { id: 'agent-traces', label: 'Agent Traces', icon: 'route' },       
    { id: 'students', label: 'Student Records', icon: 'group' },
    { id: 'analysis', label: 'Academic Analysis', icon: 'analytics' },
    { id: 'alerts', label: 'Risk Alerts', icon: 'warning' },
    { id: 'reports', label: 'Institutional Reports', icon: 'description' },
    { id: 'timetable', label: 'Timetable', icon: 'calendar_month' },
    { id: 'salary', label: 'Salary Management', icon: 'payments' },
  ],
  teacher: [
    { id: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
    { id: 'progress', label: 'Progress Monitoring', icon: 'monitoring' },
    { id: 'grading', label: 'Assignments & Grading', icon: 'assignment' },
    { id: 'materials', label: 'Study Materials', icon: 'menu_book' },
    { id: 'exams', label: 'Exam Results', icon: 'grade' },
    { id: 'flagged', label: 'Flagged Students', icon: 'flag' },
  ],
  student: [
    { id: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
    { id: 'homework', label: 'Homework', icon: 'assignment' },
    { id: 'doubts', label: 'Doubt Forum', icon: 'forum' },
    { id: 'materials', label: 'Study Materials', icon: 'menu_book' },
    { id: 'self-eval', label: 'Self-Evaluation', icon: 'quiz' },
  ]
};

export default function Sidebar({
  logoText = "eduIntel",
  roleText = "Administrator Portal",
  items,
  activeId = 'dashboard',
  onSelect,
  isCollapsed = false,
  onToggleCollapse,
  userRole = 'admin',
  accentAction = { label: 'Upgrade Pro', icon: 'auto_awesome', onClick: () => {} }
}) {
  const menuItems = items !== undefined ? items : (PORTAL_NAV_ITEMS[userRole] || PORTAL_NAV_ITEMS.admin);
  const visibleItems = menuItems.filter(
    (item) => !item.roles || item.roles.includes(userRole)
  );

  const sidebarWidth = isCollapsed ? '72px' : '260px';

  return (
    <aside
      className="edu-sidebar"
      style={{
        width: sidebarWidth
      }}
    >
      {/* Header / Brand & Toggle */}
      <div
        style={{
          padding: isCollapsed ? '0 12px 20px' : '0 20px 20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: isCollapsed ? 'center' : 'space-between',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
          marginBottom: '20px'
        }}
      >
        {!isCollapsed && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '34px',
                height: '34px',
                borderRadius: '10px',
                background: 'linear-gradient(135deg, #10B981 0%, #059669 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: '0 4px 12px rgba(16, 185, 129, 0.3)'
              }}
            >
              <span className="material-symbols-outlined" style={{ color: '#FFFFFF', fontSize: '20px' }}>
                school
              </span>
            </div>
            <div>
              <h1
                className="edu-font-heading"
                style={{
                  fontSize: '18px',
                  fontWeight: 700,
                  margin: 0,
                  color: '#FFFFFF',
                  letterSpacing: '-0.02em',
                  whiteSpace: 'nowrap'
                }}
              >
                {logoText}
              </h1>
              <p
                className="edu-font-body"
                style={{
                  fontSize: '10px',
                  fontWeight: 500,
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                  color: '#94A3B8',
                  margin: '1px 0 0 0',
                  whiteSpace: 'nowrap'
                }}
              >
                {roleText}
              </p>
            </div>
          </div>
        )}

        <button
          onClick={onToggleCollapse}
          title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          style={{
            background: 'rgba(255, 255, 255, 0.05)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            color: '#94A3B8',
            cursor: 'pointer',
            padding: '6px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: '8px',
            transition: 'all 0.15s ease'
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = '#FFFFFF';
            e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.12)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = '#94A3B8';
            e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.05)';
          }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>
            {isCollapsed ? 'chevron_right' : 'menu_open'}
          </span>
        </button>
      </div>

      {/* Navigation Links */}
      <nav style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '6px', padding: '0 12px' }}>
        {visibleItems.map((item) => {
          const isActive = item.id === activeId;

          return (
            <button
              key={item.id}
              onClick={() => onSelect && onSelect(item.id)}
              title={isCollapsed ? item.label : undefined}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                width: '100%',
                padding: isCollapsed ? '12px 0' : '10px 16px',
                justifyContent: isCollapsed ? 'center' : 'flex-start',
                backgroundColor: isActive ? 'rgba(16, 185, 129, 0.16)' : 'transparent',
                border: isActive ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid transparent',
                borderRadius: '12px',
                color: isActive ? '#A7F3D0' : '#94A3B8',
                textAlign: 'left',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                boxShadow: isActive ? '0 4px 14px rgba(16, 185, 129, 0.15)' : 'none'
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.06)';
                  e.currentTarget.style.color = '#F1F5F9';
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = 'transparent';
                  e.currentTarget.style.color = '#94A3B8';
                }
              }}
            >
              <span
                className="material-symbols-outlined"
                style={{
                  fontSize: '20px',
                  color: isActive ? '#10B981' : 'inherit'
                }}
              >
                {item.icon}
              </span>
              {!isCollapsed && (
                <span
                  className="edu-font-body"
                  style={{
                    fontSize: '13.5px',
                    fontWeight: isActive ? 600 : 400,
                    whiteSpace: 'nowrap',
                    color: isActive ? '#FFFFFF' : 'inherit'
                  }}
                >
                  {item.label}
                </span>
              )}
              {isActive && !isCollapsed && (
                <span
                  style={{
                    marginLeft: 'auto',
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    backgroundColor: '#10B981',
                    boxShadow: '0 0 8px #10B981'
                  }}
                />
              )}
            </button>
          );
        })}
      </nav>
    </aside>
  );
}

