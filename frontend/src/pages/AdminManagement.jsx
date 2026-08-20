import { useEffect, useMemo, useState, useCallback } from 'react';
import { FiUserCheck, FiUsers, FiSearch } from 'react-icons/fi';
import apiClient from '../services/api';
import AddAdminModal from '../components/AddAdminModal';
import EditAdminModal from '../components/EditAdminModal';
import AdminTable from '../components/AdminTable';
import { useTranslation } from 'react-i18next';
import { useToast } from '../context/ToastContext';
import ConfirmModal from '../components/ConfirmModal';


const AdminManagement = () => {
    const { addToast } = useToast();
    const [admins, setAdmins] = useState([]);
    const [isAddModalOpen, setIsAddModalOpen] = useState(false);
    const [confirm, setConfirm] = useState({ open: false, title: '', message: '', onConfirm: null });
    const openConfirm = (title, message, onConfirm) => setConfirm({ open: true, title, message, onConfirm });
    const closeConfirm = () => setConfirm(c => ({ ...c, open: false }));
    const [isEditModalOpen, setIsEditModalOpen] = useState(false);
    const [selectedAdmin, setSelectedAdmin] = useState(null);
    const [isLoading, setIsLoading] = useState(false);
    const { t } = useTranslation();

    const [searchTerm, setSearchTerm] = useState('');

    const fetchAdmins = useCallback(async () => {
        setIsLoading(true);
        try {
            const response = await apiClient.get('/admin/');
            if (response.data.success) {
                setAdmins(response.data.data || []);
            }
        } catch (error) {
            console.error('Error fetching admins:', error);
        } finally {
            setIsLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchAdmins();
    }, [fetchAdmins]);

    const adminStats = useMemo(() => {
        return {
            total: admins.length,
        };
    }, [admins]);

    const filteredAdmins = useMemo(() => {
        return admins.filter(admin =>
            admin.username.toLowerCase().includes(searchTerm.toLowerCase())
        );
    }, [admins, searchTerm]);

    const handleSearchChange = (event) => {
        setSearchTerm(event.target.value);
    };

    const handleAdminCreated = () => {
        setIsAddModalOpen(false);
        addToast('Admin created successfully.', 'success');
        fetchAdmins();
    };

    const handleOpenEditModal = (admin) => {
        setSelectedAdmin(admin);
        setIsEditModalOpen(true);
    };

    const handleAdminUpdated = () => {
        setIsEditModalOpen(false);
        setSelectedAdmin(null);
        addToast('Admin updated successfully.', 'success');
        fetchAdmins();
    };

    const handleDelete = (admin) => {
        openConfirm(
            t('deleteAdminConfirm', 'Delete Admin'),
            `Delete admin "${admin.username}"? Their users will remain but become unassigned.`,
            async () => {
                try {
                    const response = await apiClient.delete(`/admin/${admin.username}`);
                    if (response.data.success) {
                        addToast(t('adminDeletedSuccess', 'Admin deleted.'), 'success');
                        fetchAdmins();
                    } else {
                        addToast(response.data.msg || t('unableToDeleteAdmin'), 'error');
                    }
                } catch {
                    addToast(t('errorDeletingAdmin'), 'error');
                }
            }
        );
    };

    return (
        <div id="admins-view" className="view">
            <div className="view-header">
                <h2>{t('admins')}</h2>
                <button onClick={() => setIsAddModalOpen(true)} className="btn">
                    {t('addNewAdmin')}
                </button>
            </div>

            <div className="user-stats-row">
                <div className="user-stat" style={{ '--us-accent': '#90caf9' }}>
                  <span className="us-ico"><FiUsers /></span>
                  <span className="us-body">
                    <span className="us-label">{t('adminsTotal')}</span>
                    <span className="us-value">{adminStats.total}</span>
                  </span>
                </div>
            </div>

            <div className="search-pagination-controls">
                <div className="search-container">
                    <FiSearch className="search-icon" />
                    <input
                        type="text"
                        placeholder={t('searchByUsername')}
                        value={searchTerm}
                        onChange={handleSearchChange}
                        className="search-input"
                    />
                </div>
            </div>

            <AdminTable
                admins={filteredAdmins}
                isLoading={isLoading}
                onEdit={handleOpenEditModal}
                onDelete={handleDelete}
            />

            {isAddModalOpen && (
                <AddAdminModal
                    isOpen={isAddModalOpen}
                    onClose={() => setIsAddModalOpen(false)}
                    onAdminCreated={handleAdminCreated}
                />
            )}

            {isEditModalOpen && (
                <EditAdminModal
                    isOpen={isEditModalOpen}
                    admin={selectedAdmin}
                    onClose={() => setIsEditModalOpen(false)}
                    onAdminUpdated={handleAdminUpdated}
                />
            )}
      <ConfirmModal open={confirm.open} onClose={closeConfirm} onConfirm={confirm.onConfirm || (() => {})} title={confirm.title} message={confirm.message} danger={true} confirmLabel={t("deleteButton","Delete")} cancelLabel={t("cancelButton","Cancel")} />
        </div>
    );
};

export default AdminManagement;
