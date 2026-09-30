import { Component } from 'react';
import type { ReactNode } from 'react';
import { withTranslation } from 'react-i18next';
import { FiAlertTriangle, FiRefreshCw } from 'react-icons/fi';

type SectionBoundaryProps = {
  name?: any;
  onError?: any;
  resetKey?: any;
  onRetry?: any;
  t?: any;
  children?: ReactNode;
  title?: any;
  compact?: any;
  [key: string]: any;
};

type SectionBoundaryState = {
  hasError: boolean;
  error: any;
  resetKey: number;
};

// The app-level ErrorBoundary is a last resort that replaces the whole panel.
// That is the wrong trade-off for a dashboard of independent widgets: a throw
// while rendering the world map must not take down the users table beside it.
// The local retry remounts only this subtree (via the `resetKey` bump), so the
// rest of the page keeps its state.
class SectionBoundaryInner extends Component<SectionBoundaryProps, SectionBoundaryState> {
  constructor(props: SectionBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null, resetKey: 0 };
  }

  static getDerivedStateFromError(error: any) {
    return { hasError: true, error };
  }

  componentDidCatch(error: any, info: any) {
    // Keep the section name so a console trace points at the right widget.
    console.error(`[SectionBoundary:${this.props.name || 'unnamed'}]`, error, info);
    this.props.onError?.(error, info);
  }

  handleRetry = () => {
    this.setState((s: SectionBoundaryState) => ({ hasError: false, error: null, resetKey: s.resetKey + 1 }));
    this.props.onRetry?.();
  };

  render() {
    const { t, children, title, compact } = this.props;

    if (this.state.hasError) {
      return (
        <div className={`section-error${compact ? ' section-error--compact' : ''}`} role="alert">
          <span className="section-error-icon" aria-hidden="true">
            <FiAlertTriangle />
          </span>
          <div className="section-error-copy">
            <strong>{title || t('sectionErrorTitle', 'This section could not be displayed')}</strong>
            <span>{t('sectionErrorDesc', 'The rest of the page is still usable.')}</span>
          </div>
          <button type="button" className="btn btn-sm btn-secondary" onClick={this.handleRetry}>
            <FiRefreshCw size={13} aria-hidden="true" />
            <span>{t('retry', 'Retry')}</span>
          </button>
        </div>
      );
    }

    return <div key={this.state.resetKey}>{children}</div>;
  }
}

const SectionBoundary = withTranslation()(SectionBoundaryInner);

export default SectionBoundary;
