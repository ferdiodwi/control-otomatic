// static/js/gallery.js
document.addEventListener('DOMContentLoaded', function() {
    const mediaGrid = document.getElementById('media-grid');
    const loader = document.getElementById('loader');
    let currentPage = 1;
    let isLoading = false;
    let allMediaLoaded = false;

    // --- Logika Modal Konfirmasi Hapus ---
    let deleteMediaType = '';
    let deleteMediaId = '';

    const deleteModal = document.getElementById('deleteModal');
    const confirmDeleteBtn = document.getElementById('confirmDeleteBtn');
    const cancelDeleteBtn = document.getElementById('cancelDeleteBtn');
    const closeDeleteModalBtn = document.getElementById('closeDeleteModal');

    window.showDeleteModal = (type, id, filename) => {
        deleteMediaType = type;
        deleteMediaId = id;
        document.getElementById('deleteMessage').textContent = `Apakah Anda yakin ingin menghapus ${type} "${filename}" (ID: ${id}) secara permanen? Aksi ini tidak bisa dibatalkan.`;
        deleteModal.classList.remove('hidden');
    }

    const hideDeleteModal = () => {
        deleteModal.classList.add('hidden');
    }

    // --- Logika Modal Informasi ---
    const infoModal = document.getElementById('infoModal');
    const infoModalTitle = document.getElementById('infoModalTitle');
    const infoMessage = document.getElementById('infoMessage');
    const infoModalOkBtn = document.getElementById('infoModalOkBtn');
    const closeInfoModalBtn = document.getElementById('closeInfoModal');

    const showInfoModal = (message, title = 'Informasi', type = 'info') => {
        infoModalTitle.textContent = title;
        infoMessage.textContent = message;
        infoModalTitle.className = 'modal-header '; // Reset class
        infoModalTitle.classList.add(`modal-title-${type}`);
        infoModal.classList.remove('hidden');
    };
    const hideInfoModal = () => {
        infoModal.classList.add('hidden');
    };

    // --- Event Listeners untuk Semua Modal ---
    cancelDeleteBtn.addEventListener('click', hideDeleteModal);
    closeDeleteModalBtn.addEventListener('click', hideDeleteModal);
    infoModalOkBtn.addEventListener('click', hideInfoModal);
    closeInfoModalBtn.addEventListener('click', hideInfoModal);

    confirmDeleteBtn.addEventListener('click', async () => {
        if (!deleteMediaType || !deleteMediaId) return;

        confirmDeleteBtn.innerHTML = '<span>⏳</span> Menghapus...';
        confirmDeleteBtn.disabled = true;

        try {
            const response = await fetch(`/api/delete_media/${deleteMediaType}/${deleteMediaId}`, { method: 'DELETE' });
            const result = await response.json();

            if (response.ok) {
                showInfoModal(result.message, 'Sukses', 'success');
                document.getElementById(`media-item-${deleteMediaType}-${deleteMediaId}`).remove();

                // Cek jika galeri menjadi kosong setelah penghapusan
                if (mediaGrid.childElementCount === 0 && allMediaLoaded) {
                     mediaGrid.innerHTML = `<div class="empty-state" style="grid-column: 1 / -1;">
                        <div class="empty-state-icon">📷</div>
                        <h3>Belum Ada Media</h3>
                        <p>Galeri Anda sekarang kosong. Mulai kirim stream dari client.</p>
                    </div>`;
                    loader.style.display = 'none';
                }
            } else {
                showInfoModal(result.message || 'Gagal menghapus media.', 'Gagal', 'danger');
            }
        } catch (error) {
            console.error('Delete error:', error);
            showInfoModal('Terjadi kesalahan saat menghubungi server.', 'Error', 'danger');
        } finally {
            hideDeleteModal();
            confirmDeleteBtn.innerHTML = 'Hapus Permanen';
            confirmDeleteBtn.disabled = false;
        }
    });

    // --- Logika Memuat Media ---
    const createMediaCard = (item) => {
        const isImage = item.type === 'image';
        const thumbnailUrl = isImage && item.thumbnail_b64 ? `data:image/jpeg;base64,${item.thumbnail_b64}` : '';
        const actionButton = isImage
            ? `<a href="/annotate/${item.id}" class="btn btn-primary btn-sm"><span>🏷️</span> Lihat Anotasi</a>`
            : `<a href="/videos/${item.filename}" target="_blank" class="btn btn-primary btn-sm"><span>▶️</span> Buka Video</a>`;

        // Menggunakan item.filename yang sekarang sudah konsisten dari backend
        const cardHtml = `
            <div class="media-item" data-type="${item.type}" data-date="${item.timestamp}" data-filename="${item.filename}" id="media-item-${item.type}-${item.id}">
                <div class="media-preview">
                    <div class="media-type-badge ${isImage ? 'image' : 'video'}">${isImage ? 'GAMBAR' : 'VIDEO'}</div>
                    ${isImage 
                        ? `<img src="${thumbnailUrl}" alt="Thumbnail untuk ${item.filename}" loading="lazy">`
                        : `<video muted preload="metadata" title="Pratinjau untuk ${item.filename}"><source src="/videos/${item.filename}#t=0.5" type="video/mp4"></video>`
                    }
                </div>
                <div class="media-info">
                    <p class="media-filename">${item.filename}</p>
                    <div class="media-meta">
                        <span class="media-id">ID: ${item.id}</span>
                        <span class="media-date">${item.timestamp_str || new Date(item.timestamp).toLocaleString('id-ID')}</span>
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
        return cardHtml;
    };

    const loadMedia = async () => {
        if (isLoading || allMediaLoaded) return;
        isLoading = true;
        loader.style.display = 'block';

        try {
            const response = await fetch(`/api/gallery_media?page=${currentPage}`);
            const mediaItems = await response.json();

            if (response.ok) {
                if (mediaItems.length > 0) {
                    mediaItems.forEach(item => {
                        mediaGrid.insertAdjacentHTML('beforeend', createMediaCard(item));
                    });
                    currentPage++;
                } else {
                    allMediaLoaded = true;
                    if (currentPage === 1) { // Jika tidak ada media sama sekali
                         mediaGrid.innerHTML = `<div class="empty-state" style="grid-column: 1 / -1;">
                            <div class="empty-state-icon">📷</div>
                            <h3>Belum Ada Media</h3>
                            <p>Galeri Anda masih kosong. Mulai kirim stream dari client.</p>
                        </div>`;
                        loader.style.display = 'none';
                    } else {
                        loader.innerHTML = '<p>Semua media telah dimuat.</p>';
                    }
                }
            } else {
                 loader.innerHTML = `<p style="color:var(--danger-color);">Gagal memuat media: ${mediaItems.error || 'Kesalahan server'}</p>`;
            }
        } catch (error) {
            console.error('Failed to load media:', error);
            loader.innerHTML = '<p style="color:var(--danger-color);">Gagal memuat media. Periksa koneksi dan coba lagi.</p>';
        } finally {
            isLoading = false;
            if (!allMediaLoaded) {
                loader.style.display = 'none';
            }
        }
    };

    // Pemuatan awal
    loadMedia();

    // Infinite scroll
    window.addEventListener('scroll', () => {
        if ((window.innerHeight + window.scrollY) >= document.body.offsetHeight - 500) {
            loadMedia();
        }
    });
});