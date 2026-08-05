import React, { useState } from 'react';
import './ui.css';

/**
 * TextField Component
 */
export function TextField({
  label,
  placeholder,
  value,
  onChange,
  type = 'text',
  error,
  helperText,
  disabled = false,
  required = false,
  name,
  icon
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', width: '100%' }}>
      {label && (
        <label
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: '11px',
            fontWeight: 700,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
            color: error ? '#B23A2E' : '#5F6774'
          }}
        >
          {label} {required && <span style={{ color: '#B23A2E' }}>*</span>}
        </label>
      )}
      <div style={{ position: 'relative', width: '100%' }}>
        {icon && (
          <span
            className="material-symbols-outlined"
            style={{
              position: 'absolute',
              left: '12px',
              top: '50%',
              transform: 'translateY(-50%)',
              color: '#5F6774',
              fontSize: '18px',
              pointerEvents: 'none'
            }}
          >
            {icon}
          </span>
        )}
        <input
          type={type}
          name={name}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          disabled={disabled}
          style={{
            width: '100%',
            padding: icon ? '8px 12px 8px 38px' : '8px 12px',
            backgroundColor: disabled ? '#F4F4F1' : '#FFFFFF',
            border: `1px solid ${error ? '#B23A2E' : '#E5E5E1'}`,
            borderRadius: '4px',
            fontSize: '14px',
            fontFamily: 'var(--font-body)',
            color: disabled ? '#5F6774' : '#1B2330',
            outline: 'none',
            transition: 'border-color 0.15s ease'
          }}
          onFocus={(e) => {
            if (!disabled && !error) e.target.style.borderColor = '#26415E';
          }}
          onBlur={(e) => {
            if (!disabled && !error) e.target.style.borderColor = '#E5E5E1';
          }}
        />
      </div>
      {(error || helperText) && (
        <p
          style={{
            fontSize: '11px',
            color: error ? '#B23A2E' : '#5F6774',
            margin: '2px 0 0 0',
            fontFamily: 'var(--font-body)'
          }}
        >
          {error || helperText}
        </p>
      )}
    </div>
  );
}

/**
 * SelectInput Component
 */
