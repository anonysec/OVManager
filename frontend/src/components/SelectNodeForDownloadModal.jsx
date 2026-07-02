import { useState, useEffect } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import LoadingButton from './LoadingButton';

const SelectNodeForDownloadModal = ({ user, onClose }) => {
  const [nodes, setNodes] = useState([]);
  const [selectedNodeId, setSelectedNodeId] = useState('');
  const [isLoadingNodes, setIsLoadingNodes] = useState(true);
  const [isDownloading, setIsDownloading] = useState(false);
  const [error, setError] = useState('');
  const { t } = useTranslation();

  const nodeIsActive = (node) => node.status === true || node.status === 'active';

  const decodeArrayBuffer = (data) => {
    try {
      return new TextDecoder('utf-8').decode(new Uint8Array(data));
    } catch {
      return '';
    }
  };

  const looksLikeOpenVpnConfig = (text) => {
    const trimmed = text.trimStart();
    return (
      trimmed.startsWith('client') ||
      trimmed.includes('\nclient\n') ||
      (trimmed.includes('<ca>') && trimmed.includes('</ca>')) ||
      trimmed.includes('remote ')
    );
  };

  useEffect(() => {
    const fetchNodes = async () => {
      try {
        const response = await apiClient.get('/nodes/');
        if (response.data.success && response.data.data) {
          const available = response.data.data.filter(nodeIsActive);
          setNodes(available);
          if (available.length > 0) setSelectedNodeId(String(available[0].id));
        }
      } catch {
        setError('Failed to load available nodes.');
      } finally {
        setIsLoadingNodes(false);
      }
    };
    fetchNodes();
  }, []);

  const handleDownload = async (e) => {
    e.preventDefault();
    setError('');
    setIsDownloading(true);

    try {
      if (!selectedNodeId) throw new Error('No node selected for download.');
      const selectedNode = nodes.find(n => String(n.id) === String(selectedNodeId));
      if (!selectedNode) throw new Error('Selected node not found.');

      const downloadUrl = `/nodes/ovpn/${user.uuid}/${selectedNode.id}`;
      const downloadFileName = `${user.name}-${selectedNode.name}.ovpn`;

      const response = await apiClient.get(downloadUrl, {
        responseType: 'arraybuffer',
        headers: { Accept: 'application/x-openvpn-profile,text/plain,*/*' },
        validateStatus: () => true,
      });

      const contentType = (response.headers['content-type'] || '').toLowerCase();
      const text = decodeArrayBuffer(response.data);
      const startsWithHtml = text.trimStart().toLowerCase().startsWith('<!doctype html') || text.trimStart().toLowerCase().startsWith('<html');

      if (response.status < 200 || response.status >= 300) {
        if (contentType.includes('application/json')) {
          try {
            const errorData = JSON.parse(text);
            throw new Error(errorData.detail || errorData.msg || `Download failed with HTTP ${response.status}.`);
          } catch {
            throw new Error(`Download failed with HTTP ${response.status}.`);
          }
        }
        throw new Error(text.slice(0, 300) || `Download failed with HTTP ${response.status}.`);
      }

      if (contentType.includes('application/json')) {
        try {
          const errorData = JSON.parse(text);
          throw new Error(errorData.detail || errorData.msg || 'Server returned JSON instead of an OVPN profile.');
        } catch (jsonError) {
          if (jsonError.message) throw jsonError;
          throw new Error('Server returned JSON instead of an OVPN profile.');
        }
      }

      if (contentType.includes('text/html') || startsWithHtml || !looksLikeOpenVpnConfig(text)) {
        throw new Error('Panel received HTML or invalid content instead of an OpenVPN profile. Check panel URLPATH/API build and node selection.');
      }

      const blob = new Blob([response.data], { type: 'application/x-openvpn-profile' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', downloadFileName);
      document.body.appendChild(link);
      link.click();
      link.parentNode.removeChild(link);
      window.URL.revokeObjectURL(url);
      onClose();
    } catch (err) {
      setError(err.message || `Failed to download config for user "${user.name}".`);
    } finally {
      setIsDownloading(false);
    }
  };

  if (!user) return null;

  return (
    <div className="modal-overlay">
      <div className="modal">
        <div className="modal-header">
          <h3>{t('selectNodeForDownload', 'Select Source for')} {user.name}</h3>
          <button onClick={onClose} className="close-modal-btn">&times;</button>
        </div>
        <form onSubmit={handleDownload}>
          <div className="input-group">
            <label htmlFor="node-select">{t('downloadSource', 'Download Source')}</label>
            {isLoadingNodes ? (
              <p>Loading nodes...</p>
            ) : nodes.length === 0 ? (
              <p>{t('noNodesAvailable', 'No active nodes available for download.')}</p>
            ) : (
              <select
                id="node-select"
                value={selectedNodeId}
                onChange={(e) => setSelectedNodeId(e.target.value)}
                style={{ width: '100%', padding: '10px', backgroundColor: 'var(--background-primary)', color: 'var(--text-primary)', border: '1px solid var(--border-color)', borderRadius: '8px' }}
                required
              >
                {nodes.map(node => (
                  <option key={node.id} value={String(node.id)}>
                    {node.name} ({node.address}:{node.port})
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" onClick={onClose} className="btn btn-secondary">{t('cancelButton')}</button>
            <LoadingButton
              isLoading={isDownloading}
              type="submit"
              className="btn btn-success"
              disabled={isLoadingNodes || nodes.length === 0}
            >
              {t('downloadButton', 'Download')}
            </LoadingButton>
          </div>
          {error && <p className="error-message">{error}</p>}
        </form>
      </div>
    </div>
  );
};

export default SelectNodeForDownloadModal;
