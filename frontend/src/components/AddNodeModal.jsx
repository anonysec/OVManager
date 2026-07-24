import { useState } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import LoadingButton from './LoadingButton';
import Modal from './Modal';

const AddNodeModal = ({ isOpen, onClose, onNodeCreated }) => {
  const { t } = useTranslation();
  const [formData, setFormData] = useState({
    name: '', address: '', tunnel_address: '', protocol: 'tcp',
    ovpn_port: 1194, port: 2083, key: '', status: true, set_new_setting: true, use_tls: false,
  });
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleChange = (event) => {
    const { name, value, type, checked } = event.target;
    setFormData((prev) => ({ ...prev, [name]: type === 'checkbox' ? checked : value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');
    setIsLoading(true);
    const payload = { ...formData, ovpn_port: Number(formData.ovpn_port), port: Number(formData.port) };
    try {
      const response = await apiClient.post('/nodes/', payload);
      if (response.data.success) {
        onNodeCreated();
      } else {
        setError(response.data.msg || 'Unable to create node.');
      }
    } catch (err) {
      const errorData = err.response?.data;
      let errorMessage = 'An error occurred while creating the node.';
      if (errorData?.detail) {
        errorMessage = Array.isArray(errorData.detail)
          ? errorData.detail.map(item => item.msg).join(', ')
          : typeof errorData.detail === 'string' ? errorData.detail : JSON.stringify(errorData.detail);
      }
      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={t('modal_createNodeTitle')} size="large">
      <form onSubmit={handleSubmit} className="modal-form">
        <div className="modal-grid">
          <div className="input-group">
            <label htmlFor="name">{t('nodeName')}</label>
            <input type="text" id="name" name="name" value={formData.name} onChange={handleChange} required />
          </div>
          <div className="input-group">
            <label htmlFor="address">{t('th_address')}</label>
            <input type="text" id="address" name="address" value={formData.address} onChange={handleChange} required />
          </div>
          <div className="input-group">
            <label htmlFor="port">{t('nodePort')}</label>
            <input type="number" id="port" name="port" value={formData.port} onChange={handleChange} required />
          </div>
          <div className="input-group">
            <label htmlFor="tunnel_address">{t('tunnelAddress')} <span className="input-hint">({t('optional', 'Optional')})</span></label>
            <input type="text" id="tunnel_address" name="tunnel_address" value={formData.tunnel_address} onChange={handleChange} />
          </div>
          <div className="input-group">
            <label htmlFor="protocol">{t('th_protocol')}</label>
            <select id="protocol" name="protocol" value={formData.protocol} onChange={handleChange}>
              <option value="tcp">TCP</option>
              <option value="udp">UDP</option>
            </select>
          </div>
          <div className="input-group">
            <label htmlFor="ovpn_port">{t('ovpnPort')}</label>
            <input type="number" id="ovpn_port" name="ovpn_port" value={formData.ovpn_port} onChange={handleChange} required />
          </div>
          <div className="input-group" style={{ gridColumn: '1 / -1' }}>
            <label htmlFor="key">{t('key')}</label>
            <input type="text" id="key" name="key" value={formData.key} onChange={handleChange} required />
          </div>
        </div>

        <div className="modal-footer">
          <button type="button" onClick={onClose} className="btn btn-secondary">{t('cancelButton')}</button>
          <LoadingButton isLoading={isLoading} type="submit" className="btn">{t('createNodeButton')}</LoadingButton>
        </div>
        {error && <p className="error-message">{error}</p>}
      </form>
    </Modal>
  );
};

export default AddNodeModal;