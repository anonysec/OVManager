import { FiEdit2, FiTrash2 } from 'react-icons/fi';

export default function UserRowActions({ user, keepOneUser, onEdit, onDelete, t }: any) {
  return (
    <>
      <button type="button" className="dt-icon-btn" title={t('rowEdit', 'Edit')} aria-label={`${t('rowEdit', 'Edit')} ${user.name}`} onClick={() => onEdit(user)}><FiEdit2 size={15} /></button>
      <button type="button" className="dt-icon-btn is-danger" title={keepOneUser ? t('keepOneUser', 'You must keep at least one user') : t('rowDelete', 'Delete')} aria-label={`${t('rowDelete', 'Delete')} ${user.name}`} disabled={keepOneUser} onClick={() => onDelete(user)}><FiTrash2 size={15} /></button>
    </>
  );
}
