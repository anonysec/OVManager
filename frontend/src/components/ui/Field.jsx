// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { cloneElement, isValidElement, useId } from 'react';
import './Field.css';

/**
 * Field — label + control wrapper with hint/error wiring.
 *
 * The single child (an <input>, <select> or <textarea>) is cloned so the
 * generated id, aria-describedby and aria-invalid always match the rendered
 * label — no caller has to remember the plumbing. A `ui-input` class is merged
 * in so the control inherits the primitive's styling; pass your own className
 * and it is preserved.
 */
const Field = ({
  label,
  id,
  hint,
  error,
  required = false,
  className = '',
  children,
}) => {
  const autoId = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const child = isValidElement(children) ? children : null;
  const fieldId = child?.props?.id || id || `ui-field-${autoId}`;
  const showHint = Boolean(hint) && !error;
  const hintId = showHint ? `${fieldId}-hint` : undefined;
  const errorId = error ? `${fieldId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;

  const control = child
    ? cloneElement(child, {
        id: fieldId,
        required: child.props.required ?? (required || undefined),
        'aria-invalid': error ? true : child.props['aria-invalid'],
        'aria-describedby':
          [child.props['aria-describedby'], describedBy].filter(Boolean).join(' ') || undefined,
        className: ['ui-input', child.props.className].filter(Boolean).join(' '),
      })
    : children;

  return (
    <div className={['ui-field', error ? 'ui-field--invalid' : '', className].filter(Boolean).join(' ')}>
      {label && (
        <label className="ui-field-label" htmlFor={fieldId}>
          {label}
          {required && <span className="ui-field-required" aria-hidden="true">*</span>}
        </label>
      )}
      <div className="ui-field-control">{control}</div>
      {showHint && <p className="ui-field-hint" id={hintId}>{hint}</p>}
      {error && <p className="ui-field-error" id={errorId} role="alert">{error}</p>}
    </div>
  );
};

export default Field;
