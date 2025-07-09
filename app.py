# app.py
import base64
import psycopg2
import psycopg2.extras
import os
import shutil
import sys
import yaml
import subprocess
import threading
import time
import imagezmq
import zmq
import logging
import queue
from flask import Flask, render_template, jsonify, request, redirect, url_for, Response, send_from_directory
from psycopg2.pool import ThreadedConnectionPool
from ultralytics import YOLO
import cv2
import numpy as np
from datetime import datetime

# --- KONFIGURASI ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)
RECORDINGS_DIR = "recordings"
if not os.path.exists(RECORDINGS_DIR):
    os.makedirs(RECORDINGS_DIR)

# [MODIFIKASI] Menambahkan konfigurasi untuk video
DB_CONFIG = {"dbname": "db_yolo", "user": "postgres", "password": "123", "host": "localhost", "port": "5432"}
DATASET_EXPORT_PATH = "dataset"
TRAINED_MODEL_PATH = "runs/train/exp/weights/best.pt"
IMAGE_SAVE_INTERVAL_SECONDS = 5  # Simpan gambar setiap 5 detik
VIDEO_RECORD_DURATION_MINUTES = 1  # Simpan video per segmen 1 menit

db_pool = ThreadedConnectionPool(minconn=1, maxconn=10, **DB_CONFIG)

latest_frame_data = {
    "frame": None,
    "lock": threading.Lock()
}
training_log_queue = queue.Queue()


def get_db_connection():
    """Mendapatkan koneksi dari pool."""
    return db_pool.getconn()


def release_db_connection(conn):
    """Mengembalikan koneksi ke pool."""
    db_pool.putconn(conn)


# --- FUNGSI DATABASE & HELPER ---

def save_image_to_db(conn, client_name, image_frame):
    """Menyimpan satu frame gambar beserta thumbnail-nya ke database."""
    _, jpg_buffer = cv2.imencode('.jpg', image_frame)
    h, w, _ = image_frame.shape
    aspect_ratio = h / w
    THUMBNAIL_WIDTH = 250
    new_height = int(THUMBNAIL_WIDTH * aspect_ratio)
    thumbnail_frame = cv2.resize(image_frame, (THUMBNAIL_WIDTH, new_height), interpolation=cv2.INTER_AREA)
    _, jpg_buffer_thumbnail = cv2.imencode('.jpg', thumbnail_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO captured_images (client_name, image_data, thumbnail_data, created_at) VALUES (%s, %s, %s, %s)",
                (client_name, psycopg2.Binary(jpg_buffer), psycopg2.Binary(jpg_buffer_thumbnail), datetime.now())
            )
        conn.commit()
        logging.info(f"Successfully saved image and thumbnail from {client_name} to DB.")
    except Exception as e:
        conn.rollback()
        logging.error(f"Failed to save image to DB: {e}")


# [BARU] Fungsi untuk menyimpan metadata video, diadaptasi dari server.py
def save_video_metadata_to_db(conn, client_name, file_path, start_time, end_time):
    """Menyimpan metadata video ke tabel recorded_videos."""
    # Pastikan tabel 'recorded_videos' ada di database Anda
    # CREATE TABLE recorded_videos (
    #     id SERIAL PRIMARY KEY,
    #     client_name VARCHAR(255),
    #     file_path VARCHAR(255) NOT NULL,
    #     start_time TIMESTAMP WITHOUT TIME ZONE,
    #     end_time TIMESTAMP WITHOUT TIME ZONE,
    #     duration_seconds INTEGER,
    #     file_size_kb INTEGER,
    #     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    # );
    if not os.path.exists(file_path):
        logging.warning(f"File video tidak ditemukan di path: {file_path}, metadata tidak disimpan.")
        return

    duration = (end_time - start_time).total_seconds()
    file_size = os.path.getsize(file_path) / 1024  # dalam KB
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO recorded_videos (client_name, file_path, start_time, end_time, duration_seconds,
                                             file_size_kb)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (client_name, file_path, start_time, end_time, int(duration), int(file_size))
            )
        conn.commit()
        logging.info(f"Successfully saved video metadata for {file_path} to DB.")
    except Exception as e:
        conn.rollback()
        logging.error(f"Failed to save video metadata to DB: {e}")


