# USAGE
# python server_with_storage.py --port 5555

import argparse
import imagezmq
import cv2
import numpy as np
import time
import zmq
import logging
import psycopg2
import os
from datetime import datetime, timedelta

# --- KONFIGURASI ---
# Konfigurasi Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Konfigurasi Database PostgreSQL (UBAH SESUAI KEBUTUHAN ANDA)
DB_CONFIG = {
    "dbname": "yolo",
    "user": "postgres",
    "password": "123",
    "host": "localhost",
    "port": "5432"
}

# Konfigurasi Penyimpanan
IMAGE_SAVE_INTERVAL_SECONDS = 1  # Simpan gambar setiap 1 detik
VIDEO_RECORD_DURATION_MINUTES = 30 # Simpan video setiap 30 menit
RECORDINGS_DIR = "recordings" # Direktori untuk menyimpan file video

# --- FUNGSI DATABASE ---

def connect_db():
    """Membuka koneksi baru ke database PostgreSQL."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        logging.info("Successfully connected to the PostgreSQL database.")
        return conn
    except psycopg2.OperationalError as e:
        logging.error(f"Could not connect to database: {e}")
        return None

def save_image_to_db(conn, client_name, image_frame):
    """Meng-encode gambar dan menyimpannya ke tabel captured_images."""
    _, jpg_buffer = cv2.imencode('.jpg', image_frame)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO captured_images (client_name, image_data) VALUES (%s, %s)",
                (client_name, psycopg2.Binary(jpg_buffer))
            )
        conn.commit()
        logging.info(f"Successfully saved image from {client_name} to DB.")
    except Exception as e:
        conn.rollback()
        logging.error(f"Failed to save image to DB: {e}")

def save_video_metadata_to_db(conn, client_name, file_path, start_time, end_time):
    """Menyimpan metadata video ke tabel recorded_videos."""
    duration = (end_time - start_time).total_seconds()
    file_size = os.path.getsize(file_path) / 1024 # dalam KB
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO recorded_videos (client_name, file_path, start_time, end_time, duration_seconds, file_size_kb)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (client_name, file_path, start_time, end_time, int(duration), int(file_size))
            )
        conn.commit()
        logging.info(f"Successfully saved video metadata for {file_path} to DB.")
    except Exception as e:
        conn.rollback()
        logging.error(f"Failed to save video metadata to DB: {e}")

# --- FUNGSI UTAMA SERVER ---

def main():
    # Buat direktori perekaman jika belum ada
    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    
    # Argumen parser
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--port", type=str, default="5555",
        help="port number for the server")
    args = vars(ap.parse_args())

    # Inisialisasi koneksi database
    db_conn = connect_db()
    if not db_conn:
        return # Keluar jika tidak bisa konek ke DB

    # Inisialisasi ImageHub
    receiver = imagezmq.ImageHub(open_port="tcp://*:" + args["port"])
    receive_timeout_ms = 2000  # Timeout 2 detik
    receiver.zmq_socket.setsockopt(zmq.RCVTIMEO, receive_timeout_ms)

    logging.info(f"Server listening on port {args['port']}...")

    # Variabel state untuk penyimpanan
    last_image_save_time = time.time()
    
    # Variabel state untuk perekaman video
    video_writer = None
    video_start_time = None
    video_filename = None
    
    try:
        while True:
            try:
                client_name, frame = receiver.recv_image()
                receiver.send_reply(b'OK')

                if frame is None:
                    continue
                
                # Tampilkan frame yang diterima
                cv2.imshow("Live Stream from " + client_name, frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

                current_time = time.time()
                now_datetime = datetime.now()

                # --- Logika Perekaman Video ---
                if video_writer is None:
                    # Mulai perekaman video baru
                    video_start_time = now_datetime
                    timestamp_str = video_start_time.strftime("%Y%m%d_%H%M%S")
                    video_filename = os.path.join(RECORDINGS_DIR, f"{client_name}_{timestamp_str}.mp4")
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v') # Codec
                    height, width, _ = frame.shape
                    video_writer = cv2.VideoWriter(video_filename, fourcc, 20.0, (width, height))
                    logging.info(f"Starting new video recording: {video_filename}")

                # Tulis frame ke file video
                video_writer.write(frame)

                # Cek apakah durasi perekaman sudah tercapai
                if (now_datetime - video_start_time).total_seconds() >= VIDEO_RECORD_DURATION_MINUTES * 60:
                    logging.info(f"Completing video recording: {video_filename}")
                    video_writer.release()
                    save_video_metadata_to_db(db_conn, client_name, video_filename, video_start_time, now_datetime)
                    video_writer = None # Set ke None agar rekaman baru dimulai di iterasi selanjutnya

                # --- Logika Penyimpanan Gambar ---
                if current_time - last_image_save_time >= IMAGE_SAVE_INTERVAL_SECONDS:
                    save_image_to_db(db_conn, client_name, frame)
                    last_image_save_time = current_time

            except zmq.error.Again:
                logging.info("Waiting for client connection...")
                # Jika tidak ada klien, pastikan video writer ditutup jika ada
                if video_writer is not None:
                    logging.warning(f"Client disconnected. Closing video file: {video_filename}")
                    video_writer.release()
                    save_video_metadata_to_db(db_conn, client_name, video_filename, video_start_time, datetime.now())
                    video_writer = None
                continue
                
            except Exception as e:
                logging.error(f"An error occurred in the main loop: {e}", exc_info=True)
                time.sleep(1)

    except (KeyboardInterrupt, SystemExit):
        logging.info("Server shutting down.")
    finally:
        # Cleanup terakhir sebelum keluar
        if video_writer is not None:
            logging.info(f"Finalizing last video recording: {video_filename}")
            video_writer.release()
            save_video_metadata_to_db(db_conn, client_name, video_filename, video_start_time, datetime.now())
        
        if db_conn:
            db_conn.close()
            logging.info("Database connection closed.")
            
        cv2.destroyAllWindows()
        receiver.close()

if __name__ == "__main__":
    main()