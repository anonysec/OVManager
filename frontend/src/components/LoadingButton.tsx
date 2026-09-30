type LoadingButtonProps = {
  isLoading?: any;
  onClick?: any;
  className?: any;
  children?: any;
  disabled?: boolean;
  type?: any;
  [key: string]: any;
};

const LoadingButton = ({ isLoading, onClick, className, children, disabled = false, type, ...rest }: LoadingButtonProps) => {
  // 'btn' is always added below, so strip it from className to avoid a duplicate.
  const cleanClass = (className || '').replace(/\bbtn\b/g, '').trim();
  const finalClass = cleanClass ? `btn ${cleanClass}` : 'btn';

  return (
    <button
      type={type}
      onClick={onClick}
      className={finalClass}
      disabled={isLoading || disabled}
      {...rest}
    >
      {isLoading && (
        <span className="spinner" style={{ marginRight: '8px' }}></span>
      )}
      {children}
    </button>
  );
};

export default LoadingButton;
