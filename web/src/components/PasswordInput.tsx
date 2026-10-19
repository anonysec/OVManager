// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState } from 'react';
import { FiEye, FiEyeOff } from 'react-icons/fi';

interface Props extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
}

export default function PasswordInput({ label, className = '', ...rest }: Props) {
  const [show, setShow] = useState(false);
  return (
    <div className="ui-field">
      {label && <label className="ui-field-label">{label}</label>}
      <div className="ui-field-control login-password-wrap">
        <input type={show ? 'text' : 'password'} className={`ui-input login-password-input ${className}`} {...rest} />
        <button type="button" className="login-password-toggle" tabIndex={-1} onClick={() => setShow((v) => !v)} aria-label={show ? 'Hide password' : 'Show password'}>
          {show ? <FiEyeOff aria-hidden="true" /> : <FiEye aria-hidden="true" />}
        </button>
      </div>
    </div>
  );
}