def export_data_for_yolo():
    # Implementasi fungsi ini tetap sama
    conn = None
    try:
        if os.path.exists(DATASET_EXPORT_PATH):
            shutil.rmtree(DATASET_EXPORT_PATH)
        train_img_path = os.path.join(DATASET_EXPORT_PATH, "images", "train")
        train_lbl_path = os.path.join(DATASET_EXPORT_PATH, "labels", "train")
        val_img_path = os.path.join(DATASET_EXPORT_PATH, "images", "val")
        val_lbl_path = os.path.join(DATASET_EXPORT_PATH, "labels", "val")
        os.makedirs(train_img_path);
        os.makedirs(train_lbl_path);
        os.makedirs(val_img_path);
        os.makedirs(val_lbl_path)
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT DISTINCT i.id, i.image_data FROM captured_images i JOIN annotations a ON i.id = a.image_id")
            images = cur.fetchall()
            if not images: return False, "Tidak ada gambar beranotasi yang ditemukan untuk diekspor."
            cur.execute("SELECT image_id, class_id, bbox_x, bbox_y, bbox_width, bbox_height FROM annotations")
            all_annotations = cur.fetchall()
        annotations_by_image = {}
        for ann in all_annotations:
            if ann['image_id'] not in annotations_by_image: annotations_by_image[ann['image_id']] = []
            annotations_by_image[ann['image_id']].append(ann)
        class_names, image_files_to_write = set(), []
        for img_row in images:
            img_id, img_data = img_row['id'], img_row['image_data']
            nparr = cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)
            img_h, img_w, _ = nparr.shape
            label_lines = []
            if img_id in annotations_by_image:
                for row in annotations_by_image[img_id]:
                    x_center, y_center = (row['bbox_x'] + row['bbox_width'] / 2) / img_w, (
                                row['bbox_y'] + row['bbox_height'] / 2) / img_h
                    width, height = row['bbox_width'] / img_w, row['bbox_height'] / img_h
                    class_id = int(row['class_id'])
                    class_names.add(f"class_{class_id}")
                    label_lines.append(f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}")
            image_files_to_write.append({'id': img_id, 'image_data': img_data, 'labels': label_lines})
        split_index = int(len(image_files_to_write) * 0.8)
        train_data, val_data = image_files_to_write[:split_index], image_files_to_write[split_index:]
        for data in train_data:
            with open(os.path.join(train_img_path, f"{data['id']}.jpg"), 'wb') as f: f.write(data['image_data'])
            with open(os.path.join(train_lbl_path, f"{data['id']}.txt"), 'w') as f: f.write("\n".join(data['labels']))
        for data in val_data:
            with open(os.path.join(val_img_path, f"{data['id']}.jpg"), 'wb') as f: f.write(data['image_data'])
            with open(os.path.join(val_lbl_path, f"{data['id']}.txt"), 'w') as f: f.write("\n".join(data['labels']))
        if not class_names: return False, "Tidak ada kelas anotasi yang ditemukan."
        sorted_class_names = sorted(list(class_names), key=lambda name: int(name.split('_')[1]))
        yaml_content = {'train': os.path.abspath(train_img_path), 'val': os.path.abspath(val_img_path),
                        'nc': len(sorted_class_names), 'names': sorted_class_names}
        yaml_path = os.path.join(DATASET_EXPORT_PATH, "data.yaml")
        with open(yaml_path, 'w') as f:
            yaml.dump(yaml_content, f, default_flow_style=False)
        return True, yaml_path
    except Exception as e:
        print(f"Error saat ekspor data: {e}")
        return False, str(e)
    finally:
        if conn: release_db_connection(conn)


