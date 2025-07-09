-- Hapus database jika sudah ada (OPSIONAL, HATI-HATI!)
-- DROP DATABASE IF EXISTS db_yolo;

-- Buat database baru
-- Anda mungkin perlu menjalankan perintah ini secara terpisah
CREATE DATABASE db_yolo
    WITH
    OWNER = postgres
    ENCODING = 'UTF8'
    LC_COLLATE = 'English_United States.1252'
    LC_CTYPE = 'English_United States.1252'
    TABLESPACE = pg_default
    CONNECTION LIMIT = -1;

-- Setelah membuat database, koneksikan ke db_yolo sebelum menjalankan sisa skrip ini.
-- \c db_yolo

-- -----------------------------------------------------
-- Tabel untuk menyimpan gambar yang ditangkap dari client
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS public.captured_images
(
    id SERIAL PRIMARY KEY,
    client_name VARCHAR(255) NOT NULL,
    image_data BYTEA NOT NULL,
    thumbnail_data BYTEA,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE public.captured_images IS 'Menyimpan data gambar yang diterima dari client ImageZMQ.';
COMMENT ON COLUMN public.captured_images.id IS 'Primary Key, ID unik untuk setiap record gambar.';
COMMENT ON COLUMN public.captured_images.image_data IS 'Data gambar mentah dalam format biner (binary large object).';
COMMENT ON COLUMN public.captured_images.thumbnail_data IS 'Data thumbnail gambar dalam format biner untuk pemuatan cepat.';


-- -----------------------------------------------------
-- Tabel untuk menyimpan metadata rekaman video
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS public.recorded_videos
(
    id SERIAL PRIMARY KEY,
    client_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(1024) NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE,
    end_time TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,
    file_size_kb INTEGER
);

COMMENT ON TABLE public.recorded_videos IS 'Menyimpan metadata untuk file video yang direkam oleh server.';
COMMENT ON COLUMN public.recorded_videos.file_path IS 'Lokasi penyimpanan file video di sistem file server.';


-- -----------------------------------------------------
-- Tabel untuk menyimpan anotasi (bounding box) untuk gambar
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS public.annotations
(
    id SERIAL PRIMARY KEY,
    image_id INTEGER NOT NULL,
    class_id INTEGER NOT NULL DEFAULT 0,
    bbox_x DOUBLE PRECISION NOT NULL,
    bbox_y DOUBLE PRECISION NOT NULL,
    bbox_width DOUBLE PRECISION NOT NULL,
    bbox_height DOUBLE PRECISION NOT NULL,
    CONSTRAINT fk_image
        FOREIGN KEY(image_id) 
        REFERENCES captured_images(id)
        ON DELETE CASCADE
);

-- Membuat index pada kolom image_id untuk mempercepat query join dan pencarian anotasi
CREATE INDEX IF NOT EXISTS idx_annotations_image_id ON public.annotations(image_id);

COMMENT ON TABLE public.annotations IS 'Menyimpan data anotasi bounding box untuk setiap gambar.';
COMMENT ON COLUMN public.annotations.image_id IS 'ID dari gambar di tabel captured_images yang dianotasi.';
COMMENT ON COLUMN public.annotations.class_id IS 'ID kelas objek yang dianotasi.';
COMMENT ON COLUMN public.annotations.bbox_x IS 'Koordinat X tengah dari bounding box (relatif).';
COMMENT ON COLUMN public.annotations.fk_image IS 'Constraint yang memastikan integritas data dengan tabel captured_images.';


-- Set kepemilikan tabel ke user 'postgres' (atau user database Anda)
ALTER TABLE public.captured_images OWNER to postgres;
ALTER TABLE public.recorded_videos OWNER to postgres;
ALTER TABLE public.annotations OWNER to postgres;

-- Pesan bahwa skrip telah selesai
-- (Ini adalah komentar, tidak akan dieksekusi)
-- Skema database 'db_yolo' berhasil dibuat.