// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * SetupWizard — the first-login checklist, reachable at /setup.
 *
 * Three steps: install/add a node, create a user, download a config.
 * Steps 1 and 2 check themselves off from GET /health/setup; step 3 is a
 * manual "Mark as done" (a download cannot be observed by the panel).
 *
 * Nothing auto-redirects here. "Skip" stores a dismissal so the small Home
 * banner stops asking; the page itself stays reachable at /setup.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import apiClient from '../services/api';
import { Badge, Button, Card, ErrorState, PanelSkeleton, PageHeader } from '../components/ui';
import { copyText } from '../utils/clipboard';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import {
  FiCheck, FiCompass, FiCopy, FiDownload,
  FiExternalLink, FiRefreshCw, FiServer, FiUser, FiX,
} from 'react-icons/fi';
import './SetupWizard.css';

const DISMISS_KEY = 'ovmanager-setup-dismissed';
const CONFIG_DONE_KEY = 'ovmanager-setup-config-done';
const NODE_INSTALL_CMD = 'bash <(curl -sSL https://anonysec.github.io/OVNode/install.sh)';

const SetupWizard = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const navigate = useNavigate();
  const { userRole } = useAuth();
  const isOwner = userRole === 'owner';
  const [setup, setSetup] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [copied, setCopied] = useState(false);
  const [configDone, setConfigDone] = useState(() => localStorage.getItem(CONFIG_DONE_KEY) === '1');

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      // Not wrapped in ResponseModel — the counters are the whole body.
      const res = await apiClient.get('/health/setup');
      setSetup(res.data || null);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const nodeDone = !!setup?.has_active_node;
  const nodePartial = !nodeDone && !!setup?.has_node;
  const userDone = !!setup?.has_user;

  const doneCount = useMemo(
    () => [nodeDone, userDone, configDone].filter(Boolean).length,
    [nodeDone, userDone, configDone],
  );
  const allDone = doneCount === 3;

  const copyCommand = async () => {
    const ok = await copyText(NODE_INSTALL_CMD);
    if (ok) {
      setCopied(true);
      addToast(t('copied', 'Copied!'), 'success');
      setTimeout(() => setCopied(false), 1500);
    }
  };

  const markConfigDone = () => {
    localStorage.setItem(CONFIG_DONE_KEY, '1');
    setConfigDone(true);
  };

  const skip = () => {
    localStorage.setItem(DISMISS_KEY, '1');
    addToast(t('setupSkipped', 'Setup wizard hidden. Open /setup any time to return.'), 'info');
    navigate('/');
  };

  if (loading && !setup) {
    return (
      <div className="setup-page">
        <PanelSkeleton lines={6} label={t('loading', 'Loading…')} />
      </div>
    );
  }

  if (error && !setup) {
    return (
      <div className="setup-page">
        <ErrorState
          title={t('setupLoadError', 'Could not check setup progress')}
          message={t('setupLoadErrorDetail', 'The panel could not read its own counters. Try again in a moment.')}
          onRetry={load}
          retryLabel={t('retry', 'Retry')}
        />
      </div>
    );
  }

  const steps = [
    {
      id: 'node',
      icon: FiServer,
      title: t('setupStepNode', 'Install a node'),
      desc: t('setupStepNodeDesc', 'Nodes are the servers users actually connect to. Add this server, or connect a remote one.'),
      done: nodeDone,
      partial: nodePartial,
      content: isOwner ? (
        <>
          <div className="setup-command">
            <code>{NODE_INSTALL_CMD}</code>
            <button
              type="button"
              className="setup-copy"
              onClick={copyCommand}
              aria-label={t('setupCopyCommand', 'Copy command')}
              title={copied ? t('copied', 'Copied!') : t('setupCopyCommand', 'Copy command')}
            >
              {copied ? <FiCheck aria-hidden="true" /> : <FiCopy aria-hidden="true" />}
            </button>
          </div>
          <p className="setup-hint">
            {t('setupSameServerHint', 'Same server as OVManager? The installer’s Ready card already printed a ready-to-paste OVNode command with the API key — run that instead, then paste the ovnode:// bundle into Nodes → Add Node.')}
          </p>
          <div className="setup-actions">
            <Link to="/nodes" className="setup-link">
              <Button variant="primary" size="sm" icon={<FiExternalLink size={13} aria-hidden="true" />}>
                {t('setupOpenNodes', 'Open Nodes')}
              </Button>
            </Link>
            {!nodeDone && (
              <Button variant="ghost" size="sm" icon={<FiRefreshCw size={13} aria-hidden="true" />} onClick={load}>
                {t('setupRefresh', 'Refresh checks')}
              </Button>
            )}
          </div>
        </>
      ) : (
        <div className="setup-actions">
          <p className="setup-hint">
            {t('setupNodeOwnerOnly', 'Only the panel owner can add nodes. Ask the owner to connect one, then press Refresh.')}
          </p>
          <Button variant="ghost" size="sm" icon={<FiRefreshCw size={13} aria-hidden="true" />} onClick={load}>
            {t('setupRefresh', 'Refresh checks')}
          </Button>
        </div>
      ),
    },
    {
      id: 'user',
      icon: FiUser,
      title: t('setupStepUser', 'Create a user'),
      desc: t('setupStepUserDesc', 'A user gets a personal config they import into the OpenVPN app. Expiry and traffic limits live here.'),
      done: userDone,
      content: (
        <>
          {userDone && setup?.user_count > 0 && (
            <p className="setup-hint">
              {t('setupUserCount', '{{count}} user(s) already exist.', { count: setup.user_count })}
            </p>
          )}
          <div className="setup-actions">
            <Link to="/users" className="setup-link">
              <Button variant="primary" size="sm" icon={<FiExternalLink size={13} aria-hidden="true" />}>
                {t('setupOpenUsers', 'Open Users')}
              </Button>
            </Link>
            {!userDone && (
              <Button variant="ghost" size="sm" icon={<FiRefreshCw size={13} aria-hidden="true" />} onClick={load}>
                {t('setupRefresh', 'Refresh checks')}
              </Button>
            )}
          </div>
        </>
      ),
    },
    {
      id: 'config',
      icon: FiDownload,
      title: t('setupStepConfig', 'Download a config'),
      desc: t('setupStepConfigDesc', 'In Users, press the download icon on the user row, pick a node, and save the .ovpn file. Import it into any OpenVPN client — that is the whole connection flow.'),
      done: configDone,
      content: (
        <div className="setup-actions">
          <Link to="/users" className="setup-link">
            <Button variant="secondary" size="sm" icon={<FiExternalLink size={13} aria-hidden="true" />}>
              {t('setupOpenUsers', 'Open Users')}
            </Button>
          </Link>
          {!configDone && (
            <Button variant="ghost" size="sm" icon={<FiCheck size={13} aria-hidden="true" />} onClick={markConfigDone}>
              {t('setupMarkDone', 'Mark as done')}
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="setup-page">
      <PageHeader
        title={t('setupTitle', 'Setup wizard')}
        icon={<FiCompass aria-hidden="true" />}
        subtitle={t('setupSubtitle', 'Three quick steps to get your panel ready for real users.')}
        meta={(
          <span className="setup-progress" aria-live="polite">
            <span className="setup-progress-track" aria-hidden="true">
              <span className="setup-progress-fill" style={{ width: `${(doneCount / 3) * 100}%` }} />
            </span>
            <span>{t('setupProgress', '{{done}} of 3 done', { done: doneCount })}</span>
          </span>
        )}
      />

      {allDone && (
        <Card tone="success" className="setup-alldone">
          <strong>{t('setupAllDone', 'All set! Your panel is ready.')}</strong>
          <p>{t('setupAllDoneBody', 'Node, user and config are in place. You can close this page.')}</p>
        </Card>
      )}

      <ol className="setup-steps">
        {steps.map((step, index) => {
          const Icon = step.icon;
          return (
            <li
              key={step.id}
              className={[
                'setup-step',
                step.done ? 'is-done' : '',
                step.partial ? 'is-partial' : '',
              ].filter(Boolean).join(' ')}
            >
              <span className="setup-step-marker" aria-hidden="true">
                {step.done ? <FiCheck /> : <span>{index + 1}</span>}
              </span>
              <div className="setup-step-body">
                <div className="setup-step-head">
                  <h2 className="setup-step-title">
                    <Icon size={16} aria-hidden="true" /> {step.title}
                  </h2>
                  {step.done ? (
                    <Badge tone="success" dot>{t('setupDone', 'Done')}</Badge>
                  ) : step.partial ? (
                    <Badge tone="warning" dot>{t('setupInProgress', 'Almost there')}</Badge>
                  ) : (
                    <Badge tone="neutral">{t('setupTodo', 'To do')}</Badge>
                  )}
                </div>
                <p className="setup-step-desc">{step.desc}</p>
                {step.partial && (
                  <p className="setup-hint">
                    {t('setupNodeInactive', 'A node was added but is not answering yet. Open Nodes and test the connection.')}
                  </p>
                )}
                {step.content}
              </div>
            </li>
          );
        })}
      </ol>

      <div className="setup-footer">
        <Button variant="ghost" size="sm" icon={<FiX size={13} aria-hidden="true" />} onClick={skip}>
          {t('setupSkip', 'Skip for now')}
        </Button>
        <p className="setup-footer-note">
          {t('setupSkipNote', 'Skipping hides the reminder on Home. The wizard stays available at /setup.')}
        </p>
      </div>
    </div>
  );
};

export default SetupWizard;
