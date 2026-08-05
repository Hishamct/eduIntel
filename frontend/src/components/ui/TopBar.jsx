import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { logout } from '../../api/auth';
import './ui.css';

/**
 * TopBar Component
 *
 * @param {Object} props
 * @param {string} [props.searchPlaceholder="Search students, faculty, or datasets..."]
 * @param {string} [props.searchValue=""]
 * @param {function(string): void} [props.onSearchChange]
 * @param {function(string): void} [props.onSearchSubmit]
 * @param {number} [props.notificationsCount=1]
 * @param {function(): void} [props.onNotificationClick]
 * @param {{name: string, role: string, avatarUrl?: string}} [props.user]
 * @param {Array<{id: string, label: string, icon?: string}>} [props.profileMenuItems]
 * @param {function(string): void} [props.onProfileMenuSelect]
 */
export default function TopBar({
  searchPlaceholder = "Search students, faculty, or datasets...",
  searchValue = "",
  onSearchChange,
  onSearchSubmit,
  notificationsCount = 1,
  onNotificationClick,
  user = {
    name: "Dr. Aria Vance",
    role: "Super Admin",
    avatarUrl: ""
  },
  profileMenuItems = [
    { id: 'profile', label: 'View Profile', icon: 'person' },
    { id: 'settings', label: 'Account Settings', icon: 'settings' },
    { id: 'logout', label: 'Sign Out', icon: 'logout' }
  ],
  onProfileMenuSelect
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

  // User initials fallback
  const getInitials = (name) => {
    if (!name) return "U";
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
            left: '12px',
            top: '50%',
            transform: 'translateY(-50%)',
            color: '#5F6774',
            fontSize: '20px',
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
            padding: '8px 12px 8px 40px',
            backgroundColor: '#F4F4F1',
            border: '1px solid #E5E5E1',
            borderRadius: '4px',
            fontSize: '14px',
            color: '#1B2330',
            outline: 'none',
            fontFamily: 'var(--font-body)',
            transition: 'border-color 0.2s ease, background-color 0.2s ease'
          }}
          onFocus={(e) => {
            e.target.style.borderColor = '#26415E';
            e.target.style.backgroundColor = '#FFFFFF';
          }}
          onBlur={(e) => {
            e.target.style.borderColor = '#E5E5E1';
            e.target.style.backgroundColor = '#F4F4F1';
          }}
        />
      </div>

      {/* Right Controls: Notifications & Profile Menu */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
        {/* Notification Bell */}
        <button
          onClick={onNotificationClick}
          title="Notifications"
          style={{
            position: 'relative',
            background: 'transparent',
            border: 'none',
            color: '#5F6774',
            cursor: 'pointer',
            padding: '8px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: '50%',
            transition: 'color 0.15s ease, background-color 0.15s ease'
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = '#26415E';
            e.currentTarget.style.backgroundColor = '#F1F1ED';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = '#5F6774';
            e.currentTarget.style.backgroundColor = 'transparent';
          }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: '22px' }}>
            notifications
          </span>
          {notificationsCount > 0 && (
            <span
              style={{
                position: 'absolute',
                top: '6px',
                right: '6px',
                width: '8px',
                height: '8px',
                backgroundColor: '#B23A2E',
                borderRadius: '50%',
                border: '2px solid #FAFAF7'
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
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              padding: '4px 8px',
              borderRadius: '4px',
              transition: 'background-color 0.15s ease'
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#F1F1ED')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            {user.avatarUrl ? (
              <img
                src={user.avatarUrl}
                alt={user.name}
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '50%',
                  objectFit: 'cover',
                  border: '1px solid #E5E5E1'
                }}
              />
            ) : (
              <div
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '50%',
                  backgroundColor: '#26415E',
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
                  fontSize: '12px',
                  fontWeight: 700,
                  color: '#1B2330',
                  margin: 0,
                  lineHeight: '1.2'
                }}
              >
                {user.name.toUpperCase()}
              </p>
              <p
                style={{
                  fontSize: '10px',
                  color: '#5F6774',
                  margin: '2px 0 0 0',
                  textTransform: 'uppercase'
                }}
              >
                {user.role}
              </p>
            </div>
            <span
              className="material-symbols-outlined"
              style={{
                fontSize: '18px',
                color: '#5F6774',
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
                top: 'calc(100% + 4px)',
                width: '200px',
                backgroundColor: '#FFFFFF',
                border: '1px solid #E5E5E1',
                borderRadius: '4px',
                boxShadow: '0 4px 12px rgba(38, 65, 94, 0.08)',
                padding: '4px 0',
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
                    padding: '10px 16px',
                    background: 'transparent',
                    border: 'none',
                    textAlign: 'left',
                    fontSize: '13px',
                    color: item.id === 'logout' ? '#B23A2E' : '#1B2330',
                    cursor: 'pointer',
                    transition: 'background-color 0.15s ease'
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#F1F1ED')}
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
