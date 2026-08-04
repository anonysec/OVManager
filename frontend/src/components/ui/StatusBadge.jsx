import { FiCheckCircle, FiXCircle, FiAlertTriangle, FiCircle, FiHelpCircle } from 'react-icons/fi';

const ICONS = {
  online: FiCheckCircle,
  offline: FiXCircle,
  warning: FiAlertTriangle,
  danger: FiAlertTriangle,
  idle: FiCircle,
};

const StatusBadge = ({ status = 'idle', label }) => {
  const Icon = ICONS[status] || FiHelpCircle;
  return (
    <span className={`status-badge status-${status}`}>
      <Icon size={13} aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
};

export default StatusBadge;