// static/js/annotate.js
document.addEventListener('DOMContentLoaded', () => {
    const image = document.getElementById('bg-image');
    const canvas = document.getElementById('image-canvas');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const saveBtn = document.getElementById('save-btn');
    const deleteAllBtn = document.getElementById('delete-all-btn');
    const classIdInput = document.getElementById('class-id');
    const annotationsList = document.getElementById('annotations-ul');
    const statusMsg = document.getElementById('status-msg');
    
    const IMAGE_ID = window.IMAGE_ID;
    let existingAnnotations = window.EXISTING_ANNOTATIONS;

    // --- Logika Modal Konfirmasi ---
    const confirmModal = document.getElementById('confirmModal');
    const confirmMessage = document.getElementById('confirmMessage');
    const confirmModalYesBtn = document.getElementById('confirmModalYesBtn');
    const confirmModalNoBtn = document.getElementById('confirmModalNoBtn');
    const closeConfirmModalBtn = document.getElementById('closeConfirmModal');
    let onConfirmAction = null; // Store the function to run on confirmation

    function showConfirmModal(message, onConfirm) {
        confirmMessage.textContent = message;
        onConfirmAction = onConfirm;
        confirmModal.classList.remove('hidden');
    }

    function hideConfirmModal() {
        confirmModal.classList.add('hidden');
        onConfirmAction = null;
    }
    
    confirmModalNoBtn.addEventListener('click', hideConfirmModal);
    closeConfirmModalBtn.addEventListener('click', hideConfirmModal);
    confirmModalYesBtn.addEventListener('click', () => {
        if (typeof onConfirmAction === 'function') {
            onConfirmAction();
        }
        hideConfirmModal();
    });
    // --- End Logika Modal ---

    let isDrawing = false;
    let startX, startY;
    let currentRect = null;

    function showStatus(message, type = 'info', duration = 3000) {
        statusMsg.textContent = message;
        statusMsg.className = `visible ${type}`;
        if (duration > 0) {
            setTimeout(() => {
                statusMsg.className = '';
            }, duration);
        }
    }

    function redrawAllAnnotations() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        existingAnnotations.forEach(ann => {
            ctx.strokeStyle = '#ef4444'; ctx.lineWidth = 3;
            ctx.strokeRect(ann.bbox_x, ann.bbox_y, ann.bbox_width, ann.bbox_height);
            ctx.fillStyle = 'rgba(15, 23, 42, 0.7)'; ctx.font = 'bold 16px Inter, sans-serif';
            const label = `ID:${ann.class_id}`;
            const textWidth = ctx.measureText(label).width;
            ctx.fillRect(ann.bbox_x, ann.bbox_y - 24, textWidth + 12, 24);
            ctx.fillStyle = 'white';
            ctx.fillText(label, ann.bbox_x + 6, ann.bbox_y - 6);
        });
    }

    function updateAnnotationList() {
        annotationsList.innerHTML = '';
        if (existingAnnotations.length === 0) {
            annotationsList.innerHTML = '<li class="annotation-item"><span>Belum ada anotasi.</span></li>';
            return;
        }
        existingAnnotations.forEach((ann, index) => {
            const li = document.createElement('li');
            li.className = 'annotation-item';
            const bbox_x = Math.round(ann.bbox_x); const bbox_y = Math.round(ann.bbox_y);
            const bbox_width = Math.round(ann.bbox_width); const bbox_height = Math.round(ann.bbox_height);
            const textNode = document.createElement('span');
            textNode.textContent = `Class ${ann.class_id}: [${bbox_width} x ${bbox_height}]`;
            const deleteBtn = document.createElement('button');
            deleteBtn.innerHTML = '<span>🗑️</span> Hapus';
            deleteBtn.className = 'btn btn-danger btn-sm';
            deleteBtn.dataset.id = ann.id; deleteBtn.dataset.index = index;
            li.appendChild(textNode); li.appendChild(deleteBtn);
            annotationsList.appendChild(li);
        });
    }

    image.onload = () => {
        canvas.width = image.width; canvas.height = image.height;
        redrawAllAnnotations(); updateAnnotationList();
    };
    if (image.complete) { image.onload(); }

    canvas.addEventListener('mousedown', (e) => { isDrawing = true; startX = e.offsetX; startY = e.offsetY; });
    canvas.addEventListener('mousemove', (e) => {
        if (!isDrawing) return; redrawAllAnnotations();
        const currentX = e.offsetX; const currentY = e.offsetY;
        const width = currentX - startX; const height = currentY - startY;
        ctx.strokeStyle = '#34d399'; ctx.lineWidth = 3; ctx.setLineDash([6, 3]);
        ctx.strokeRect(startX, startY, width, height); ctx.setLineDash([]);
    });
    canvas.addEventListener('mouseup', (e) => {
        if (!isDrawing) return; isDrawing = false; const endX = e.offsetX; const endY = e.offsetY;
        currentRect = { x: Math.min(startX, endX), y: Math.min(startY, endY), width: Math.abs(endX - startX), height: Math.abs(endY - startY) };
        if (currentRect.width < 5 || currentRect.height < 5) { currentRect = null; redrawAllAnnotations(); return; }
        showStatus('Kotak digambar! Klik "Simpan Anotasi" untuk menyimpan.', 'info', 4000);
    });

    saveBtn.addEventListener('click', async () => {
        if (!currentRect) { showStatus('Silakan gambar kotak anotasi terlebih dahulu!', 'error'); return; }
        const classId = classIdInput.value;
        if (classId === '' || isNaN(parseInt(classId))) { showStatus('Class ID tidak valid!', 'error'); return; }
        showStatus('Menyimpan...', 'info', 0); saveBtn.disabled = true;
        try {
            const response = await fetch('/api/save_annotation', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image_id: IMAGE_ID, class_id: parseInt(classId), bbox: currentRect }) });
            const result = await response.json();
            if (result.status === 'success' && result.new_annotation) {
                showStatus('Berhasil disimpan!', 'success'); existingAnnotations.push(result.new_annotation);
                currentRect = null; redrawAllAnnotations(); updateAnnotationList();
            } else { showStatus(`Error: ${result.message}`, 'error'); }
        } catch (error) { showStatus('Error koneksi.', 'error'); console.error('Save error:', error); } finally { saveBtn.disabled = false; }
    });

    deleteAllBtn.addEventListener('click', () => {
        const action = async () => {
            showStatus('Menghapus semua anotasi...', 'info', 0);
            deleteAllBtn.disabled = true;
            try {
                const response = await fetch(`/api/delete_annotations_for_image/${IMAGE_ID}`, { method: 'DELETE' });
                const result = await response.json();
                if (result.status === 'success') {
                    showStatus('Semua anotasi berhasil dihapus!', 'success');
                    existingAnnotations = [];
                    redrawAllAnnotations();
                    updateAnnotationList();
                } else {
                    showStatus(`Error: ${result.message}`, 'error');
                }
            } catch (error) {
                showStatus('Error koneksi saat menghapus.', 'error');
                console.error('Delete all error:', error);
            } finally {
                deleteAllBtn.disabled = false;
            }
        };
        showConfirmModal('Apakah Anda yakin ingin menghapus SEMUA anotasi untuk gambar ini?', action);
    });

    annotationsList.addEventListener('click', (e) => {
        const button = e.target.closest('.btn-danger');
        if (!button) return;
        const annotationId = button.dataset.id;
        const arrayIndex = parseInt(button.dataset.index, 10);
        
        const action = async () => {
            showStatus('Menghapus anotasi...', 'info', 0);
            button.disabled = true;
            try {
                const response = await fetch(`/api/delete_annotation/${annotationId}`, { method: 'DELETE' });
                const result = await response.json();
                if (result.status === 'success') {
                    showStatus('Anotasi berhasil dihapus!', 'success');
                    existingAnnotations.splice(arrayIndex, 1);
                    redrawAllAnnotations();
                    updateAnnotationList();
                } else {
                    showStatus(`Error: ${result.message}`, 'error');
                    button.disabled = false;
                }
            } catch (error) {
                showStatus('Error koneksi saat menghapus.', 'error');
                console.error('Delete error:', error);
                button.disabled = false;
            }
        };
        showConfirmModal(`Apakah Anda yakin ingin menghapus anotasi ini (ID: ${annotationId})?`, action);
    });
});