import React, { useState, useMemo } from 'react';
import './ui.css';

/**
 * DataTable Component
 *
 * @param {Object} props
 * @param {string} [props.title] - Header title for table container
 * @param {Array<{key: string, label: string, sortable?: boolean, render?: function(row): React.ReactNode, type?: 'text'|'number'|'node'}>} props.columns
 * @param {Array<Object>} props.data - Raw table rows data
 * @param {number} [props.pageSize=5] - Rows per page
 * @param {React.ReactNode} [props.actions] - Header action buttons / icons
 * @param {function(row): void} [props.onRowClick] - Optional row click handler
 */
export default function DataTable({
  title = "Performance Registry",
  columns = [],
  data = [],
  pageSize = 5,
  actions,
  onRowClick
}) {
  const [sortKey, setSortKey] = useState(null);
  const [sortDirection, setSortDirection] = useState('asc'); // 'asc' | 'desc'
  const [filters, setFilters] = useState({});
  const [currentPage, setCurrentPage] = useState(1);

  // Column filter change
  const handleFilterChange = (key, value) => {
    setFilters((prev) => ({
      ...prev,
      [key]: value
    }));
    setCurrentPage(1);
  };

  // Sort click
  const handleSort = (column) => {
    if (!column.sortable) return;
    if (sortKey === column.key) {
      if (sortDirection === 'asc') setSortDirection('desc');
      else {
        setSortKey(null);
        setSortDirection('asc');
      }
    } else {
      setSortKey(column.key);
      setSortDirection('asc');
    }
  };

  // Filtered & Sorted Data computation
  const processedData = useMemo(() => {
    let result = [...data];

    // Filter
    Object.keys(filters).forEach((key) => {
      const val = filters[key];
      if (val && val.trim() !== '') {
        result = result.filter((row) => {
          const cellVal = row[key];
          if (cellVal == null) return false;
          return String(cellVal).toLowerCase().includes(val.toLowerCase().trim());
        });
      }
    });

    // Sort
    if (sortKey) {
      result.sort((a, b) => {
        const valA = a[sortKey];
        const valB = b[sortKey];
        if (valA == null) return 1;
        if (valB == null) return -1;
        if (typeof valA === 'number' && typeof valB === 'number') {
          return sortDirection === 'asc' ? valA - valB : valB - valA;
        }
        return sortDirection === 'asc'
          ? String(valA).localeCompare(String(valB))
          : String(valB).localeCompare(String(valA));
      });
    }

    return result;
  }, [data, filters, sortKey, sortDirection]);

  // Pagination bounds
  const totalEntries = processedData.length;
  const totalPages = Math.max(1, Math.ceil(totalEntries / pageSize));
  const page = Math.min(currentPage, totalPages);
  const startIndex = (page - 1) * pageSize;
  const paginatedData = processedData.slice(startIndex, startIndex + pageSize);

  return (
    <div className="edu-card" style={{ overflow: 'hidden' }}>
      {/* Table Title Bar */}
      {title && (
        <div
          style={{
            padding: '16px 20px',
            backgroundColor: 'rgba(255, 255, 255, 0.5)',
            borderBottom: '1px solid rgba(226, 232, 240, 0.8)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '12px'
          }}
        >
          <h4
            className="edu-font-heading"
            style={{ margin: 0, fontSize: '17px', fontWeight: 700, color: '#0F172A', letterSpacing: '-0.01em' }}
          >
            {title}
          </h4>
          {actions && <div style={{ display: 'flex', gap: '8px' }}>{actions}</div>}
        </div>
      )}

      {/* Table Content */}
      <div style={{ overflowX: 'auto' }}>
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            textAlign: 'left',
            fontFamily: 'var(--font-body)',
            fontSize: '13px'
          }}
        >
          {/* Header Row */}
          <thead>
            <tr style={{ backgroundColor: 'rgba(248, 250, 252, 0.7)', borderBottom: '1px solid rgba(226, 232, 240, 0.8)' }}>
              {columns.map((col) => (
                <th
                  key={col.key}
                  onClick={() => handleSort(col)}
                  style={{
                    padding: '12px 18px',
                    fontFamily: 'var(--font-body)',
                    fontSize: '11px',
                    fontWeight: 700,
                    letterSpacing: '0.05em',
                    color: '#64748B',
                    borderRight: '1px solid rgba(226, 232, 240, 0.6)',
                    cursor: col.sortable ? 'pointer' : 'default',
                    userSelect: 'none',
                    transition: 'background-color 0.15s ease'
                  }}
                  onMouseEnter={(e) => {
                    if (col.sortable) e.currentTarget.style.backgroundColor = 'rgba(241, 245, 249, 0.9)';
                  }}
                  onMouseLeave={(e) => {
                    if (col.sortable) e.currentTarget.style.backgroundColor = 'rgba(248, 250, 252, 0.7)';
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px' }}>
                    <span>{col.label.toUpperCase()}</span>
                    {col.sortable && (
                      <span className="material-symbols-outlined" style={{ fontSize: '15px', color: '#94A3B8' }}>
                        {sortKey === col.key
                          ? sortDirection === 'asc'
                            ? 'arrow_upward'
                            : 'arrow_downward'
                          : 'unfold_more'}
                      </span>
                    )}
                  </div>
                </th>
              ))}
            </tr>

            {/* Filter Inputs Row */}
            <tr style={{ backgroundColor: 'rgba(255, 255, 255, 0.6)', borderBottom: '1px solid rgba(226, 232, 240, 0.8)' }}>
              {columns.map((col) => (
                <th key={`filter-${col.key}`} style={{ padding: '8px 14px', borderRight: '1px solid rgba(226, 232, 240, 0.6)' }}>
                  <input
                    type="text"
                    placeholder={`Filter ${col.label}...`}
                    value={filters[col.key] || ''}
                    onChange={(e) => handleFilterChange(col.key, e.target.value)}
                    style={{
                      width: '100%',
                      padding: '6px 10px',
                      fontSize: '12px',
                      fontFamily: 'var(--font-body)',
                      backgroundColor: 'rgba(255, 255, 255, 0.9)',
                      border: '1px solid #E2E8F0',
                      borderRadius: '8px',
                      outline: 'none',
                      color: '#1E293B',
                      transition: 'border-color 0.15s ease'
                    }}
                    onFocus={(e) => (e.target.style.borderColor = '#10B981')}
                    onBlur={(e) => (e.target.style.borderColor = '#E2E8F0')}
                  />
                </th>
              ))}
            </tr>
          </thead>

          {/* Table Body */}
          <tbody>
            {paginatedData.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  style={{
                    padding: '36px',
                    textAlign: 'center',
                    color: '#64748B',
                    fontFamily: 'var(--font-body)',
                    fontSize: '13.5px'
                  }}
                >
                  No matching records found
                </td>
              </tr>
            ) : (
              paginatedData.map((row, idx) => (
                <tr
                  key={row.id || idx}
                  onClick={() => onRowClick && onRowClick(row)}
                  style={{
                    borderBottom: '1px solid rgba(226, 232, 240, 0.6)',
                    cursor: onRowClick ? 'pointer' : 'default',
                    transition: 'background-color 0.15s ease'
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(16, 185, 129, 0.04)')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                >
                  {columns.map((col) => (
                    <td
                      key={`${row.id || idx}-${col.key}`}
                      style={{
                        padding: '14px 18px',
                        borderRight: '1px solid rgba(226, 232, 240, 0.6)',
                        color: '#1E293B'
                      }}
                    >
                      {col.render ? col.render(row) : row[col.key]}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      <div
        style={{
          padding: '12px 20px',
          backgroundColor: 'rgba(255, 255, 255, 0.5)',
          borderTop: '1px solid rgba(226, 232, 240, 0.8)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '12px'
        }}
      >
        <p
          style={{
            fontSize: '11px',
            fontFamily: 'var(--font-body)',
            fontWeight: 700,
            letterSpacing: '0.05em',
            color: '#64748B',
            margin: 0,
            textTransform: 'uppercase'
          }}
        >
          SHOWING {totalEntries > 0 ? startIndex + 1 : 0} TO {Math.min(startIndex + pageSize, totalEntries)} OF {totalEntries} ENTRIES
        </p>

        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          <button
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            style={{
              width: '32px',
              height: '32px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: '#FFFFFF',
              border: '1px solid #E2E8F0',
              borderRadius: '8px',
              cursor: page === 1 ? 'not-allowed' : 'pointer',
              opacity: page === 1 ? 0.5 : 1
            }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: '18px', color: '#64748B' }}>
              chevron_left
            </span>
          </button>

          {Array.from({ length: totalPages }, (_, i) => i + 1).map((pNum) => (
            <button
              key={pNum}
              onClick={() => setCurrentPage(pNum)}
              style={{
                width: '32px',
                height: '32px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                backgroundColor: pNum === page ? '#10B981' : '#FFFFFF',
                color: pNum === page ? '#FFFFFF' : '#1E293B',
                border: pNum === page ? '1px solid #10B981' : '1px solid #E2E8F0',
                borderRadius: '8px',
                fontWeight: pNum === page ? 700 : 500,
                fontSize: '12px',
                cursor: 'pointer',
                transition: 'all 0.15s ease'
              }}
            >
              {pNum}
            </button>
          ))}

          <button
            onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            style={{
              width: '32px',
              height: '32px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: '#FFFFFF',
              border: '1px solid #E2E8F0',
              borderRadius: '8px',
              cursor: page === totalPages ? 'not-allowed' : 'pointer',
              opacity: page === totalPages ? 0.5 : 1
            }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: '18px', color: '#64748B' }}>
              chevron_right
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
