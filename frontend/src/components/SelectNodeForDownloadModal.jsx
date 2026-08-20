import { useState, useEffect } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import LoadingButton from './LoadingButton';
import Modal from './Modal';
import { FiServer, FiDownload, FiCheck } from 'react-icons/fi';

const SelectNodeForDownloadModal = ({ user, isOpen, onClose }) => {
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
      setIsLoadingNodes(true);
      setError('');
      try {
        const response = await apiClient.get('/nodes/');
        if (response.data.success && response.data.data) {
          const available = response.data.data.filter(nodeIsActive);
          setNodes(available);
          if (available.length > 0) setSelectedNodeId(String(available[0].id));
        } else {
          setNodes([]);
        }
      } catch {
        setError(t('noNodesAvailable', 'Failed to load available nodes.'));
      } finally {
        setIsLoadingNodes(false);
      }
    };
    if (isOpen) fetchNodes();
  }, [isOpen, t]);

  const handleDownload = async (e) => {
    e.preventDefault();
    setError('');
    setIsDownloading(true);
    try {
      if (!selectedNodeId) throw new Error(t('noNodeSelected', 'No node selected for download.'));
      const selectedNode = nodes.find(n => String(n.id) === String(selectedNodeId));
      if (!selectedNode) throw new Error(t('noNodeSelected', 'Selected node not found.'));
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
        throw new Error(t('ovpnInvalid', 'Panel received HTML or invalid content instead of an OpenVPN profile. Check panel URLPATH/API build and node selection.'));
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

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`${t('downloadConfigFromNode')} — ${user?.name || ''}`} size="medium">
      <div className="node-pick">
        <p className="node-pick-hint">{t('downloadSourceHint', 'Choose a node to pull the OpenVPN profile from.')}</p>

        {isLoadingNodes ? (
          <div className="node-pick-loading">{t('loadingNodesDots', 'Loading nodes...')}</div>
        ) : nodes.length === 0 ? (
          <div className="node-pick-empty">{t('noNodesAvailable', 'No active nodes available for download.')}</div>
        ) : (
          <div className="node-pick-list">
            {nodes.map((node) => {
              const active = String(selectedNodeId) === String(node.id);
              return (
                <button
                  type="button"
                  key={node.id}
                  className={`node-pick-item${active ? ' active' : ''}`}
                  onClick={() => setSelectedNodeId(String(node.id))}
                  aria-pressed={active}
                >
                  <span className="npi-ico"><FiServer /></span>
                  <span className="npi-body">
                    <span className="npi-name">{node.name}</span>
                    <span className="npi-addr">{node.address}:{node.port}</span>
                  </span>
                  {active && <span className="npi-check"><FiCheck /></span>}
                </button>
              );
            })}
          </div>
        )}

        {error && <p className="error-message">{error}</p>}

        <div className="modal-footer">
          <button type="button" onClick={onClose} className="btn btn-secondary">{t('cancelButton')}</button>
          <LoadingButton isLoading={isDownloading} type="submit" className="btn btn-success" disabled={isLoadingNodes || nodes.length === 0} onClick={handleDownload}>
            <FiDownload /> {t('downloadButton', 'Download')}
          </LoadingButton>
        </div>
      </div>
    </Modal>
  );
};

export default SelectNodeForDownloadModal;