# [MODIFIKASI] Thread utama untuk menerima gambar dan merekam video
def image_receiver_thread():
    logging.info("Image receiver thread started, waiting for client...")
    db_conn = get_db_connection()

    # Konfigurasi ZMQ Receiver
    receiver = imagezmq.ImageHub()
    receive_timeout_ms = 2000  # Timeout 2 detik untuk deteksi disconnect
    receiver.zmq_socket.setsockopt(zmq.RCVTIMEO, receive_timeout_ms)

    # State untuk penyimpanan
    last_image_save_time = time.time()
    video_writer_states = {}  # { 'client_name': {'writer': obj, 'start_time': dt, 'path': '...'}}

    try:
        while True:
            client_name = None
            try:
                client_name, frame = receiver.recv_image()
                receiver.send_reply(b'OK')

                if frame is None:
                    continue

                # Perbarui frame global untuk live feed
                with latest_frame_data["lock"]:
                    latest_frame_data["frame"] = frame.copy()

                now_datetime = datetime.now()
                current_time = time.time()

                # --- Logika Perekaman Video ---
                client_state = video_writer_states.get(client_name)

                # Jika belum ada video writer untuk client ini, buat baru
                if not client_state:
                    video_start_time = now_datetime
                    timestamp_str = video_start_time.strftime("%Y%m%d_%H%M%S")
                    video_filename = os.path.join(RECORDINGS_DIR, f"{client_name}_{timestamp_str}.mp4")
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # Codec .mp4
                    height, width, _ = frame.shape
                    writer = cv2.VideoWriter(video_filename, fourcc, 20.0, (width, height))

                    video_writer_states[client_name] = {
                        'writer': writer,
                        'start_time': video_start_time,
                        'path': video_filename
                    }
                    logging.info(f"Starting new video recording for {client_name}: {video_filename}")

                # Tulis frame ke file video
                video_writer_states[client_name]['writer'].write(frame)

                # Cek apakah durasi perekaman sudah tercapai
                start_time = video_writer_states[client_name]['start_time']
                if (now_datetime - start_time).total_seconds() >= VIDEO_RECORD_DURATION_MINUTES * 60:
                    logging.info(
                        f"Completing video segment for {client_name}: {video_writer_states[client_name]['path']}")
                    # Finalisasi video
                    video_writer_states[client_name]['writer'].release()
                    # Simpan metadata ke DB
                    save_video_metadata_to_db(db_conn, client_name, video_writer_states[client_name]['path'],
                                              start_time, now_datetime)
                    # Hapus state untuk memulai yang baru di iterasi berikutnya
                    video_writer_states.pop(client_name, None)

                # --- Logika Penyimpanan Gambar (Snapshot) ---
                if current_time - last_image_save_time >= IMAGE_SAVE_INTERVAL_SECONDS:
                    save_image_to_db(db_conn, client_name, frame)
                    last_image_save_time = current_time

            except zmq.error.Again:
                logging.info("Waiting for new client connection...")
                # Jika client timeout/disconnect, finalisasi video yang sedang berjalan
                if client_name and client_name in video_writer_states:
                    logging.warning(
                        f"Client '{client_name}' disconnected. Closing video file: {video_writer_states[client_name]['path']}")
                    state = video_writer_states.pop(client_name)
                    state['writer'].release()
                    save_video_metadata_to_db(db_conn, client_name, state['path'], state['start_time'], datetime.now())
                time.sleep(1)
                continue

            except Exception as e:
                logging.error(f"Error in image receiver thread: {e}", exc_info=True)
                time.sleep(2)

    finally:
        # Cleanup terakhir sebelum thread berhenti
        logging.info("Image receiver thread shutting down. Finalizing all recordings...")
        for client, state in video_writer_states.items():
            state['writer'].release()
            logging.info(f"Finalized recording for {client}: {state['path']}")
            save_video_metadata_to_db(db_conn, client, state['path'], state['start_time'], datetime.now())

        release_db_connection(db_conn)
        logging.info("Database connection released.")


# --- RUTE-RUTE HALAMAN ---

