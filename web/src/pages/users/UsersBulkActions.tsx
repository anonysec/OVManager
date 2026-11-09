import { useTranslation } from 'react-i18next';
import { FiTrash2, FiX } from 'react-icons/fi';

export default function UsersBulkActions({ count, onDelete, onClear }: any) {
  const { t: tt } = useTranslation();
  if (!count) return null;
  return (
    <div className="um-bulk" role="toolbar" aria-label={tt('bulkActions', 'Bulk actions')}>
      <span>{tt('selectedCount', '{{n}} selected', { n: count })}</span>
      <button type="button" className="ui-btn ui-btn-danger" onClick={onDelete}><FiTrash2 size={15} /> {tt('deleteSelected', 'Delete')}</button>
      <button type="button" className="ui-btn" onClick={onClear} aria-label={tt('clearSelection', 'Clear selection')}><FiX size={15} /></button>
    </div>
  );
}
