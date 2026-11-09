import { FiSearch, FiPlus } from 'react-icons/fi';

export default function UsersFilters({ search, onSearch, onAdd, t }: any) {
  return (
    <div className="um-toolbar">
      <div className="um-search">
        <FiSearch size={16} aria-hidden="true" />
        <input type="search" value={search} onChange={(e) => onSearch(e.target.value)} placeholder={t('searchUsers', 'Search users')} aria-label={t('searchUsers', 'Search users')} data-testid="user-search" />
      </div>
      <button type="button" className="ui-btn ui-btn-primary" onClick={onAdd} data-testid="add-user"><FiPlus size={16} /> {t('addUser', 'Add user')}</button>
    </div>
  );
}