@app.route('/')
def home():
    conn = None
    stats = {
        'total_images': 0, 'total_videos': 0, 'annotated_images': 0,
        'unannotated_images': 0, 'model_exists': False, 'progress': 0.0
    }
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                        SELECT (SELECT COUNT(*) FROM captured_images)             AS total_images,
                               (SELECT COUNT(*) FROM recorded_videos)             AS total_videos,
                               (SELECT COUNT(DISTINCT image_id) FROM annotations) AS annotated_images;
                        """)
            result = cur.fetchone()
            total_images, total_videos, annotated_images = result

            stats['total_images'] = total_images
            stats['total_videos'] = total_videos
            stats['annotated_images'] = annotated_images
            stats['unannotated_images'] = total_images - annotated_images
            if total_images > 0:
                stats['progress'] = round((annotated_images / total_images) * 100, 1)

        stats['model_exists'] = os.path.exists(TRAINED_MODEL_PATH)
        return render_template('home.html', stats=stats)
    except Exception as e:
        print(f"Error di rute home: {e}")
        return render_template('home.html', stats=stats)
    finally:
        if conn: release_db_connection(conn)


@app.route('/gallery')
def gallery():
    return render_template('gallery.html')


@app.route('/data_anotasi')
def data_cleaning_page():
    return render_template('data_cleaning.html')


@app.route('/train')
def train_page():
    return render_template('train.html')


@app.route('/live_inference')
def live_inference_page():
    return render_template('inference.html')


@app.route('/annotate/<int:image_id>')
def annotate(image_id):
    conn = None
    context = request.args.get('context', 'unannotated')
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id FROM captured_images WHERE id = %s", (image_id,))
            image_info = cur.fetchone()
            if not image_info: return "Image not found", 404

            cur.execute("SELECT image_data FROM captured_images WHERE id = %s", (image_id,))
            image_data = cur.fetchone()['image_data']

            cur.execute("SELECT * FROM annotations WHERE image_id = %s ORDER BY id", (image_id,))
            annotations = [dict(row) for row in cur.fetchall()]

            nav_ids = []
            if context == 'annotated':
                cur.execute("SELECT DISTINCT image_id AS id FROM annotations ORDER BY image_id ASC")
                nav_ids = [row['id'] for row in cur.fetchall()]
            else:
                cur.execute(
                    "SELECT id FROM captured_images WHERE NOT EXISTS (SELECT 1 FROM annotations WHERE image_id = captured_images.id) ORDER BY id ASC")
                nav_ids = [row['id'] for row in cur.fetchall()]

            prev_id, next_id = None, None
            try:
                current_index = nav_ids.index(image_id)
                if current_index > 0: prev_id = nav_ids[current_index - 1]
                if current_index < len(nav_ids) - 1: next_id = nav_ids[current_index + 1]
            except ValueError:
                pass

        image_data_b64 = base64.b64encode(image_data).decode('utf-8')
        return render_template(
            'annotate.html', image_info=image_info, image_data_b64=image_data_b64,
            annotations=annotations, prev_id=prev_id, next_id=next_id, context=context
        )
    except Exception as e:
        logging.error(f"Error in annotate route for image {image_id}: {e}", exc_info=True)
        return "Server error", 500
    finally:
        if conn: release_db_connection(conn)


# --- ENDPOINT API ---

def process_media_rows(rows):
    """Helper to convert media data and encode thumbnails."""
    results = []
    for row in rows:
        item = dict(row)
        if 'thumbnail_data' in item and item['thumbnail_data']:
            item['thumbnail_b64'] = base64.b64encode(item['thumbnail_data']).decode('utf-8')
        else:
            item['thumbnail_b64'] = None
        item.pop('thumbnail_data', None)
        item.pop('image_data', None)
        results.append(item)
    return results


# [MODIFIKASI] API untuk galeri sekarang juga mengambil thumbnail video jika ada
@app.route('/api/gallery_media')
def get_gallery_media():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Query ini menggabungkan gambar dan video, diurutkan berdasarkan waktu pembuatan
            # dan memastikan ada kolom 'filename' yang konsisten.
            query = """
                (SELECT 
                    'image' as type, 
                    id, 
                    client_name, 
                    thumbnail_data, 
                    created_at as timestamp, 
                    'img_' || id || '_' || to_char(created_at, 'YYYYMMDD') || '.jpg' as filename
                FROM captured_images)
                UNION ALL
                (SELECT 
                    'video' as type, 
                    id, 
                    client_name, 
                    NULL as thumbnail_data, 
                    start_time as timestamp,
                    file_path as filename
                FROM recorded_videos)
                ORDER BY timestamp DESC
                LIMIT %s OFFSET %s;
            """
            cur.execute(query, (per_page, offset))
            raw_media = cur.fetchall()

            media_items = []
            for row in raw_media:
                item = dict(row)
                if item.get('timestamp'):
                    item['timestamp_str'] = item['timestamp'].strftime('%d %b %Y, %H:%M:%S')

                if item['type'] == 'image' and item.get('thumbnail_data'):
                    item['thumbnail_b64'] = base64.b64encode(item['thumbnail_data']).decode('utf-8')
                else:
                    item['thumbnail_b64'] = None

                    # Untuk video, nama file mungkin berisi path, kita hanya butuh nama filenya saja.
                if item['type'] == 'video' and item.get('filename'):
                    item['filename'] = os.path.basename(item['filename'])

                # Menghapus data biner besar dari payload JSON
                item.pop('thumbnail_data', None)
                media_items.append(item)

        return jsonify(media_items)
    except Exception as e:
        logging.error(f"Error fetching gallery media: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: release_db_connection(conn)


@app.route('/api/data_by_status')
def get_data_by_status():
    status = request.args.get('status', 'unannotated')
    sort_order = request.args.get('sort_order', 'desc')
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    if sort_order.lower() not in ['asc', 'desc']:
        sort_order = 'desc'

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            if status == 'unannotated':
                query = f"""
                    SELECT id, created_at, thumbnail_data 
                    FROM captured_images i
                    WHERE NOT EXISTS (
                        SELECT 1 FROM annotations a WHERE a.image_id = i.id
                    )
                    ORDER BY i.created_at {sort_order.upper()}
                    LIMIT %s OFFSET %s;
                """
            else:  # annotated
                query = f"""
                    SELECT i.id, i.created_at, i.thumbnail_data
                    FROM captured_images i
                    WHERE EXISTS (
                        SELECT 1 FROM annotations a WHERE a.image_id = i.id
                    )
                    ORDER BY i.created_at {sort_order.upper()}
                    LIMIT %s OFFSET %s;
                """
            cur.execute(query, (per_page, offset))
            images = process_media_rows(cur.fetchall())
        return jsonify(images)
    except Exception as e:
        logging.error(f"Error fetching {status} data: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: release_db_connection(conn)


# --- Sisa Rute API & Streaming ---
@app.route('/api/save_annotation', methods=['POST'])
def save_annotation():
    conn = None
    try:
        data = request.get_json()
        image_id, class_id, bbox = data.get('image_id'), data.get('class_id', 0), data.get('bbox')
        if not all([image_id, bbox]): return jsonify({"status": "error", "message": "Data tidak lengkap"}), 400
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "INSERT INTO annotations (image_id, class_id, bbox_x, bbox_y, bbox_width, bbox_height) VALUES (%s, %s, %s, %s, %s, %s) RETURNING *;",
                (image_id, class_id, bbox['x'], bbox['y'], bbox['width'], bbox['height']))
            new_annotation = cur.fetchone()
        conn.commit()
        return jsonify(
            {"status": "success", "message": "Anotasi berhasil disimpan!", "new_annotation": dict(new_annotation)})
    except Exception as e:
        if conn: conn.rollback()
        print(f"Error saving annotation: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn: release_db_connection(conn)


@app.route('/api/delete_annotation/<int:annotation_id>', methods=['DELETE'])
def delete_annotation(annotation_id):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM annotations WHERE id = %s", (annotation_id,))
            if cur.rowcount == 0:
                conn.rollback()
                return jsonify({"status": "error", "message": "Anotasi tidak ditemukan"}), 404
        conn.commit()
        return jsonify({"status": "success", "message": "Anotasi berhasil dihapus."})
    except Exception as e:
        if conn: conn.rollback()
        print(f"Error saat menghapus anotasi {annotation_id}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn: release_db_connection(conn)


@app.route('/api/delete_annotations_for_image/<int:image_id>', methods=['DELETE'])
def delete_all_annotations_for_image(image_id):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM annotations WHERE image_id = %s", (image_id,))
            deleted_count = cur.rowcount
        conn.commit()
        return jsonify(
            {"status": "success", "message": f"Berhasil menghapus {deleted_count} anotasi untuk gambar ID {image_id}."})
    except Exception as e:
        if conn: conn.rollback()
        print(f"Error saat menghapus semua anotasi untuk gambar {image_id}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn: release_db_connection(conn)


# [MODIFIKASI] API delete sekarang menangani video
@app.route('/api/delete_media/<string:media_type>/<int:media_id>', methods=['DELETE'])
def delete_media(media_type, media_id):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            if media_type == 'image':
                cur.execute("DELETE FROM annotations WHERE image_id = %s", (media_id,))
                cur.execute("DELETE FROM captured_images WHERE id = %s", (media_id,))
            elif media_type == 'video':
                cur.execute("SELECT file_path FROM recorded_videos WHERE id = %s", (media_id,))
                row = cur.fetchone()
                if row and row[0] and os.path.exists(row[0]):
                    os.remove(row[0])
                    logging.info(f"File video fisik '{row[0]}' telah dihapus.")
                cur.execute("DELETE FROM recorded_videos WHERE id = %s", (media_id,))
            else:
                return jsonify({"status": "error", "message": "Tipe media tidak valid"}), 400

            if cur.rowcount == 0:
                conn.rollback()
                return jsonify({"status": "error", "message": "Media tidak ditemukan"}), 404

        conn.commit()
        return jsonify({"status": "success", "message": f"{media_type.capitalize()} ID {media_id} berhasil dihapus."})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn: release_db_connection(conn)


@app.route('/api/delete_media_bulk', methods=['POST'])
def delete_media_bulk():
    conn = None
    try:
        data = request.get_json()
        media_type = data.get('media_type')
        ids_to_delete = data.get('ids')
        if not all([media_type, isinstance(ids_to_delete, list)]): return jsonify(
            {"status": "error", "message": "Payload tidak lengkap atau format salah."}), 400
        if not ids_to_delete: return jsonify(
            {"status": "success", "message": "Tidak ada item yang dipilih untuk dihapus."})
        conn = get_db_connection()
        with conn.cursor() as cur:
            if media_type == 'image':
                id_tuple = tuple(ids_to_delete)
                cur.execute("DELETE FROM annotations WHERE image_id IN %s", (id_tuple,))
                cur.execute("DELETE FROM captured_images WHERE id IN %s", (id_tuple,))
            elif media_type == 'video':
                id_tuple = tuple(ids_to_delete)
                cur.execute("SELECT file_path FROM recorded_videos WHERE id IN %s", (id_tuple,))
                for row in cur.fetchall():
                    if row and row[0] and os.path.exists(row[0]):
                        os.remove(row[0])
                cur.execute("DELETE FROM recorded_videos WHERE id IN %s", (id_tuple,))
            else:
                return jsonify({"status": "error", "message": "Tipe media tidak valid untuk hapus massal"}), 400
            deleted_count = cur.rowcount
        conn.commit()
        return jsonify({"status": "success", "message": f"{deleted_count} {media_type} berhasil dihapus."})
    except Exception as e:
        if conn: conn.rollback()
        print(f"Error saat menghapus massal: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn: release_db_connection(conn)


def run_training_in_thread(yaml_path):
    try:
        command = [sys.executable, '-u', 'run_training.py', yaml_path]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        for line in iter(process.stdout.readline, ''):
            training_log_queue.put(line)
        process.stdout.close()
        return_code = process.wait()
        if return_code == 0:
            training_log_queue.put("\n[SUCCESS] Proses pelatihan di server telah selesai.")
        else:
            training_log_queue.put(f"\n[ERROR] Proses pelatihan di server berhenti dengan kode: {return_code}")
    except Exception as e:
        training_log_queue.put(f"\n[FATAL] Gagal menjalankan thread pelatihan: {str(e)}")
    finally:
        training_log_queue.put(None)


@app.route('/api/start_training', methods=['POST'])
def start_training():
    if 'training_thread' in app.config and app.config['training_thread'].is_alive():
        return jsonify({"status": "error", "message": "Proses pelatihan lain sudah berjalan."}), 409
    success, message_or_path = export_data_for_yolo()
    if not success:
        return jsonify({"status": "error", "message": f"Gagal mengekspor data: {message_or_path}"}), 500
    try:
        yaml_path = os.path.abspath(message_or_path)
        while not training_log_queue.empty():
            training_log_queue.get()
        thread = threading.Thread(target=run_training_in_thread, args=(yaml_path,))
        thread.daemon = True
        app.config['training_thread'] = thread
        thread.start()
        return jsonify(
            {"status": "success", "message": "Proses ekspor data berhasil. Memulai streaming log pelatihan..."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Gagal memulai subprocess pelatihan: {e}"}), 500


@app.route('/api/training_status')
def training_status():
    def generate_logs():
        while True:
            try:
                line = training_log_queue.get(timeout=10)
                if line is None:
                    yield 'event: complete\ndata: Pelatihan Selesai\n\n'
                    break
                yield f'data: {line}\n\n'
            except queue.Empty:
                yield ': keep-alive\n\n'

    return Response(generate_logs(), mimetype='text/event-stream')


@app.route('/video_feed')
def video_feed():
    def generate_frames():
        model_exists = os.path.exists(TRAINED_MODEL_PATH)
        model = YOLO(TRAINED_MODEL_PATH) if model_exists else None
        while True:
            frame = None
            with latest_frame_data["lock"]:
                if latest_frame_data["frame"] is not None: frame = latest_frame_data["frame"].copy()
            if frame is None:
                placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(placeholder, "Menunggu stream dari client...", (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1,
                            (255, 255, 255), 2)
                (flag, encodedImage) = cv2.imencode(".jpg", placeholder)
                yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + bytearray(encodedImage) + b'\r\n')
                time.sleep(1)
                continue
            if model:
                results = model(frame, verbose=False)
                annotated_frame = results[0].plot()
            else:
                annotated_frame = frame
            (flag, encodedImage) = cv2.imencode(".jpg", annotated_frame)
            if not flag: continue
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + bytearray(encodedImage) + b'\r\n')

    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/server_video_feed')
def server_video_feed():
    def generate_server_frames():
        model_exists = os.path.exists(TRAINED_MODEL_PATH)
        model = YOLO(TRAINED_MODEL_PATH) if model_exists else None
        logging.info(f"SERVER CAM - Model exist: {model_exists}. Model loaded: {'Yes' if model else 'No'}")
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            logging.error("SERVER CAM - Tidak dapat membuka kamera server (ID: 0).")
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "Error: Kamera server tidak ditemukan", (30, 240), cv2.FONT_HERSHEY_SIMPLEX, 1,
                        (0, 0, 255), 2)
            (flag, encodedImage) = cv2.imencode(".jpg", placeholder)
            while True:
                yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + bytearray(encodedImage) + b'\r\n')
                time.sleep(1)
        logging.info("SERVER CAM - Kamera server berhasil dibuka. Memulai streaming...")
        try:
            while True:
                success, frame = cap.read()
                if not success:
                    logging.warning("SERVER CAM - Gagal membaca frame dari kamera. Menghentikan stream.")
                    break
                if model:
                    results = model(frame, verbose=False)
                    annotated_frame = results[0].plot()
                else:
                    annotated_frame = frame
                    cv2.putText(annotated_frame, "Model tidak ditemukan", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                (0, 0, 255), 2)
                (flag, encodedImage) = cv2.imencode(".jpg", annotated_frame)
                if not flag: continue
                yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + bytearray(encodedImage) + b'\r\n')
        finally:
            cap.release()
            logging.info("SERVER CAM - Koneksi stream ditutup, kamera server dilepaskan.")

    return Response(generate_server_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


# [BARU] Rute untuk menyajikan file video dari direktori recordings
@app.route('/videos/<path:filename>')
def serve_video(filename):
    """Menyajikan file video yang telah direkam."""
    return send_from_directory(RECORDINGS_DIR, filename, as_attachment=False)


# --- ENTRY POINT ---
if __name__ == '__main__':
    print("=====================================================================")
    print("### PERINGATAN ###")
    print("Server ini adalah server pengembangan Flask dan TIDAK UNTUK PRODUKSI.")
    print("Gunakan WSGI server seperti Gunicorn atau uWSGI untuk production.")
    print("Contoh menjalankan dengan Gunicorn:")
    print("gunicorn --workers 1 --threads 10 --bind 0.0.0.0:5000 app:app")
    print("=====================================================================")

    receiver_thread = threading.Thread(target=image_receiver_thread, daemon=True)
    receiver_thread.start()

    logging.info("Memulai server web Flask di http://0.0.0.0:5000")
    # Catatan: use_reloader=False penting saat menggunakan state global/thread seperti ini.
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)