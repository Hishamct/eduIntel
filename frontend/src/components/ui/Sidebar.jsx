import React from 'react';
import './ui.css';

/**
 * Sidebar Navigation Component
 *
 * @param {Object} props
 * @param {string} [props.logoText="EduIntel AI"] - Logo/brand header text
 * @param {string} [props.roleText="Administrator"] - User role badge text
 * @param {Array<{id: string, label: string, icon: string, roles?: string[]}>} [props.items] - Menu items
 * @param {string} [props.activeId] - Currently active menu item ID
 * @param {function(string): void} [props.onSelect] - Callback when an item is selected
 * @param {boolean} [props.isCollapsed=false] - Whether sidebar is in collapsed icon-only mode
 * @param {function(): void} [props.onToggleCollapse] - Toggle collapse handler
 * @param {string} [props.userRole="admin"] - Current active user role for filtering items
 * @param {Object} [props.accentAction] - Optional standout accent action button { label: string, icon?: string, onClick: function }
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
  logoText = "EduIntel AI",
  roleText = "Administrator Portal",
  items,
  activeId = 'dashboard',
  onSelect,
  isCollapsed = false,
  onToggleCollapse,
  userRole = 'admin',
  accentAction = { label: 'NEW ANALYSIS', icon: 'add', onClick: () => {} }
}) {
  const menuItems = items !== undefined ? items : (PORTAL_NAV_ITEMS[userRole] || PORTAL_NAV_ITEMS.admin);
  const visibleItems = menuItems.filter(
    (item) => !item.roles || item.roles.includes(userRole)
  );

  const sidebarWidth = isCollapsed ? '64px' : '260px';

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
          padding: isCollapsed ? '0 12px 24px' : '0 24px 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: isCollapsed ? 'center' : 'space-between',
          borderBottom: '1px solid rgba(255, 255, 255, 0.1)',
          marginBottom: '16px'
        }}
      >
        {!isCollapsed && (
          <div>
            <h1
              className="edu-font-heading"
              style={{
                fontSize: '20px',
                fontWeight: 700,
                margin: 0,
                color: '#FFFFFF',
                whiteSpace: 'nowrap'
              }}
            >
              {logoText}
            </h1>
            <p
              className="edu-font-body"
              style={{
                fontSize: '10px',
                letterSpacing: '0.05em',
                textTransform: 'uppercase',
                color: '#92ADCF',
                margin: '2px 0 0 0',
                whiteSpace: 'nowrap'
              }}
            >
              {roleText}
            </p>
          </div>
        )}
        <button
          onClick={onToggleCollapse}
          title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          style={{
            background: 'transparent',
            border: 'none',
            color: '#92ADCF',
            cursor: 'pointer',
            padding: '4px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: '4px'
          }}
        >
          <span className="material-symbols-outlined">
            {isCollapsed ? 'chevron_right' : 'menu_open'}
          </span>
        </button>
      </div>

      {/* Navigation Links */}
      <nav style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
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
                padding: isCollapsed ? '12px 0' : '12px 24px',
                justifyContent: isCollapsed ? 'center' : 'flex-start',
                backgroundColor: isActive ? 'rgba(255, 255, 255, 0.15)' : 'transparent',
                borderLeft: isActive ? '4px solid #C97A2B' : '4px solid transparent',
                color: isActive ? '#FFFFFF' : '#92ADCF',
                borderTop: 'none',
                borderRight: 'none',
                borderBottom: 'none',
                textAlign: 'left',
                cursor: 'pointer',
                transition: 'all 0.15s ease'
              }}
              onMouseEnter={(e) => {
                if (!isActive) e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.08)';
              }}
              onMouseLeave={(e) => {
                if (!isActive) e.currentTarget.style.backgroundColor = 'transparent';
              }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>
                {item.icon}
              </span>
              {!isCollapsed && (
                <span
                  className="edu-font-body"
                  style={{ fontSize: '14px', fontWeight: isActive ? 600 : 400, whiteSpace: 'nowrap' }}
                >
                  {item.label}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Accent Standout CTA */}
      {accentAction && (
        <div style={{ padding: isCollapsed ? '12px' : '16px 24px 8px' }}>
          <button
            onClick={accentAction.onClick}
            className="edu-btn-accent"
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: isCollapsed ? '0' : '8px',
              padding: isCollapsed ? '10px 0' : '12px 16px'
            }}
            title={isCollapsed ? accentAction.label : undefined}
          >
            {accentAction.icon && (
              <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>
                {accentAction.icon}
              </span>
            )}
            {!isCollapsed && accentAction.label}
          </button>
        </div>
      )}
    </aside>
  );
}
