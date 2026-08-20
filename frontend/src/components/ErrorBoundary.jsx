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
          padding: '40px', textAlign: 'center', fontFamily: 'sans-serif',
          color: '#ccc', background: '#1e1e2e', minHeight: '100vh',
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'
        }}>
          <h1 style={{ fontSize: '48px', margin: '0 0 16px', color: '#ff7a8a' }}>⚠</h1>
          <h2 style={{ margin: '0 0 8px' }}>{t('errorBoundaryTitle', 'Something went wrong')}</h2>
          <p style={{ color: '#888', maxWidth: 500, marginBottom: 24 }}>
            {t('errorBoundaryDesc', 'An unexpected error occurred. Please try refreshing the page.')}
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: '10px 24px', background: '#ff7a8a', color: '#fff',
              border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '14px'
            }}
          >
            {t('reloadPage', 'Reload page')}
          </button>
          {this.state.error && (
            <details style={{ marginTop: 24, textAlign: 'left', maxWidth: 600 }}>
              <summary style={{ cursor: 'pointer', color: '#888' }}>{t('errorDetails', 'Error details')}</summary>
              <pre style={{ fontSize: '12px', color: '#666', marginTop: 8, whiteSpace: 'pre-wrap' }}>
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