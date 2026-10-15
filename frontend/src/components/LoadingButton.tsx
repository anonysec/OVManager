// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import Button from './ui/Button';

type LoadingButtonProps = {
  isLoading?: any;
  onClick?: any;
  className?: any;
  children?: any;
  disabled?: boolean;
  type?: any;
  [key: string]: any;
};

// Thin adapter over the ui-btn primitive: the legacy `btn btn-sm btn-secondary`
// class strings stay at the call sites, and the button itself renders with the
// shared geometry, spinner and focus behaviour instead of a second copy.
const LoadingButton = ({ isLoading, onClick, className, children, disabled = false, type, ...rest }: LoadingButtonProps) => {
  const cls = className || '';
  const variant = /\bbtn-secondary\b/.test(cls)
    ? 'secondary'
    : /\bbtn-danger\b/.test(cls)
      ? 'danger'
      : /\bbtn-success\b/.test(cls)
        ? 'success'
        : 'primary';
  const size = /\bbtn-sm\b/.test(cls) ? 'md' : 'lg';

  return (
    <Button
      type={type}
      onClick={onClick}
      variant={variant}
      size={size}
      loading={isLoading}
      disabled={disabled}
      {...rest}
    >
      {children}
    </Button>
  );
};

export default LoadingButton;
