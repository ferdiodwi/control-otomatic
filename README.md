# Sistem Deteksi Objek Real-Time dengan Manajemen Media (Flask & YOLOv8)

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=for-the-badge&logo=python)
![Flask](https://img.shields.io/badge/Flask-2.x-black?style=for-the-badge&logo=flask)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-13%2B-blue?style=for-the-badge&logo=postgresql)
![YOLOv8](https://img.shields.io/badge/YOLO-v8-purple?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

Sistem aplikasi web komprehensif yang dirancang untuk menerima stream video, melakukan deteksi objek secara real-time menggunakan model YOLO, dan mengelola semua aset media yang dihasilkan melalui antarmuka yang intuitif.


---

## 🚀 Fitur Utama

-   **📽️ Pemrosesan Stream Real-Time**: Menerima feed video dari berbagai klien (misalnya, Raspberry Pi, laptop lain) melalui jaringan.
-   **🧠 Inferensi AI dengan YOLO**: Menjalankan model deteksi objek YOLO (dapat dikonfigurasi) pada setiap frame yang diterima.
-   **🗄️ Manajemen Media Otomatis**:
    -   Secara otomatis menyimpan gambar dan rekaman video **mentah** (raw).
    -   Secara otomatis menyimpan gambar dan rekaman video **beranotasi** (hasil inferensi AI).
-   **🖼️ Galeri Media Interaktif**: Antarmuka web untuk melihat, memfilter, dan mengelola semua gambar dan video yang tersimpan (mentah & beranotasi). Mendukung seleksi massal dan penghapusan.
-   **✏️ Alat Anotasi Web**: Halaman khusus untuk menggambar *bounding box* pada gambar yang tersimpan dan menyimpannya ke database untuk pelatihan ulang.
-   **⚙️ Alur Kerja Pelatihan Model**:
    -   Ekspor data anotasi dari database ke format dataset YOLO secara otomatis.
    -   Memulai proses pelatihan model YOLO dari antarmuka web dan melihat log pelatihan secara *live*.
-   **🔌 Arsitektur Multi-Thread**: Menggunakan thread terpisah untuk penerimaan stream dan pemrosesan AI, memastikan performa yang lancar dan responsif.

---

## 🛠️ Tumpukan Teknologi

-   **Backend**: Python, Flask, Psycopg2
-   **AI & Computer Vision**: Ultralytics YOLOv8, OpenCV
-   **Komunikasi Real-Time**: ZMQ (imagezmq)
-   **Database**: PostgreSQL
-   **Frontend**: HTML, CSS, JavaScript (Vanilla)

---

## 📦 Panduan Instalasi dan Setup

Ikuti langkah-langkah ini untuk menjalankan proyek di lingkungan lokal Anda.

### 1. Prasyarat

-   [Python](https://www.python.org/downloads/) (versi 3.9 atau lebih tinggi)
-   [PostgreSQL](https://www.postgresql.org/download/) (versi 13 atau lebih tinggi)
-   [Git](https://git-scm.com/downloads/)

### 2. Clone Repositori

```bash
git clone [https://github.com/ferdiodwi/control-otomatic.git](https://github.com/ferdiodwi/control-otomatic.git)
cd control-otomatic