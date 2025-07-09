// static/js/data_cleaning.js
document.addEventListener('DOMContentLoaded', () => {
    let currentTab = 'unannotated';
    let currentPage = { unannotated: 1, annotated: 1 };
    let isLoading = { unannotated: false, annotated: false };
    let allLoaded = { unannotated: false, annotated: false };

    const tabs = document.querySelectorAll('.tab-button');
    const sortSelect = document.getElementById('sort-order-select');

    // --- Logika Modal Konfirmasi Hapus ---
    const deleteModal = document.getElementById('deleteModal');
    const confirmDeleteBtn = document.getElementById('confirmDeleteBtn');
    const cancelDeleteBtn = document.getElementById('cancelDeleteBtn');
    const closeDeleteModalBtn = document.getElementById('closeDeleteModal');
    const deleteMessage = document.getElementById('deleteMessage');

    let deletionContext = {
        type: null,
        mediaType: 'image',
        ids: []
    };

    const showDeleteModal = (message) => {
        deleteMessage.textContent = message;
        deleteModal.classList.remove('hidden');
    };
    const hideDeleteModal = () => {
        deleteModal.classList.add('hidden');
    };
    // --- End Logika Modal Konfirmasi ---

    // --- Logika Modal Informasi ---
    const infoModal = document.getElementById('infoModal');
    const infoModalTitle = document.getElementById('infoModalTitle');
    const infoMessage = document.getElementById('infoMessage');
    const infoModalOkBtn = document.getElementById('infoModalOkBtn');
    const closeInfoModalBtn = document.getElementById('closeInfoModal');
    
    const showInfoModal = (message, title = 'Informasi', type = 'info') => {
        infoModalTitle.textContent = title;
        infoMessage.textContent = message;
        infoModalTitle.className = ''; // Reset class
        infoModalTitle.classList.add(`modal-title-${type}`);
        infoModal.classList.remove('hidden');
    };
    const hideInfoModal = () => {
        infoModal.classList.add('hidden');
    };
    // --- End Logika Modal Informasi ---


    const openTab = (tabName) => {
        document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
        document.querySelectorAll('.tab-button').forEach(tb => tb.classList.remove('active'));
        document.getElementById(tabName).classList.add('active');
        document.querySelector(`.tab-button[data-tab='${tabName}']`).classList.add('active');
        currentTab = tabName;
        if (document.querySelector(`#${tabName}-table tbody`).childElementCount === 0) {
            loadDataForCurrentTab(true);
        }
    }

    tabs.forEach(tab => tab.addEventListener('click', (event) => openTab(event.currentTarget.dataset.tab)));

    const createTableRow = (item, context) => {
        const displayDate = new Date(item.created_at).toLocaleString('id-ID', { day: '2-digit', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' });
        const annotateUrl = `/annotate/${item.id}?context=${context}`;
        const actionButtonText = context === 'unannotated' ? 'Anotasi' : 'Edit';
        const actionButtonIcon = context === 'unannotated' ? '✏️' : '🔍';
        const thumbnailSrc = item.thumbnail_b64 ? `data:image/jpeg;base64,${item.thumbnail_b64}` : '';

        const row = document.createElement('tr');
        row.id = `media-row-image-${item.id}`;
        row.innerHTML = `
            <td class="checkbox-col"><input type="checkbox" class="row-checkbox" value="${item.id}"></td>
            <td>${item.id}</td>
            <td class="preview-col"><a href="${annotateUrl}" title="Klik untuk anotasi/edit"><img src="${thumbnailSrc}" alt="Thumbnail ${item.id}" loading="lazy"></a></td>
            <td>${displayDate}</td>
            <td style="text-align: center;"><div class="action-buttons">
                <a href="${annotateUrl}" class="btn btn-sm btn-primary">${actionButtonIcon} ${actionButtonText}</a>
                <button class="btn btn-sm btn-danger btn-delete-single" data-type="image" data-id="${item.id}">🗑️ Hapus</button>
            </div></td>`;
        return row;
    }

    const loadDataForCurrentTab = async (reset = false) => {
        if (isLoading[currentTab] || (!reset && allLoaded[currentTab])) return;
        isLoading[currentTab] = true;
        const tableBody = document.querySelector(`#${currentTab}-table tbody`);
        if (reset) {
            currentPage[currentTab] = 1;
            allLoaded[currentTab] = false;
            tableBody.innerHTML = '';
        }
        const loader = document.getElementById(`${currentTab}-loader`);
        loader.style.display = 'block';
        const sortOrder = sortSelect.value;
        const url = `/api/data_by_status?status=${currentTab}&sort_order=${sortOrder}&page=${currentPage[currentTab]}`;
        try {
            const response = await fetch(url);
            const data = await response.json();
            if (data.length > 0) {
                data.forEach(item => tableBody.appendChild(createTableRow(item, currentTab)));
                currentPage[currentTab]++;
            } else {
                allLoaded[currentTab] = true;
                if (reset && tableBody.childElementCount === 0) {
                    const colCount = document.querySelectorAll(`#${currentTab}-table thead th`).length;
                    tableBody.innerHTML = `<tr><td colspan="${colCount}"><div class="empty-state">Tidak ada data untuk ditampilkan.</div></td></tr>`;
                }
            }
        } catch (error) {
            console.error("Gagal mengambil data:", error);
            showInfoModal("Gagal mengambil data dari server.", "Error", "danger");
        } finally {
            isLoading[currentTab] = false;
            loader.style.display = 'none';
        }
    }

    const handleSortChange = () => {
        loadDataForCurrentTab(true);
        const otherTab = currentTab === 'unannotated' ? 'annotated' : 'unannotated';
        currentPage[otherTab] = 1;
        allLoaded[otherTab] = false;
        document.querySelector(`#${otherTab}-table tbody`).innerHTML = '';
    }

    sortSelect.addEventListener('change', handleSortChange);
    loadDataForCurrentTab(true);

    document.querySelector('.card').addEventListener('click', (e) => {
        const singleDeleteBtn = e.target.closest('.btn-delete-single');
        const bulkDeleteBtn = e.target.closest('.btn-delete-selected');
        const selectAllCheckbox = e.target.closest('.select-all-checkbox');

        if (singleDeleteBtn) {
            const type = singleDeleteBtn.dataset.type;
            const id = parseInt(singleDeleteBtn.dataset.id);
            deletionContext = { type: 'single', mediaType: type, ids: [id] };
            showDeleteModal(`Apakah Anda yakin ingin menghapus ${type} ID: ${id} secara permanen? Aksi ini tidak bisa dibatalkan.`);
        } else if (bulkDeleteBtn) {
            const tableId = bulkDeleteBtn.closest('.tab-content').id + '-table';
            const checkboxes = document.querySelectorAll(`#${tableId} .row-checkbox:checked`);
            const idsToDelete = Array.from(checkboxes).map(cb => parseInt(cb.value));
            if (idsToDelete.length === 0) {
                showInfoModal("Tidak ada item yang dipilih.", "Perhatian", "info");
                return;
            }
            deletionContext = { type: 'bulk', mediaType: 'image', ids: idsToDelete };
            showDeleteModal(`Apakah Anda yakin ingin menghapus ${idsToDelete.length} item terpilih secara permanen? Aksi ini tidak bisa dibatalkan.`);
        } else if (selectAllCheckbox) {
            toggleAll(selectAllCheckbox, selectAllCheckbox.dataset.table);
        }
    });
    
    // Event Listeners untuk semua modal
    cancelDeleteBtn.addEventListener('click', hideDeleteModal);
    closeDeleteModalBtn.addEventListener('click', hideDeleteModal);
    infoModalOkBtn.addEventListener('click', hideInfoModal);
    closeInfoModalBtn.addEventListener('click', hideInfoModal);

    confirmDeleteBtn.addEventListener('click', async () => {
        if (!deletionContext.type || deletionContext.ids.length === 0) return;
        confirmDeleteBtn.innerHTML = '<span>⏳</span> Menghapus...';
        confirmDeleteBtn.disabled = true;

        try {
            let response;
            if (deletionContext.type === 'single') {
                const id = deletionContext.ids[0];
                const type = deletionContext.mediaType;
                response = await fetch(`/api/delete_media/${type}/${id}`, { method: 'DELETE' });
            } else if (deletionContext.type === 'bulk') {
                response = await fetch('/api/delete_media_bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ media_type: deletionContext.mediaType, ids: deletionContext.ids })
                });
            }
            const result = await response.json();
            if (result.status === 'success') {
                showInfoModal(result.message, 'Sukses', 'success');
                if (deletionContext.type === 'single') {
                     const row = document.getElementById(`media-row-${deletionContext.mediaType}-${deletionContext.ids[0]}`);
                     if (row) row.remove();
                } else {
                     handleSortChange();
                }
            } else {
                showInfoModal(result.message, 'Gagal', 'danger');
            }
        } catch (error) {
            console.error('Error:', error);
            showInfoModal('Terjadi kesalahan saat menghubungi server.', 'Error', 'danger');
        } finally {
            hideDeleteModal();
            confirmDeleteBtn.innerHTML = 'Hapus Permanen';
            confirmDeleteBtn.disabled = false;
            deletionContext = { type: null, mediaType: 'image', ids: [] };
        }
    });

    const toggleAll = (source, tableId) => {
        document.querySelectorAll(`#${tableId} .row-checkbox`).forEach(checkbox => checkbox.checked = source.checked);
    }
});