export function SelectInput({
  label,
  options = [],
  value,
  onChange,
  error,
  disabled = false,
  required = false,
  name,
  placeholder = "Select an option..."
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', width: '100%' }}>
      {label && (
        <label
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: '11px',
            fontWeight: 700,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
            color: error ? '#B23A2E' : '#5F6774'
          }}
        >
          {label} {required && <span style={{ color: '#B23A2E' }}>*</span>}
        </label>
      )}
      <div style={{ position: 'relative', width: '100%' }}>
        <select
          name={name}
          value={value}
          onChange={onChange}
          disabled={disabled}
          style={{
            width: '100%',
            padding: '8px 36px 8px 12px',
            backgroundColor: disabled ? '#F4F4F1' : '#FFFFFF',
            border: `1px solid ${error ? '#B23A2E' : '#E5E5E1'}`,
            borderRadius: '4px',
            fontSize: '14px',
            fontFamily: 'var(--font-body)',
            color: disabled ? '#5F6774' : '#1B2330',
            outline: 'none',
            appearance: 'none',
            WebkitAppearance: 'none',
            cursor: disabled ? 'not-allowed' : 'pointer',
            transition: 'border-color 0.15s ease'
          }}
          onFocus={(e) => {
            if (!disabled && !error) e.target.style.borderColor = '#26415E';
          }}
          onBlur={(e) => {
            if (!disabled && !error) e.target.style.borderColor = '#E5E5E1';
          }}
        >
          {placeholder && <option value="">{placeholder}</option>}
          {options.map((opt, idx) => {
            const optVal = typeof opt === 'object' ? opt.value : opt;
            const optLabel = typeof opt === 'object' ? opt.label : opt;
            return (
              <option key={idx} value={optVal}>
                {optLabel}
              </option>
            );
          })}
        </select>
        <span
          className="material-symbols-outlined"
          style={{
            position: 'absolute',
            right: '10px',
            top: '50%',
            transform: 'translateY(-50%)',
            color: '#5F6774',
            fontSize: '20px',
            pointerEvents: 'none'
          }}
        >
          unfold_more
        </span>
      </div>
      {error && (
        <p style={{ fontSize: '11px', color: '#B23A2E', margin: '2px 0 0 0', fontFamily: 'var(--font-body)' }}>
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * DatePicker Component
 */
export function DatePicker({
  label,
  value,
  onChange,
  error,
  disabled = false,
  required = false,
  name,
  min,
  max
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', width: '100%' }}>
      {label && (
        <label
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: '11px',
            fontWeight: 700,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
            color: error ? '#B23A2E' : '#5F6774'
          }}
        >
          {label} {required && <span style={{ color: '#B23A2E' }}>*</span>}
        </label>
      )}
      <input
        type="date"
        name={name}
        value={value}
        onChange={onChange}
        disabled={disabled}
        min={min}
        max={max}
        style={{
          width: '100%',
          padding: '8px 12px',
          backgroundColor: disabled ? '#F4F4F1' : '#FFFFFF',
          border: `1px solid ${error ? '#B23A2E' : '#E5E5E1'}`,
          borderRadius: '4px',
          fontSize: '14px',
          fontFamily: 'var(--font-body)',
          color: disabled ? '#5F6774' : '#1B2330',
          outline: 'none',
          transition: 'border-color 0.15s ease'
        }}
        onFocus={(e) => {
          if (!disabled && !error) e.target.style.borderColor = '#26415E';
        }}
        onBlur={(e) => {
          if (!disabled && !error) e.target.style.borderColor = '#E5E5E1';
        }}
      />
      {error && (
        <p style={{ fontSize: '11px', color: '#B23A2E', margin: '2px 0 0 0', fontFamily: 'var(--font-body)' }}>
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * FileDropzone Component
 */
export function FileDropzone({
  label = "Academic Transcript Upload",
  acceptText = "Drag and drop .PDF or .XLSX files",
  maxSizeText = "Maximum file size 10MB",
  onFilesSelected,
  accept = ".pdf,.xlsx,.doc,.docx"
}) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setIsDragOver(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      setSelectedFile(file);
      if (onFilesSelected) onFilesSelected(e.dataTransfer.files);
    }
  };

  const handleFileInputChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0];
      setSelectedFile(file);
      if (onFilesSelected) onFilesSelected(e.target.files);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', width: '100%' }}>
      {label && (
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
          {label}
        </label>
      )}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        style={{
          width: '100%',
          height: '120px',
          border: `2px dashed ${isDragOver ? '#26415E' : '#E5E5E1'}`,
          borderRadius: '8px',
          backgroundColor: isDragOver ? 'rgba(38, 65, 94, 0.05)' : '#FFFFFF',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          padding: '16px',
          position: 'relative',
          transition: 'all 0.2s ease'
        }}
      >
        <input
          type="file"
          accept={accept}
          onChange={handleFileInputChange}
          style={{
            position: 'absolute',
            inset: 0,
            opacity: 0,
            width: '100%',
            height: '100%',
            cursor: 'pointer'
          }}
        />
        <span
          className="material-symbols-outlined"
          style={{
            fontSize: '28px',
            color: isDragOver ? '#26415E' : '#5F6774',
            marginBottom: '6px'
          }}
        >
          cloud_upload
        </span>
        {selectedFile ? (
          <div style={{ textAlign: 'center' }}>
            <p style={{ fontSize: '13px', fontWeight: 600, color: '#1B2330', margin: 0 }}>
              {selectedFile.name}
            </p>
            <p style={{ fontSize: '11px', color: '#5F6774', margin: '2px 0 0 0' }}>
              {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
            </p>
          </div>
        ) : (
          <div style={{ textAlign: 'center' }}>
            <p style={{ fontSize: '13px', color: '#5F6774', margin: 0, fontFamily: 'var(--font-body)' }}>
              {acceptText}
            </p>
            <p
              style={{
                fontSize: '10px',
                color: '#92ADCF',
                textTransform: 'uppercase',
                margin: '4px 0 0 0',
                letterSpacing: '0.05em'
              }}
            >
              {maxSizeText}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default {
  TextField,
  SelectInput,
  DatePicker,
  FileDropzone
};
