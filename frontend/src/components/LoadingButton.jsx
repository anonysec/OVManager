import React from 'react';

const LoadingButton = ({ isLoading, onClick, className, children }) => {
  // Strip 'btn' from className to avoid duplication since we always add it
  const cleanClass = (className || '').replace(/\bbtn\b/g, '').trim();
  const finalClass = cleanClass ? `btn ${cleanClass}` : 'btn';
  
  return (
    <button
      onClick={onClick}
      className={finalClass}
      disabled={isLoading}
    >
      {isLoading && (
        <span className="spinner" style={{ marginRight: '8px' }}></span>
      )}
      {children}
    </button>
  );
};

export default LoadingButton;
