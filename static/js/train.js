// static/js/train.js
document.addEventListener('DOMContentLoaded', function() {
    const trainBtn = document.getElementById('start-train-btn');
    if (!trainBtn) return;

    const statusBox = document.getElementById('training-status');
    const originalBtnHTML = trainBtn.innerHTML;
    let eventSource = null;

    function stopEventSource() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
    }

    trainBtn.addEventListener('click', function() {
        if (this.disabled) return;

        // [DIUBAH] Mengganti confirm() standar dengan SweetAlert2
        Swal.fire({
            title: 'Konfirmasi Pelatihan',
            text: "Apakah Anda yakin ingin memulai proses pelatihan? Ini akan menggunakan sumber daya server secara intensif.",
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#4CAF50', // Warna hijau yang lebih cocok
            cancelButtonColor: '#F44336', // Warna merah
            confirmButtonText: 'Ya, Mulai Pelatihan!',
            cancelButtonText: 'Batal',
            background: '#2d3748', // Latar belakang gelap
            color: '#e2e8f0' // Teks terang
        }).then((result) => {
            // Hanya lanjutkan jika pengguna mengklik tombol "Confirm"
            if (result.isConfirmed) {
                startTrainingProcess();
            }
        });
    });

    function startTrainingProcess() {
        // 1. Ubah UI untuk menandakan proses dimulai
        trainBtn.disabled = true;
        trainBtn.innerHTML = `<span class="spinner"></span> Memproses...`;
        
        statusBox.classList.remove('waiting');
        statusBox.textContent = '[INFO] Mengirim permintaan pelatihan ke server...\n';
        statusBox.scrollTop = statusBox.scrollHeight;

        // 2. Kirim permintaan untuk memulai pelatihan
        fetch('/api/start_training', {
            method: 'POST',
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => { throw new Error(err.message || `HTTP error! Status: ${response.status}`); });
            }
            return response.json();
        })
        .then(data => {
            if (data.status === 'success') {
                statusBox.textContent += `[SERVER] ${data.message}\n\n`;
                statusBox.scrollTop = statusBox.scrollHeight;
                
                // 3. Jika berhasil, mulai dengarkan event log
                startListeningForLogs();
            } else {
                throw new Error(data.message || 'Gagal memulai pelatihan dari server.');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            statusBox.textContent += `\n[FATAL] Terjadi kesalahan kritis: ${error.message}\n`;
            statusBox.scrollTop = statusBox.scrollHeight;
            resetButton();
            // [BARU] Tampilkan alert error dengan SweetAlert
            Swal.fire({
                title: 'Error!',
                text: error.message,
                icon: 'error',
                background: '#2d3748',
                color: '#e2e8f0'
            });
        });
    }

    function startListeningForLogs() {
        trainBtn.innerHTML = `<span>⏳</span> Pelatihan Berjalan <br> Jangan Tinggalkan Halaman Ini `;
        
        stopEventSource();
        eventSource = new EventSource('/api/training_status');

        eventSource.onopen = function() {
            statusBox.textContent += '[STREAM] Koneksi ke log server berhasil dibuat. Menunggu output...\n';
            statusBox.scrollTop = statusBox.scrollHeight;
        };

        eventSource.onmessage = function(event) {
            statusBox.textContent += event.data;
            statusBox.scrollTop = statusBox.scrollHeight;
        };

        eventSource.addEventListener('complete', function(event) {
            statusBox.textContent += '\n[STREAM] Server menandakan proses selesai. Menutup koneksi.\n';
            statusBox.scrollTop = statusBox.scrollHeight;
            
            // [DIUBAH] Mengganti alert() standar dengan SweetAlert2
            Swal.fire({
                title: 'Berhasil!',
                text: 'Proses pelatihan telah berhasil diselesaikan!',
                icon: 'success',
                background: '#2d3748', // Latar belakang gelap
                color: '#e2e8f0' // Teks terang
            });
            
            trainBtn.innerHTML = `<span>✅</span> Pelatihan Selesai`;
            trainBtn.disabled = false;
            
            stopEventSource();
        });

        eventSource.onerror = function(err) {
            console.error('EventSource failed:', err);
            statusBox.textContent += '\n[STREAM_ERROR] Koneksi ke log server terputus. Proses mungkin masih berjalan di latar belakang.\n';
            statusBox.scrollTop = statusBox.scrollHeight;
            resetButton();
            stopEventSource();
        };
    }

    function resetButton() {
        trainBtn.disabled = false;
        trainBtn.innerHTML = originalBtnHTML;
    }
});