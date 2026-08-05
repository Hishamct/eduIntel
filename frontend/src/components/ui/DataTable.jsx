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
            padding: '12px 16px',
            backgroundColor: '#F4F4F1',
            borderBottom: '1px solid #E5E5E1',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between'
          }}
        >
          <h4
            className="edu-font-heading"
            style={{ margin: 0, fontSize: '16px', fontWeight: 600, color: '#1B2330' }}
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
            fontFamily: 'var(--font-mono)',
            fontSize: '13px'
          }}
        >
          {/* Header Row */}
          <thead>
            <tr style={{ backgroundColor: '#FAFAF7', borderBottom: '1px solid #E5E5E1' }}>
              {columns.map((col) => (
                <th
                  key={col.key}
                  onClick={() => handleSort(col)}
                  style={{
                    padding: '10px 16px',
                    fontFamily: 'var(--font-body)',
                    fontSize: '11px',
                    fontWeight: 700,
                    letterSpacing: '0.05em',
                    color: '#1B2330',
                    borderRight: '1px solid #E5E5E1',
                    cursor: col.sortable ? 'pointer' : 'default',
                    userSelect: 'none',
                    transition: 'background-color 0.15s ease'
                  }}
                  onMouseEnter={(e) => {
                    if (col.sortable) e.currentTarget.style.backgroundColor = '#E8E8E5';
                  }}
                  onMouseLeave={(e) => {
                    if (col.sortable) e.currentTarget.style.backgroundColor = '#FAFAF7';
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px' }}>
                    <span>{col.label.toUpperCase()}</span>
                    {col.sortable && (
                      <span className="material-symbols-outlined" style={{ fontSize: '14px', color: '#5F6774' }}>
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
            <tr style={{ backgroundColor: '#FFFFFF', borderBottom: '1px solid #E5E5E1' }}>
              {columns.map((col) => (
                <th key={`filter-${col.key}`} style={{ padding: '6px 12px', borderRight: '1px solid #E5E5E1' }}>
                  <input
                    type="text"
                    placeholder={`Filter ${col.label}...`}
                    value={filters[col.key] || ''}
                    onChange={(e) => handleFilterChange(col.key, e.target.value)}
                    style={{
                      width: '100%',
                      padding: '4px 8px',
                      fontSize: '12px',
                      fontFamily: 'var(--font-body)',
                      backgroundColor: 'transparent',
                      border: '1px solid #E5E5E1',
                      borderRadius: '2px',
                      outline: 'none',
                      color: '#1B2330'
                    }}
                    onFocus={(e) => (e.target.style.borderColor = '#26415E')}
                    onBlur={(e) => (e.target.style.borderColor = '#E5E5E1')}
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
                    padding: '24px',
                    textAlign: 'center',
                    color: '#5F6774',
                    fontFamily: 'var(--font-body)',
                    fontSize: '13px'
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
                    borderBottom: '1px solid #E5E5E1',
                    cursor: onRowClick ? 'pointer' : 'default',
                    transition: 'background-color 0.15s ease'
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#F1F1ED')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                >
                  {columns.map((col) => (
                    <td
                      key={`${row.id || idx}-${col.key}`}
                      style={{
                        padding: '12px 16px',
                        borderRight: '1px solid #E5E5E1',
                        color: '#1B2330'
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
          padding: '10px 16px',
          backgroundColor: '#F4F4F1',
          borderTop: '1px solid #E5E5E1',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}
      >
        <p
          style={{
            fontSize: '11px',
            fontFamily: 'var(--font-body)',
            fontWeight: 700,
            letterSpacing: '0.05em',
            color: '#5F6774',
            margin: 0,
            textTransform: 'uppercase'
          }}
        >
          SHOWING {totalEntries > 0 ? startIndex + 1 : 0} TO {Math.min(startIndex + pageSize, totalEntries)} OF {totalEntries} ENTRIES
        </p>

        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
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
              border: '1px solid #E5E5E1',
              borderRadius: '2px',
              cursor: page === 1 ? 'not-allowed' : 'pointer',
              opacity: page === 1 ? 0.5 : 1
            }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: '18px', color: '#5F6774' }}>
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
                backgroundColor: pNum === page ? '#26415E' : '#FFFFFF',
                color: pNum === page ? '#FFFFFF' : '#1B2330',
                border: '1px solid #E5E5E1',
                borderRadius: '2px',
                fontWeight: pNum === page ? 600 : 400,
                fontSize: '12px',
                cursor: 'pointer',
                fontFamily: 'var(--font-mono)'
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
              border: '1px solid #E5E5E1',
              borderRadius: '2px',
              cursor: page === totalPages ? 'not-allowed' : 'pointer',
              opacity: page === totalPages ? 0.5 : 1
            }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: '18px', color: '#5F6774' }}>
              chevron_right
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
