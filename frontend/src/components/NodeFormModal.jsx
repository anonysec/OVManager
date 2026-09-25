import { useEffect, useState } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import { FiPlus, FiWifi } from 'react-icons/fi';
import Modal from './Modal';
import { Button, Field } from './ui';
import { CODES } from '../utils/geo';
import './NodeFormModal.css';

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
      use_tls: params.get('tls') !== '0',
    },
  };
};

// New nodes default to UDP: it is the faster transport and what the node
// installer sets up first. Edit keeps whatever the node record already has.
const BLANK = {
  name: '', address: '', tunnel_address: '', protocol: 'udp',
  ovpn_port: 1194, port: 2083, key: '', status: true, set_new_setting: true, use_tls: true,
  country_code: '',
};

const errorText = (err, fallback) => {
  const detail = err.response?.data?.detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || JSON.stringify(item)).join(', ');
  if (detail && typeof detail === 'object') return JSON.stringify(detail);
  if (typeof detail === 'string') return detail;
  if (typeof err.response?.data?.msg === 'string' && err.response.data.msg) return err.response.data.msg;
  return fallback;
};

// Unified add/edit node form. mode="create" (node=null) or mode="edit".
// Fields are grouped into Quick setup / Connection / VPN / Location / Security
// so each screen is a few small decisions, and every problem is reported next
// to the field that caused it.
const NodeFormModal = ({ node, isOpen, onClose, onSaved }) => {
  const isEdit = !!node;
  const { t } = useTranslation();
  const [formData, setFormData] = useState(BLANK);
  const [bundle, setBundle] = useState('');
  const [bundleError, setBundleError] = useState('');
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});
  const [isLoading, setIsLoading] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState(null); // {ok, msg}

  useEffect(() => {
    if (isEdit && node) {
      setFormData({
        name: node.name || '', address: node.address || '', tunnel_address: node.tunnel_address || '',
        protocol: node.protocol || 'udp', ovpn_port: node.ovpn_port || 1194, port: node.port || 2083,
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
    setFieldErrors({});
    setTestResult(null);
  }, [node, isOpen, isEdit]);

  const handleChange = (event) => {
    const { name, value, type, checked } = event.target;
    setFormData((prev) => ({ ...prev, [name]: type === 'checkbox' ? checked : value }));
    setFieldErrors((prev) => (prev[name] ? { ...prev, [name]: undefined } : prev));
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

  const validate = () => {
    const errors = {};
    if (!String(formData.name || '').trim()) errors.name = t('nodeNameRequired', 'Enter a name for this node.');
    if (!String(formData.address || '').trim()) errors.address = t('nodeAddressRequired', "Enter the node's public IP address or hostname.");
    const syncPort = Number(formData.port);
    if (!Number.isInteger(syncPort) || syncPort < 1 || syncPort > 65535) errors.port = t('nodePortInvalid', 'Port must be a whole number from 1 to 65535.');
    const vpnPort = Number(formData.ovpn_port);
    if (!Number.isInteger(vpnPort) || vpnPort < 1 || vpnPort > 65535) errors.ovpn_port = t('nodeOvpnPortInvalid', 'VPN port must be a whole number from 1 to 65535.');
    if (!isEdit && !String(formData.key || '').trim()) errors.key = t('nodeKeyRequired', "Paste the node's API key.");
    return errors;
  };

  const buildPayload = () => {
    const payload = {
      ...formData,
      protocol: formData.protocol || 'udp',
      ovpn_port: Number(formData.ovpn_port),
      port: Number(formData.port),
      // TLS is not optional for new nodes: the API key must never travel in
      // cleartext. Edits preserve the stored value so a working node is
      // never flipped by a metadata change.
      use_tls: isEdit ? formData.use_tls !== false : true,
      // Blank = auto-detect; the API rejects "" (pattern), so send null.
      country_code: (formData.country_code || '').trim() || null,
    };
    if (isEdit) {
      payload.status = Boolean(formData.status);
      if (!payload.key || payload.key.trim() === '') delete payload.key;
    }
    return payload;
  };

  const handleTest = async () => {
    const errors = validate();
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }
    setError('');
    setTestResult(null);
    setIsTesting(true);
    try {
      const response = await apiClient.post('/nodes/test', buildPayload());
      setTestResult({ ok: !!response.data.success, msg: response.data.msg || '' });
    } catch (err) {
      setTestResult({ ok: false, msg: errorText(err, t('nodeTestFailed')) });
    } finally {
      setIsTesting(false);
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const errors = validate();
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }
    setError('');
    setFieldErrors({});
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
      setError(errorText(err, t(isEdit ? 'nodeUpdateFailed' : 'nodeCreateFailed')));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={isEdit ? `${t('modal_editNodeTitle', 'Edit Node')} — ${node?.name || ''}` : t('modal_createNodeTitle')}
      size="medium"
    >
      <form onSubmit={handleSubmit} className="nf-form" noValidate>
        {!isEdit && (
          <fieldset className="nf-section">
            <legend className="nf-legend">{t('nodeSectionQuick', 'Quick setup')}</legend>
            <Field label={t('nodeBundleLabel', 'Paste node bundle')} hint={t('nodeBundleHint', 'Printed by the node installer ("Bundle") and its --json output. Fills every field below.')} error={bundleError}>
              <input
                type="text"
                value={bundle}
                onChange={(e) => { setBundle(e.target.value); setBundleError(''); }}
                placeholder={t('nodeBundlePlaceholder', 'ovnode://node-1@203.0.113.10:2083?key=…&tls=1')}
                spellCheck={false}
              />
            </Field>
            <div className="nf-inline">
              <Button variant="secondary" onClick={applyBundle}>{t('nodeBundleApply', 'Fill fields')}</Button>
            </div>
          </fieldset>
        )}

        <fieldset className="nf-section">
          <legend className="nf-legend">{t('nodeSectionConnection', 'Connection')}</legend>
          <div className="nf-grid">
            <Field label={t('nodeName')} required error={fieldErrors.name} hint={!isEdit ? t('nodeNameHint', 'Must match the --name given to the node installer, exactly.') : undefined}>
              <input
                type="text" name="name" value={formData.name} onChange={handleChange}
                autoFocus={!isEdit} autoComplete="off" spellCheck={false}
              />
            </Field>
            <Field label={t('th_address')} required error={fieldErrors.address} hint={!isEdit ? t('nodeAddressHint', 'Public IP or hostname of the node server.') : undefined}>
              <input type="text" name="address" value={formData.address} onChange={handleChange} autoComplete="off" spellCheck={false} />
            </Field>
            <Field label={t('nodePort')} required error={fieldErrors.port} hint={!isEdit ? t('nodePortHint', 'Sync API port (2083 default) — not the OpenVPN port.') : undefined}>
              <input type="number" name="port" value={formData.port} onChange={handleChange} min="1" max="65535" step="1" inputMode="numeric" />
            </Field>
            <Field label={`${t('tunnelAddress', 'Tunnel address')} (${t('optional', 'Optional')})`}>
              <input type="text" name="tunnel_address" value={formData.tunnel_address} onChange={handleChange} autoComplete="off" spellCheck={false} />
            </Field>
          </div>
        </fieldset>

        <fieldset className="nf-section">
          <legend className="nf-legend">{t('nodeSectionVpn', 'VPN')}</legend>
          <div className="nf-grid">
            <Field label={t('th_protocol', 'Protocol')} hint={t('nodeProtocolHint', 'UDP is usually faster; TCP gets through stricter networks.')}>
              <select name="protocol" value={formData.protocol} onChange={handleChange}>
                <option value="udp">UDP</option>
                <option value="tcp">TCP</option>
              </select>
            </Field>
            <Field label={t('ovpnPort', 'OpenVPN port')} required error={fieldErrors.ovpn_port}>
              <input type="number" name="ovpn_port" value={formData.ovpn_port} onChange={handleChange} min="1" max="65535" step="1" inputMode="numeric" />
            </Field>
          </div>
          {!isEdit && <p className="nf-note">{t('nodeDefaultsNote', 'New nodes default to UDP — change it if the installer used TCP.')}</p>}
        </fieldset>

        <fieldset className="nf-section">
          <legend className="nf-legend">{t('nodeSectionLocation', 'Location')}</legend>
          <Field label={t('nodeCountry', 'Country')} hint={t('nodeCountryHint', 'Leave on auto-detect unless the lookup is wrong — a manual pick always wins.')}>
            <select name="country_code" value={formData.country_code} onChange={handleChange}>
              <option value="">{t('nodeCountryAuto', 'Auto-detect from IP')}</option>
              {Object.entries(CODES).map(([code, entry]) => (
                <option key={code} value={code}>{entry.name}</option>
              ))}
            </select>
          </Field>
        </fieldset>

        <fieldset className="nf-section">
          <legend className="nf-legend">{t('nodeSectionSecurity', 'Security')}</legend>
          <Field
            label={t('key', 'API key')}
            required={!isEdit}
            error={fieldErrors.key}
            hint={!isEdit ? t('nodeKeyHint', 'Paste the API key from the node installer summary.') : undefined}
          >
            <input
              type="text" name="key" value={formData.key} onChange={handleChange}
              placeholder={isEdit ? t('keyKeepExistingHint', 'Leave blank to keep the current key') : ''}
              autoComplete="off" spellCheck={false}
            />
          </Field>
          {isEdit && (
            <label className="nf-check">
              <input type="checkbox" name="set_new_setting" checked={formData.set_new_setting} onChange={handleChange} />
              <span>
                {t('applyNodeSettings', 'Apply new VPN settings on the node')}
                <small>{t('applyNodeSettingsHint', 'Re-writes OpenVPN protocol/port/tunnel on the node. Leave off to only update this panel record — works even when the node is offline.')}</small>
              </span>
            </label>
          )}
          {!isEdit && (
            <p className="nf-note">{t('nodeTlsAlways', 'Connection is always encrypted (TLS). Self-signed nodes verify with a fingerprint on first connect.')}</p>
          )}
        </fieldset>

        {testResult && (
          <p className={`nf-result${testResult.ok ? ' is-ok' : ' is-error'}`} role="status">{testResult.msg}</p>
        )}
        {error && <p className="nf-result is-error" role="alert">{error}</p>}

        <div className="nf-footer">
          <Button variant="secondary" onClick={onClose}>{t('cancelButton')}</Button>
          {!isEdit && (
            <Button variant="secondary" loading={isTesting} disabled={isLoading} icon={<FiWifi size={14} aria-hidden="true" />} onClick={handleTest}>
              {t('nodeTestButton', 'Test connection')}
            </Button>
          )}
          <Button type="submit" variant="primary" loading={isLoading} icon={<FiPlus size={14} aria-hidden="true" />}>
            {isEdit ? t('updateNodeButton', 'Save changes') : t('createNodeButton')}
          </Button>
        </div>
      </form>
    </Modal>
  );
};

export default NodeFormModal;
