import { FiCheckCircle, FiXCircle, FiAlertTriangle, FiCircle, FiHelpCircle } from 'react-icons/fi';
import type { IconType } from 'react-icons';

const ICONS: Record<string, IconType> = {
  online: FiCheckCircle,
  offline: FiXCircle,
  warning: FiAlertTriangle,
  danger: FiAlertTriangle,
  idle: FiCircle,
};

const StatusBadge = ({ status = 'idle', label }: { status?: string; label?: any }) => {
  const Icon: IconType = ICONS[status] || FiHelpCircle;
  const dotClass =
    status === 'online' ? 'online' :
    status === 'offline' ? 'offline' :
    status === 'warning' ? 'warning' :
    status === 'danger' ? 'danger' :
    status === 'idle' ? 'offline' :
    '';
  return (
    <span className={`status-badge status-${status}`}>
      <span className={`status-dot ${dotClass}`} aria-hidden="true" />
      <Icon size={13} className="status-badge-icon" aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
};

export default StatusBadge;