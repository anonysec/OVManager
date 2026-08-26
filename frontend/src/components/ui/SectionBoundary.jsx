import { Component, Suspense } from 'react';
import { withTranslation } from 'react-i18next';
import { FiAlertTriangle, FiRefreshCw } from 'react-icons/fi';

/**
 * Per-section error boundary.
 *
 * The app-level ErrorBoundary is a last resort: when it trips the whole panel
 * is replaced by an error page. That is the wrong trade-off for a dashboard
 * made of independent widgets — a thrown error while rendering the world map
 * should not take down the users table next to it.
 *
 * SectionBoundary contains the blast radius to one panel and offers a local
 * retry that remounts only that subtree (via the `resetKey` bump), so the rest
 * of the page keeps its state and stays interactive.
 */
class SectionBoundaryInner extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, resetKey: 0 };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    // Keep the section name so a console trace points at the right widget.
    console.error(`[SectionBoundary:${this.props.name || 'unnamed'}]`, error, info);
    this.props.onError?.(error, info);
  }

  handleRetry = () => {
    this.setState((s) => ({ hasError: false, error: null, resetKey: s.resetKey + 1 }));
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

/**
 * Convenience wrapper: error boundary + Suspense in one. Use for lazily
 * imported widgets so a chunk that fails to load degrades to a retry card
 * instead of an unhandled rejection.
 */
export const LazySection = ({ name, title, fallback, compact, children }) => (
  <SectionBoundary name={name} title={title} compact={compact}>
    <Suspense fallback={fallback ?? null}>{children}</Suspense>
  </SectionBoundary>
);

export default SectionBoundary;
