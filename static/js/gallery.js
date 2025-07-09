// static/js/gallery.js
document.addEventListener('DOMContentLoaded', function() {
    const galleryContainer = document.getElementById('gallery-container');
    const toggleSelectionBtn = document.getElementById('toggle-selection-btn');
    const deleteSelectedBtn = document.getElementById('delete-selected-btn');
    const selectAllCheckbox = document.getElementById('select-all-checkbox');
    const selectionCounter = document.getElementById('selection-counter');

    // --- State Management (Sudah Termasuk video_annotated) ---
    const state = {
        images: {
            grid: document.getElementById('image-grid'),
            loader: document.getElementById('image-loader'),
            content: document.getElementById('images-content'),
            page: 1,
            isLoading: false,
            allLoaded: false,
        },
        images_annotated: {
            grid: document.getElementById('image-annotated-grid'),
            loader: document.getElementById('image-annotated-loader'),
            content: document.getElementById('images-annotated-content'),
            page: 1,
            isLoading: false,
            allLoaded: false,
        },
        videos: {
            grid: document.getElementById('video-grid'),
            loader: document.getElementById('video-loader'),
            content: document.getElementById('videos-content'),
            page: 1,
            isLoading: false,
            allLoaded: false,
        },
        videos_annotated: {
            grid: document.getElementById('video-annotated-grid'),
            loader: document.getElementById('video-annotated-loader'),
            content: document.getElementById('videos-annotated-content'),
            page: 1,
            isLoading: false,
            allLoaded: false,
        },
    };
    let activeTab = 'images';
    let isSelectionMode = false;
    let selectedItems = new Set();

    // --- Variabel dan Fungsi Helper Modal (Tidak Berubah) ---
    let singleDeleteItem = { type: null, id: null };
    const deleteModal = document.getElementById('deleteModal');
    const confirmDeleteBtn = document.getElementById('confirmDeleteBtn');
    const cancelDeleteBtn = document.getElementById('cancelDeleteBtn');
    const closeDeleteModalBtn = document.getElementById('closeDeleteModal');
    const infoModal = document.getElementById('infoModal');
    const infoModalTitle = document.getElementById('infoModalTitle');
    const infoMessage = document.getElementById('infoMessage');
    const infoModalOkBtn = document.getElementById('infoModalOkBtn');
    const closeInfoModalBtn = document.getElementById('closeInfoModal');

    window.showDeleteModal = (type, id, filename) => {
        singleDeleteItem = { type, id };
        selectedItems.clear();
        document.getElementById('deleteMessage').textContent = `Apakah Anda yakin ingin menghapus ${type.replace(/_/g, ' ')} "${filename}" (ID: ${id}) secara permanen? Aksi ini tidak bisa dibatalkan.`;
        deleteModal.classList.remove('hidden');
    };
    const hideDeleteModal = () => deleteModal.classList.add('hidden');
    const showInfoModal = (message, title = 'Informasi', type = 'info') => {
        infoModalTitle.textContent = title;
        infoMessage.textContent = message;
        infoModalTitle.className = 'modal-header ';
        infoModalTitle.classList.add(`modal-title-${type}`);
        infoModal.classList.remove('hidden');
    };
    const hideInfoModal = () => infoModal.classList.add('hidden');

    cancelDeleteBtn.addEventListener('click', hideDeleteModal);
    closeDeleteModalBtn.addEventListener('click', hideDeleteModal);
    infoModalOkBtn.addEventListener('click', hideInfoModal);
    closeInfoModalBtn.addEventListener('click', hideInfoModal);

    // --- Logika Mode Seleksi (Tidak Berubah) ---
    function toggleSelectionMode(enable) {
        isSelectionMode = typeof enable === 'boolean' ? enable : !isSelectionMode;
        galleryContainer.classList.toggle('selection-mode', isSelectionMode);

        if (isSelectionMode) {
            toggleSelectionBtn.textContent = 'Batal';
            toggleSelectionBtn.classList.add('btn-secondary');
        } else {
            toggleSelectionBtn.textContent = 'Pilih';
            toggleSelectionBtn.classList.remove('btn-secondary');
            selectedItems.clear();
            document.querySelectorAll('.media-item.selected').forEach(el => el.classList.remove('selected'));
            document.querySelectorAll('.media-item-checkbox').forEach(cb => cb.checked = false);
            selectAllCheckbox.checked = false;
        }
        updateSelectionUI();
    }

    function updateSelectionUI() {
        const count = selectedItems.size;
        selectionCounter.textContent = `${count} dipilih`;
        deleteSelectedBtn.disabled = count === 0;
        const currentGrid = state[activeTab]?.grid; // Gunakan optional chaining
        if (!currentGrid) return;
        const visibleItems = currentGrid.querySelectorAll('.media-item');
        selectAllCheckbox.checked = visibleItems.length > 0 && count === visibleItems.length;
    }

    // --- Logika Pembuatan Kartu Media (Sudah Termasuk video_annotated) ---
    const createMediaCard = (item) => {
        let badgeText, previewHtml, actionButton, fileUrl, badgeClass;

        if (item.type === 'image') {
            fileUrl = `/images/${item.filename}`;
        } else if (item.type === 'image_annotated') {
            fileUrl = `/images_annotated/${item.filename}`;
        } else if (item.type === 'video') {
            fileUrl = `/videos/${item.filename}`;
        } else if (item.type === 'video_annotated') {
            fileUrl = `/videos_annotated/${item.filename}`;
        }

        if (item.type === 'image') {
            const thumbnailUrl = item.thumbnail_b64 ? `data:image/jpeg;base64,${item.thumbnail_b64}` : fileUrl;
            badgeText = 'GAMBAR MENTAH';
            badgeClass = 'media-type-badge';
            previewHtml = `<img src="${thumbnailUrl}" alt="Thumbnail untuk ${item.filename}" loading="lazy">`;
            actionButton = `<a href="/annotate/${item.id}" class="btn btn-primary btn-sm"><span>✏️</span> Anotasi</a>`;
        } else if (item.type === 'image_annotated') {
            badgeText = 'GAMBAR AI';
            badgeClass = 'media-type-badge annotated';
            previewHtml = `<img src="${fileUrl}" alt="Gambar anotasi ${item.filename}" loading="lazy">`;
            actionButton = `<a href="${fileUrl}" target="_blank" class="btn btn-secondary btn-sm"><span>🖼️</span> Lihat Full</a>`;
        } else if (item.type === 'video') {
            badgeText = 'VIDEO MENTAH';
            badgeClass = 'media-type-badge';
            previewHtml = `<video muted preload="metadata" title="Pratinjau untuk ${item.filename}"><source src="${fileUrl}#t=0.5" type="video/mp4"></video>`;
            actionButton = `<a href="${fileUrl}" target="_blank" class="btn btn-primary btn-sm"><span>▶️</span> Buka Video</a>`;
        } else if (item.type === 'video_annotated') {
            badgeText = 'VIDEO AI';
            badgeClass = 'media-type-badge annotated';
            previewHtml = `<video muted preload="metadata" title="Pratinjau untuk ${item.filename}"><source src="${fileUrl}#t=0.5" type="video/mp4"></video>`;
            actionButton = `<a href="${fileUrl}" target="_blank" class="btn btn-secondary btn-sm"><span>▶️</span> Buka Video</a>`;
        }

        return `
            <div class="media-item" id="media-item-${item.type}-${item.id}" data-id="${item.id}" data-type="${item.type}">
                <input type="checkbox" class="media-item-checkbox" aria-label="Pilih item ini">
                <div class="media-preview">
                    <div class="${badgeClass}">${badgeText}</div>
                    ${previewHtml}
                </div>
                <div class="media-info">
                    <p class="media-filename">${item.filename}</p>
                    <div class="media-meta">
                        <span class="media-id">ID: ${item.id}</span>
                        <span class="media-date">${item.timestamp_str}</span>
                    </div>
                    <div class="media-actions">
                        ${actionButton}
                        <button class="btn btn-danger btn-sm" onclick="showDeleteModal('${item.type}', ${item.id}, '${item.filename}')">
                            <span>🗑️</span> Hapus
                        </button>
                    </div>
                </div>
            </div>
        `;
    };

    // --- Logika Pemuatan Media ---
    const loadMedia = async (type) => {
        const s = state[type];
        if (!s || s.isLoading || s.allLoaded) return;
        s.isLoading = true;
        s.loader.style.display = 'block';
        try {
            // [MODIFIKASI] Endpoint API sekarang konsisten dengan nama state/tab
            const response = await fetch(`/api/gallery_${type}?page=${s.page}`);
            const mediaItems = await response.json();
            if (response.ok) {
                if (mediaItems.length > 0) {
                    mediaItems.forEach(item => s.grid.insertAdjacentHTML('beforeend', createMediaCard(item)));
                    s.page++;
                } else {
                    s.allLoaded = true;
                    if (s.page === 1) {
                        let mediaName, mediaIcon;
                        if (type === 'images') { mediaName = 'Gambar Mentah'; mediaIcon = '🖼️'; }
                        else if (type === 'images_annotated') { mediaName = 'Gambar AI'; mediaIcon = '✨'; }
                        else if (type === 'videos') { mediaName = 'Video Mentah'; mediaIcon = '🎬'; }
                        else { mediaName = 'Video AI'; mediaIcon = '🎥'; }
                        s.grid.innerHTML = `<div class="empty-state"><div class="empty-state-icon">${mediaIcon}</div><h3>Belum Ada ${mediaName}</h3><p>Galeri ${mediaName} Anda masih kosong.</p></div>`;
                    }
                    const readableType = type.replace(/_/g, ' ').replace('images', 'gambar').replace('videos', 'video');
                    s.loader.innerHTML = `<p>Semua ${readableType} telah dimuat.</p>`;
                }
            } else {
                s.loader.innerHTML = `<p style="color:var(--danger-color);">Gagal memuat ${type}: ${mediaItems.error || 'Kesalahan server'}</p>`;
            }
        } catch (error) {
            s.loader.innerHTML = `<p style="color:var(--danger-color);">Gagal memuat ${type}. Periksa koneksi.</p>`;
        } finally {
            s.isLoading = false;
            if (!s.allLoaded) s.loader.style.display = 'none';
        }
    };

    // --- Event Listeners Utama ---
    toggleSelectionBtn.addEventListener('click', () => toggleSelectionMode());

    ['image-grid', 'video-grid', 'image-annotated-grid', 'video-annotated-grid'].forEach(gridId => {
        const gridElement = document.getElementById(gridId);
        if(gridElement) {
            gridElement.addEventListener('click', (e) => {
                if (!isSelectionMode) return;
                const card = e.target.closest('.media-item');
                if (card) {
                    e.preventDefault();
                    const checkbox = card.querySelector('.media-item-checkbox');
                    if (checkbox && e.target !== checkbox) {
                        checkbox.checked = !checkbox.checked;
                        checkbox.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            });
        }
    });

    galleryContainer.addEventListener('change', (e) => {
        if (e.target.classList.contains('media-item-checkbox')) {
            const card = e.target.closest('.media-item');
            const id = card.dataset.id;
            const type = card.dataset.type;
            const uniqueId = `${type}-${id}`;

            if (e.target.checked) {
                selectedItems.add(uniqueId);
                card.classList.add('selected');
            } else {
                selectedItems.delete(uniqueId);
                card.classList.remove('selected');
            }
            updateSelectionUI();
        }
    });

    selectAllCheckbox.addEventListener('change', (e) => {
        const isChecked = e.target.checked;
        const currentGrid = state[activeTab]?.grid;
        if (!currentGrid) return;
        currentGrid.querySelectorAll('.media-item-checkbox').forEach(checkbox => {
            if (checkbox.checked !== isChecked) {
                checkbox.checked = isChecked;
                checkbox.dispatchEvent(new Event('change', { bubbles: true }));
            }
        });
        updateSelectionUI();
    });

    deleteSelectedBtn.addEventListener('click', () => {
        if (selectedItems.size === 0) return;
        singleDeleteItem = { type: null, id: null };
        document.getElementById('deleteMessage').textContent = `Apakah Anda yakin ingin menghapus ${selectedItems.size} item yang dipilih secara permanen?`;
        deleteModal.classList.remove('hidden');
    });

    // --- [PERBAIKAN] Logika Konfirmasi Hapus ---
    confirmDeleteBtn.addEventListener('click', async () => {
        confirmDeleteBtn.innerHTML = '<span>⏳</span> Menghapus...';
        confirmDeleteBtn.disabled = true;

        try {
            let response;
            // Mode Bulk Delete
            if (selectedItems.size > 0) {
                // [FIX] Peta untuk menerjemahkan nama tab ke tipe media API
                const apiMediaTypeMap = {
                    'images': 'image',
                    'videos': 'video',
                    'images_annotated': 'image_annotated',
                    'videos_annotated': 'video_annotated'
                };

                // [FIX] Gunakan peta untuk mendapatkan tipe media yang benar
                const media_type = apiMediaTypeMap[activeTab];
                if (!media_type) {
                    throw new Error("Tipe media dari tab aktif tidak valid.");
                }

                const ids = Array.from(selectedItems).map(uid => {
                    const parts = uid.split(/-(.+)/);
                    return parseInt(parts[1], 10);
                });

                if (ids.length === 0) throw new Error("Tidak ada ID valid yang bisa diekstrak.");

                response = await fetch('/api/delete_media_bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ media_type: media_type, ids: ids }),
                });

            } else if (singleDeleteItem.id) { // Mode Single Delete
                response = await fetch(`/api/delete_media/${singleDeleteItem.type}/${singleDeleteItem.id}`, { method: 'DELETE' });
            } else {
                throw new Error("Tidak ada item yang dipilih untuk dihapus.");
            }

            const result = await response.json();

            if (response.ok) {
                showInfoModal(result.message, 'Sukses', 'success');
                if (selectedItems.size > 0) {
                    selectedItems.forEach(uid => {
                         const el = document.getElementById(`media-item-${uid}`);
                         if (el) el.remove();
                    });
                    toggleSelectionMode(false);
                } else {
                    const el = document.getElementById(`media-item-${singleDeleteItem.type}-${singleDeleteItem.id}`);
                    if (el) el.remove();
                }
            } else {
                // [FIX] Menampilkan pesan error dari server
                showInfoModal(result.message || 'Gagal menghapus media.', 'Gagal', 'danger');
            }
        } catch (error) {
            console.error("Delete error:", error);
            showInfoModal('Terjadi kesalahan saat menghubungi server.', 'Error', 'danger');
        } finally {
            hideDeleteModal();
            confirmDeleteBtn.innerHTML = 'Hapus Permanen';
            confirmDeleteBtn.disabled = false;
            selectedItems.clear();
            singleDeleteItem = { type: null, id: null };
            updateSelectionUI();
        }
    });

    // --- Logika Pergantian Tab ---
    const tabs = document.querySelectorAll('.tab-link');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            if (isSelectionMode) toggleSelectionMode(false);

            const tabName = tab.dataset.tab;
            if (tabName === activeTab) return;
            activeTab = tabName;

            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            Object.values(state).forEach(s => {
                if(s && s.content) s.content.classList.remove('active');
            });

            if (state[activeTab] && state[activeTab].content) {
                state[activeTab].content.classList.add('active');
                if (state[activeTab].page === 1 && state[activeTab].grid.childElementCount === 0) {
                    loadMedia(activeTab);
                }
            }
            updateSelectionUI();
        });
    });

    // --- Infinite Scroll ---
    window.addEventListener('scroll', () => {
        if ((window.innerHeight + window.scrollY) >= document.body.offsetHeight - 500) {
            loadMedia(activeTab);
        }
    });

    // --- Pemuatan Awal ---
    loadMedia('images');
});