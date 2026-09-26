import { Component } from 'react';
import { withTranslation } from 'react-i18next';

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo);
  }

  render() {
    const { t } = this.props;
    if (this.state.hasError) {
      return (
        <div style={{
          padding: '40px', textAlign: 'center',
          fontFamily: 'var(--font-sans, sans-serif)',
          color: 'var(--text-secondary, #cccccc)',
          background: 'var(--bg, #0e1116)',
          minHeight: '100vh',
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'
        }}>
          <h1 style={{ fontSize: '48px', margin: '0 0 16px', color: 'var(--danger-text, #ff7a8a)' }} aria-hidden="true">⚠</h1>
          <h2 style={{ margin: '0 0 8px', color: 'var(--text-primary, #f7f8fa)' }}>
            {t('errorBoundaryTitle', 'Something went wrong')}
          </h2>
          <p style={{ color: 'var(--text-muted, #838a96)', maxWidth: 500, marginBottom: 24 }}>
            {t('errorBoundaryDesc', 'An unexpected error occurred. Please try refreshing the page.')}
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: '10px 24px',
              background: 'var(--accent, #ff6a1a)',
              color: 'var(--accent-contrast, #15110a)',
              border: 'none', borderRadius: '8px', cursor: 'pointer',
              fontSize: '14px', fontWeight: 600,
            }}
          >
            {t('reloadPage', 'Reload page')}
          </button>
          {this.state.error && (
            <details style={{ marginTop: 24, textAlign: 'left', maxWidth: 600 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--text-muted, #838a96)' }}>
                {t('errorDetails', 'Error details')}
              </summary>
              <pre style={{
                fontSize: '12px',
                color: 'var(--text-secondary, #9aa1ad)',
                marginTop: 8, whiteSpace: 'pre-wrap',
              }}>
                {this.state.error.toString()}
              </pre>
            </details>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}

const TranslatedErrorBoundary = withTranslation()(ErrorBoundary);
export default TranslatedErrorBoundary;