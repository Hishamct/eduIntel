import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { logout } from '../../api/auth';
import './ui.css';

/**
 * TopBar Component - Glassmorphic Header
 */
export default function TopBar({
  searchPlaceholder = "Search students, faculty, or analytical reports...",
  searchValue = "",
  onSearchChange,
  onSearchSubmit,
  notificationsCount = 2,
  onNotificationClick,
  user = {
    name: "Dr. Sarah Evans",
    role: "Super Admin",
    avatarUrl: ""
  },
  profileMenuItems = [
    { id: 'profile', label: 'View Profile', icon: 'person' },
    { id: 'settings', label: 'Account Settings', icon: 'settings' },
    { id: 'logout', label: 'Sign Out', icon: 'logout' }
  ],
  onProfileMenuSelect,
  showAiMode = true
}) {
  const navigate = useNavigate();
  const [internalSearch, setInternalSearch] = useState(searchValue);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const dropdownRef = useRef(null);

  const handleMenuItemClick = (itemId) => {
    setIsDropdownOpen(false);
    if (itemId === 'logout') {
      logout(navigate);
    }
    if (onProfileMenuSelect) {
      onProfileMenuSelect(itemId);
    }
  };

  useEffect(() => {
    setInternalSearch(searchValue);
  }, [searchValue]);

  useEffect(() => {
    function handleClickOutside(event) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSearchInputChange = (e) => {
    const val = e.target.value;
    setInternalSearch(val);
    if (onSearchChange) onSearchChange(val);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && onSearchSubmit) {
      onSearchSubmit(internalSearch);
    }
  };

  const getInitials = (name) => {
    if (!name) return "SE";
    return name
      .split(' ')
      .map((n) => n[0])
      .join('')
      .substring(0, 2)
      .toUpperCase();
  };

  return (
    <header className="edu-topbar">
      {/* Search Input Box */}
      <div className="edu-topbar-search">
        <span
          className="material-symbols-outlined"
          style={{
            position: 'absolute',
            left: '16px',
            top: '50%',
            transform: 'translateY(-50%)',
            color: '#94A3B8',
            fontSize: '19px',
            pointerEvents: 'none'
          }}
        >
          search
        </span>
        <input
          type="text"
          value={internalSearch}
          onChange={handleSearchInputChange}
          onKeyDown={handleKeyDown}
          placeholder={searchPlaceholder}
          style={{
            width: '100%',
            padding: '9px 16px 9px 44px',
            backgroundColor: 'rgba(255, 255, 255, 0.7)',
            border: '1px solid rgba(226, 232, 240, 0.9)',
            borderRadius: '9999px',
            fontSize: '13.5px',
            color: '#1E293B',
            outline: 'none',
            fontFamily: 'var(--font-body)',
            boxShadow: '0 2px 6px rgba(0, 0, 0, 0.02)',
            transition: 'all 0.2s ease'
          }}
          onFocus={(e) => {
            e.target.style.borderColor = '#10B981';
            e.target.style.backgroundColor = '#FFFFFF';
            e.target.style.boxShadow = '0 0 0 3px rgba(16, 185, 129, 0.15)';
          }}
          onBlur={(e) => {
            e.target.style.borderColor = 'rgba(226, 232, 240, 0.9)';
            e.target.style.backgroundColor = 'rgba(255, 255, 255, 0.7)';
            e.target.style.boxShadow = '0 2px 6px rgba(0, 0, 0, 0.02)';
          }}
        />
      </div>

      {/* Right Controls: Notifications & Profile Menu */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        {/* Notification Bell */}
        <button
          onClick={onNotificationClick}
          title="Notifications"
          style={{
            position: 'relative',
            background: 'rgba(255, 255, 255, 0.8)',
            border: '1px solid rgba(226, 232, 240, 0.8)',
            color: '#64748B',
            cursor: 'pointer',
            width: '38px',
            height: '38px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: '50%',
            transition: 'all 0.15s ease',
            boxShadow: '0 2px 6px rgba(0,0,0,0.03)'
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = '#0F172A';
            e.currentTarget.style.backgroundColor = '#FFFFFF';
            e.currentTarget.style.borderColor = '#CBD5E1';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = '#64748B';
            e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.8)';
            e.currentTarget.style.borderColor = 'rgba(226, 232, 240, 0.8)';
          }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>
            notifications
          </span>
          {notificationsCount > 0 && (
            <span
              style={{
                position: 'absolute',
                top: '7px',
                right: '7px',
                width: '8px',
                height: '8px',
                backgroundColor: '#EF4444',
                borderRadius: '50%',
                border: '2px solid #FFFFFF'
              }}
            />
          )}
        </button>

        {/* Profile Dropdown Trigger */}
        <div style={{ position: 'relative' }} ref={dropdownRef}>
          <button
            onClick={() => setIsDropdownOpen(!isDropdownOpen)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              background: 'rgba(255, 255, 255, 0.8)',
              border: '1px solid rgba(226, 232, 240, 0.8)',
              cursor: 'pointer',
              padding: '5px 12px 5px 6px',
              borderRadius: '9999px',
              boxShadow: '0 2px 6px rgba(0,0,0,0.03)',
              transition: 'all 0.15s ease'
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#FFFFFF')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.8)')}
          >
            {user.avatarUrl ? (
              <img
                src={user.avatarUrl}
                alt={user.name}
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '50%',
                  objectFit: 'cover'
                }}
              />
            ) : (
              <div
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '50%',
                  background: 'linear-gradient(135deg, #0F172A 0%, #334155 100%)',
                  color: '#FFFFFF',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: 600,
                  fontSize: '12px',
                  fontFamily: 'var(--font-heading)'
                }}
              >
                {getInitials(user.name)}
              </div>
            )}
            <div style={{ textAlign: 'left' }}>
              <p
                className="edu-font-body"
                style={{
                  fontSize: '12.5px',
                  fontWeight: 600,
                  color: '#0F172A',
                  margin: 0,
                  lineHeight: '1.2'
                }}
              >
                {user.name}
              </p>
              <p
                style={{
                  fontSize: '10px',
                  color: '#64748B',
                  margin: '1px 0 0 0',
                  textTransform: 'uppercase',
                  fontWeight: 500
                }}
              >
                {user.role}
              </p>
            </div>
            <span
              className="material-symbols-outlined"
              style={{
                fontSize: '18px',
                color: '#64748B',
                transform: isDropdownOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                transition: 'transform 0.2s ease'
              }}
            >
              expand_more
            </span>
          </button>

          {/* Profile Menu Popup */}
          {isDropdownOpen && (
            <div
              style={{
                position: 'absolute',
                right: 0,
                top: 'calc(100% + 8px)',
                width: '210px',
                backgroundColor: 'rgba(255, 255, 255, 0.95)',
                backdropFilter: 'blur(16px)',
                border: '1px solid rgba(226, 232, 240, 0.9)',
                borderRadius: '14px',
                boxShadow: '0 12px 30px -5px rgba(0, 0, 0, 0.1)',
                padding: '6px',
                zIndex: 100
              }}
            >
              {profileMenuItems.map((item) => (
                <button
                  key={item.id}
                  onClick={() => handleMenuItemClick(item.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    width: '100%',
                    padding: '9px 14px',
                    background: 'transparent',
                    border: 'none',
                    borderRadius: '8px',
                    textAlign: 'left',
                    fontSize: '13px',
                    fontWeight: 500,
                    color: item.id === 'logout' ? '#EF4444' : '#1E293B',
                    cursor: 'pointer',
                    transition: 'background-color 0.15s ease'
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = item.id === 'logout' ? '#FEE2E2' : '#F1F5F9')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                >
                  {item.icon && (
                    <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>
                      {item.icon}
                    </span>
                  )}
                  {item.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

