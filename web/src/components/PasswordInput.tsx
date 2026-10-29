// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FiEye, FiEyeOff } from 'react-icons/fi';

interface Props extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
}

export default function PasswordInput({ label, className = '', id, ...rest }: Props) {
  const { t } = useTranslation();
  const [show, setShow] = useState(false);
  const autoId = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const inputId = id || `password-${autoId}`;
  return (
    <div className="ui-field">
      {label && <label className="ui-field-label" htmlFor={inputId}>{label}</label>}
      <div className="ui-field-control login-password-wrap">
        <input id={inputId} type={show ? 'text' : 'password'} className={`ui-input login-password-input ${className}`} {...rest} />
        <button type="button" className="login-password-toggle" onClick={() => setShow((v) => !v)} aria-label={show ? t('hidePassword', 'Hide password') : t('showPassword', 'Show password')}>
          {show ? <FiEyeOff aria-hidden="true" /> : <FiEye aria-hidden="true" />}
        </button>
      </div>
    </div>
  );
}
