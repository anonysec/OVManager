// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { cloneElement, isValidElement, useId } from 'react';
import type { ReactElement, ReactNode } from 'react';
import './Field.css';

type FieldProps = {
  label?: any;
  inputId?: any;
  hint?: any;
  error?: any;
  required?: boolean;
  className?: string;
  children?: ReactNode;
};


const Field = ({
  label,
  inputId,
  hint,
  error,
  required = false,
  className = '',
  children,
}: FieldProps) => {
  const autoId = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const child = isValidElement(children) ? (children as ReactElement<any>) : null;
  const childProps: any = (child?.props as any) || {};
  const fieldId = childProps.id || inputId || `ui-field-${autoId}`;
  const showHint = Boolean(hint) && !error;
  const hintId = showHint ? `${fieldId}-hint` : undefined;
  const errorId = error ? `${fieldId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;

  const control = child
    ? cloneElement(child, {
        id: fieldId,
        required: childProps.required ?? (required || undefined),
        'aria-invalid': error ? true : childProps['aria-invalid'],
        'aria-describedby':
          [childProps['aria-describedby'], describedBy].filter(Boolean).join(' ') || undefined,
        className: ['ui-input', childProps.className].filter(Boolean).join(' '),
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
