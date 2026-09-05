import { useState, useEffect } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import LoadingButton from './LoadingButton';
import Modal from './Modal';
import { CODES } from '../utils/geo';

const parseBundle = (raw, t) => {
  // ovnode://<name>@<host>:<port>?key=<APIKEY>&tls=0|1  (printed by the node installer)
  const m = String(raw || '').trim().match(/^ovnode:\/\/([^@]+)@([^:/?#]+)(?::(\d+))?\?([^#]*)$/);
  if (!m) return { error: t('nodeBundleInvalid') };
  const [, name, address, port, query] = m;
  const params = new URLSearchParams(query);
  const key = params.get('key') || '';
  if (!name || !address || !key) return { error: t('nodeBundleMissing') };
  return {
    values: {
      name,
      address,
      port: port ? Number(port) : 2083,
      key,
      use_tls: params.get('tls') === '1',
    },
  };
};

const BLANK = {
  name: '', address: '', tunnel_address: '', protocol: 'tcp',
  ovpn_port: 1194, port: 2083, key: '', status: true, set_new_setting: true, use_tls: true,
  country_code: '',
};

// Unified add/edit node form. mode="create" (node=null) or mode="edit".
// Replaces AddNodeModal + EditNodeModal. Create-only: bundle paste + test
// connection. Edit-only: blank-key-keeps-existing + apply-settings checkbox.
const NodeFormModal = ({ node, isOpen, onClose, onSaved }) => {
  const isEdit = !!node;
  const { t } = useTranslation();
  const [formData, setFormData] = useState(BLANK);
  const [bundle, setBundle] = useState('');
  const [bundleError, setBundleError] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState(null); // {ok, msg}

  useEffect(() => {
    if (isEdit && node) {
      setFormData({
        name: node.name || '', address: node.address || '', tunnel_address: node.tunnel_address || '',
        protocol: node.protocol || 'tcp', ovpn_port: node.ovpn_port || 1194, port: node.port || 2083,
        key: '', status: node.status === 'active' || node.status === true,
        set_new_setting: false, // metadata edits must not require the node to be online
        use_tls: node.use_tls === true,
        country_code: node.country_code || '',
      });
    } else if (!isEdit) {
      setFormData(BLANK);
      setBundle('');
      setBundleError('');
    }
    setError('');
    setTestResult(null);
  }, [node, isOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = (event) => {
    const { name, value, type, checked } = event.target;
    setFormData((prev) => ({ ...prev, [name]: type === 'checkbox' ? checked : value }));
    setTestResult(null);
  };

  const applyBundle = () => {
    const parsed = parseBundle(bundle, t);
    if (parsed.error) {
      setBundleError(parsed.error);
      return;
    }
    setBundleError('');
    setFormData((prev) => ({ ...prev, ...parsed.values }));
    setTestResult(null);
  };

  const buildPayload = () => {
    const payload = {
      ...formData,
      ovpn_port: Number(formData.ovpn_port),
      port: Number(formData.port),
      // Blank = auto-detect; the API rejects "" (pattern), so send null.
      country_code: (formData.country_code || '').trim() || null,
    };
    if (isEdit) {
      payload.status = Boolean(formData.status);
      if (!payload.key || payload.key.trim() === '') delete payload.key;
    }
    return payload;
  };

  const requestError = (err, fallback) => {
    const errorData = err.response?.data;
    if (errorData?.detail) {
      return Array.isArray(errorData.detail)
        ? errorData.detail.map(item => item.msg).join(', ')
        : typeof errorData.detail === 'string' ? errorData.detail : JSON.stringify(errorData.detail);
    }
    if (typeof errorData?.msg === 'string' && errorData.msg) return errorData.msg;
    return fallback;
  };

  const handleTest = async () => {
    setError('');
    setTestResult(null);
    setIsTesting(true);
    try {
      const response = await apiClient.post('/nodes/test', buildPayload());
      setTestResult({ ok: !!response.data.success, msg: response.data.msg || '' });
    } catch (err) {
      setTestResult({ ok: false, msg: requestError(err, t('nodeTestFailed')) });
    } finally {
      setIsTesting(false);
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      const response = isEdit
        ? await apiClient.put(`/nodes/${node.id}`, buildPayload())
        : await apiClient.post('/nodes/', buildPayload());
      if (response.data.success) {
        onSaved(response.data.msg);
      } else {
        setError(response.data.msg || t(isEdit ? 'nodeUpdateFailed' : 'nodeCreateFailed'));
      }
    } catch (err) {
      setError(requestError(err, t(isEdit ? 'nodeUpdateFailed' : 'nodeCreateFailed')));
    } finally {
      setIsLoading(false);
    }
  };

  const idp = (s) => `${isEdit ? 'edit' : 'new'}-${s}`;

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={isEdit ? `${t('modal_editNodeTitle', 'Edit Node')} — ${node?.name || ''}` : t('modal_createNodeTitle')} size="medium">
      <form onSubmit={handleSubmit} className="modal-form">
        {!isEdit && (
          <>
            <p className="modal-section-title">{t('nodeSectionQuick', 'Quick setup')}</p>
            <div className="input-group">
              <label htmlFor="node-bundle">{t('nodeBundleLabel', 'Paste node bundle')}</label>
            <div className="shortcut-row">
              <input
                type="text"
                id="node-bundle"
                value={bundle}
                onChange={(e) => setBundle(e.target.value)}
                placeholder={t('nodeBundlePlaceholder', 'ovnode://node-1@203.0.113.10:2083?key=…&tls=1')}
                className="shortcut-input"
                spellCheck={false}
              />
              <div className="shortcut-btns">
                <button type="button" onClick={applyBundle} className="btn btn-secondary btn-sm">
                  {t('nodeBundleApply', 'Fill fields')}
                </button>
              </div>
            </div>
            <span className="input-hint">
              {t('nodeBundleHint', 'Printed by the node installer (“Bundle”) and its --json output. Fills every field below.')}
            </span>
            {bundleError && <p className="modal-error" role="alert">{bundleError}</p>}
            </div>
          </>
        )}
        <p className="modal-section-title">{t('nodeSectionConnection', 'Connection')}</p>
        <div className="modal-grid">
          <div className="input-group">
            <label htmlFor={idp('name')}>{t('nodeName')}</label>
            <input type="text" id={idp('name')} name="name" value={formData.name} onChange={handleChange} required />
            {!isEdit && <span className="input-hint">{t('nodeNameHint', 'Must match the --name given to the node installer, exactly.')}</span>}
          </div>
          <div className="input-group">
            <label htmlFor={idp('address')}>{t('th_address')}</label>
            <input type="text" id={idp('address')} name="address" value={formData.address} onChange={handleChange} required />
            {!isEdit && <span className="input-hint">{t('nodeAddressHint', 'Public IP or hostname of the node server.')}</span>}
          </div>
          <div className="input-group">
            <label htmlFor={idp('port')}>{t('nodePort')}</label>
            <input type="number" id={idp('port')} name="port" value={formData.port} onChange={handleChange} required />
            {!isEdit && <span className="input-hint">{t('nodePortHint', 'Sync API port (2083 default) — not the OpenVPN port.')}</span>}
          </div>
          <div className="input-group">
            <label htmlFor={idp('tunnel_address')}>{t('tunnelAddress')} <span className="input-hint">({t('optional', 'Optional')})</span></label>
            <input type="text" id={idp('tunnel_address')} name="tunnel_address" value={formData.tunnel_address} onChange={handleChange} />
          </div>
          <div className="input-group">
            <label htmlFor={idp('protocol')}>{t('th_protocol')}</label>
            <select id={idp('protocol')} name="protocol" value={formData.protocol} onChange={handleChange}>
              <option value="tcp">TCP</option>
              <option value="udp">UDP</option>
            </select>
          </div>
          <div className="input-group">
            <label htmlFor={idp('ovpn_port')}>{t('ovpnPort')}</label>
            <input type="number" id={idp('ovpn_port')} name="ovpn_port" value={formData.ovpn_port} onChange={handleChange} required />
          </div>
          <div className="input-group">
            <label htmlFor={idp('country_code')}>{t('nodeCountry', 'Country')}</label>
            <select id={idp('country_code')} name="country_code" value={formData.country_code} onChange={handleChange}>
              <option value="">{t('nodeCountryAuto', 'Auto-detect from IP')}</option>
              {Object.entries(CODES).map(([code, entry]) => (
                <option key={code} value={code}>{entry.name}</option>
              ))}
            </select>
            <span className="input-hint">
              {t('nodeCountryHint', 'Leave on auto-detect unless the lookup is wrong — a manual pick always wins.')}
            </span>
          </div>
          <div className="input-group" style={{ gridColumn: '1 / -1' }}>
            <label htmlFor={idp('key')}>{t('key')}</label>
            <input
              type="text" id={idp('key')} name="key" value={formData.key} onChange={handleChange}
              required={!isEdit}
              placeholder={isEdit
                ? t('keyKeepExistingHint', 'Leave blank to keep existing key')
                : t('nodeKeyHint', 'From the node installer summary (API key) — copy it exactly.')}
            />
          </div>
          {isEdit ? (
            <label className="modal-check-row" style={{ gridColumn: '1 / -1' }}>
              <input type="checkbox" name="set_new_setting" checked={formData.set_new_setting} onChange={handleChange} />
              <span>
                {t('applyNodeSettings', 'Apply new VPN settings on the node')}
                <small>{t('applyNodeSettingsHint', 'Re-writes OpenVPN protocol/port/tunnel on the node. Leave off to only update this panel record — works even when the node is offline.')}</small>
              </span>
            </label>
          ) : (
            <label className="modal-check-row" style={{ gridColumn: '1 / -1' }} htmlFor="node-use_tls">
              <input type="checkbox" id="node-use_tls" name="use_tls" checked={!!formData.use_tls} onChange={handleChange} />
              <span>
                {t('nodeUseTls', 'Use TLS (https)')}
                <small>{t('nodeUseTlsHint', 'On when the node used self-signed or Let’s Encrypt; off only when the node used TLS None.')}</small>
              </span>
            </label>
          )}
        </div>

        {testResult && (
          <p className={testResult.ok ? 'success-message' : 'modal-error'} role="status">{testResult.msg}</p>
        )}
        {error && <p className="modal-error" role="alert">{error}</p>}
        <div className="modal-footer">
          <button type="button" onClick={onClose} className="btn btn-secondary">{t('cancelButton')}</button>
          {!isEdit && (
            <button type="button" onClick={handleTest} className="btn btn-secondary" disabled={isTesting || isLoading}>
              {isTesting ? t('nodeTesting', 'Testing…') : t('nodeTestButton', 'Test connection')}
            </button>
          )}
          <LoadingButton isLoading={isLoading} type="submit" className="btn">
            {isEdit ? t('updateNodeButton', 'Update Node') : t('createNodeButton')}
          </LoadingButton>
        </div>
      </form>
    </Modal>
  );
};

export default NodeFormModal;
