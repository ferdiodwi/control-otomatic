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

# --- Direktori untuk media mentah ---
IMAGES_DIR = "images"
RECORDINGS_DIR = "recordings"

# --- Direktori untuk media yang telah diproses AI ---
IMAGES_ANNOTATED_DIR = "images_annotated"
RECORDINGS_ANNOTATED_DIR = "recordings_annotated"

# --- Pembuatan Direktori ---
for directory in [IMAGES_DIR, RECORDINGS_DIR, IMAGES_ANNOTATED_DIR, RECORDINGS_ANNOTATED_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

# --- Konfigurasi Lainnya ---
DB_CONFIG = {"dbname": "db_yolo", "user": "postgres", "password": "040303", "host": "localhost", "port": "5433"}
DATASET_EXPORT_PATH = "dataset"
TRAINED_MODEL_PATH = "runs/train/exp/weights/best.pt"
IMAGE_SAVE_INTERVAL_SECONDS = 1
VIDEO_RECORD_DURATION_MINUTES = 1

# --- Konfigurasi untuk penyimpanan media yang diannotasi ---
ANNOTATED_IMAGE_SAVE_INTERVAL_SECONDS = 2
ANNOTATED_VIDEO_RECORD_DURATION_MINUTES = 1

db_pool = ThreadedConnectionPool(minconn=1, maxconn=10, **DB_CONFIG)

latest_frame_data = {
    "frame": None,
    "lock": threading.Lock(),
    "client_name": "unknown_client"
}
training_log_queue = queue.Queue()


def get_db_connection():
    """Mendapatkan koneksi dari pool."""
    return db_pool.getconn()


def release_db_connection(conn):
    """Mengembalikan koneksi ke pool."""
    db_pool.putconn(conn)


# --- FUNGSI DATABASE & HELPER ---

def save_image(conn, client_name, image_frame):
    """
    Menyimpan frame gambar mentah ke folder DAN sebagai data biner ke database.
    """
    try:
        now = datetime.now()
        _, jpg_buffer = cv2.imencode('.jpg', image_frame)
        h, w, _ = image_frame.shape
        aspect_ratio = h / w
        THUMBNAIL_WIDTH = 250
        new_height = int(THUMBNAIL_WIDTH * aspect_ratio)
        thumbnail_frame = cv2.resize(image_frame, (THUMBNAIL_WIDTH, new_height), interpolation=cv2.INTER_AREA)
        _, jpg_buffer_thumbnail = cv2.imencode('.jpg', thumbnail_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])

        timestamp_str = now.strftime("%Y%m%d_%H%M%S_%f")
        image_filename = f"{client_name}_{timestamp_str}.jpg"
        image_filepath = os.path.join(IMAGES_DIR, image_filename)
        cv2.imwrite(image_filepath, image_frame)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO captured_images (client_name, image_data, thumbnail_data, created_at, file_path)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
                """,
                (client_name, psycopg2.Binary(jpg_buffer), psycopg2.Binary(jpg_buffer_thumbnail), now, image_filepath)
            )
            image_id = cur.fetchone()[0]
        conn.commit()
        logging.info(f"Successfully saved raw image to {image_filepath} and as binary data to DB (ID: {image_id}).")
        return image_id
    except Exception as e:
        conn.rollback()
        logging.error(f"Failed to save raw image with hybrid model: {e}")
        return None

def save_annotated_image(conn, client_name, annotated_frame, original_image_id):
    """
    Menyimpan frame yang sudah di-anotasi oleh AI sebagai file fisik dan menyimpan metadatanya.
    """
    try:
        now = datetime.now()
        timestamp_str = now.strftime("%Y%m%d_%H%M%S_%f")
        image_filename = f"{client_name}_annotated_{timestamp_str}.jpg"
        image_filepath = os.path.join(IMAGES_ANNOTATED_DIR, image_filename)
        cv2.imwrite(image_filepath, annotated_frame)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO captured_images_annotated (client_name, file_path, created_at, original_image_id)
                VALUES (%s, %s, %s, %s)
                """,
                (client_name, image_filepath, now, original_image_id)
            )
        conn.commit()
        logging.info(f"Successfully saved annotated image to {image_filepath}.")
    except Exception as e:
        conn.rollback()
        logging.error(f"Failed to save annotated image to DB: {e}")

def save_video_metadata_to_db(conn, client_name, file_path, start_time, end_time, table="recorded_videos"):
    """
    Menyimpan metadata video ke tabel yang ditentukan (bisa untuk video mentah atau beranotasi).
    """
    if not os.path.exists(file_path):
        logging.warning(f"File video tidak ditemukan di path: {file_path}, metadata tidak disimpan.")
        return

    duration = (end_time - start_time).total_seconds()
    file_size = os.path.getsize(file_path) / 1024
    try:
        with conn.cursor() as cur:
            # Validasi nama tabel untuk keamanan
            if table not in ["recorded_videos", "recorded_videos_annotated"]:
                raise ValueError("Invalid table name for saving video metadata")

            cur.execute(
                f"""
                INSERT INTO {table} (client_name, file_path, start_time, end_time, duration_seconds, file_size_kb)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (client_name, file_path, start_time, end_time, int(duration), int(file_size))
            )
        conn.commit()
        logging.info(f"Successfully saved video metadata for {file_path} to table '{table}'.")
    except Exception as e:
        conn.rollback()
        logging.error(f"Failed to save video metadata to DB table '{table}': {e}")


def export_data_for_yolo():
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
                "SELECT DISTINCT i.id, i.file_path FROM captured_images i JOIN annotations a ON i.id = a.image_id WHERE i.file_path IS NOT NULL")
            images = cur.fetchall()
            if not images: return False, "Tidak ada gambar beranotasi (dengan file_path) yang ditemukan untuk diekspor."

            cur.execute("SELECT image_id, class_id, bbox_x, bbox_y, bbox_width, bbox_height FROM annotations")
            all_annotations = cur.fetchall()

        annotations_by_image = {}
        for ann in all_annotations:
            if ann['image_id'] not in annotations_by_image: annotations_by_image[ann['image_id']] = []
            annotations_by_image[ann['image_id']].append(ann)

        class_names = set()
        image_files_to_process = []
        for img_row in images:
            img_id, file_path = img_row['id'], img_row['file_path']
            if not os.path.exists(file_path):
                logging.warning(f"File gambar {file_path} untuk ID {img_id} tidak ditemukan. Dilewati.")
                continue

            nparr = cv2.imread(file_path)
            if nparr is None:
                logging.warning(f"Gagal membaca file gambar {file_path}. Dilewati.")
                continue

            img_h, img_w, _ = nparr.shape
            label_lines = []
            if img_id in annotations_by_image:
                for row in annotations_by_image[img_id]:
                    x_center = (row['bbox_x'] + row['bbox_width'] / 2) / img_w
                    y_center = (row['bbox_y'] + row['bbox_height'] / 2) / img_h
                    width = row['bbox_width'] / img_w
                    height = row['bbox_height'] / img_h
                    class_id = int(row['class_id'])
                    class_names.add(f"class_{class_id}")
                    label_lines.append(f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}")

            image_files_to_process.append({'id': img_id, 'file_path': file_path, 'labels': label_lines})

        split_index = int(len(image_files_to_process) * 0.8)
        train_data, val_data = image_files_to_process[:split_index], image_files_to_process[split_index:]

        for data in train_data:
            shutil.copy(data['file_path'], os.path.join(train_img_path, f"{data['id']}.jpg"))
            with open(os.path.join(train_lbl_path, f"{data['id']}.txt"), 'w') as f: f.write("\n".join(data['labels']))

        for data in val_data:
            shutil.copy(data['file_path'], os.path.join(val_img_path, f"{data['id']}.jpg"))
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


def image_receiver_thread():
    """
    Thread ini HANYA bertanggung jawab menerima frame dari client,
    menyimpannya sebagai media mentah (raw), dan meletakkannya di 'latest_frame_data'
    untuk diproses oleh thread lain.
    """
    logging.info("Image receiver thread started, waiting for client...")
    db_conn = get_db_connection()
    receiver = imagezmq.ImageHub()
    receive_timeout_ms = 2000
    receiver.zmq_socket.setsockopt(zmq.RCVTIMEO, receive_timeout_ms)

    last_image_save_time = time.time()
    video_writer_states = {} # Untuk video mentah

    try:
        while True:
            client_name_recv = "unknown_client"
            try:
                client_name_recv, frame = receiver.recv_image()
                receiver.send_reply(b'OK')

                if frame is None: continue

                with latest_frame_data["lock"]:
                    latest_frame_data["frame"] = frame.copy()
                    latest_frame_data["client_name"] = client_name_recv

                now_datetime = datetime.now()
                current_time = time.time()
                client_state = video_writer_states.get(client_name_recv)

                if not client_state:
                    video_start_time = now_datetime
                    timestamp_str = video_start_time.strftime("%Y%m%d_%H%M%S")
                    video_filename = os.path.join(RECORDINGS_DIR, f"{client_name_recv}_{timestamp_str}.mp4")
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    height, width, _ = frame.shape
                    writer = cv2.VideoWriter(video_filename, fourcc, 20.0, (width, height))
                    video_writer_states[client_name_recv] = {'writer': writer, 'start_time': video_start_time, 'path': video_filename}
                    logging.info(f"Starting new RAW video recording for {client_name_recv}: {video_filename}")

                video_writer_states[client_name_recv]['writer'].write(frame)

                start_time = video_writer_states[client_name_recv]['start_time']
                if (now_datetime - start_time).total_seconds() >= VIDEO_RECORD_DURATION_MINUTES * 60:
                    logging.info(f"Completing RAW video segment for {client_name_recv}: {video_writer_states[client_name_recv]['path']}")
                    video_writer_states[client_name_recv]['writer'].release()
                    save_video_metadata_to_db(db_conn, client_name_recv, video_writer_states[client_name_recv]['path'], start_time, now_datetime, table="recorded_videos")
                    video_writer_states.pop(client_name_recv, None)

                if current_time - last_image_save_time >= IMAGE_SAVE_INTERVAL_SECONDS:
                    save_image(db_conn, client_name_recv, frame)
                    last_image_save_time = current_time

            except zmq.error.Again:
                logging.info("Waiting for new client connection...")
                if client_name_recv and client_name_recv in video_writer_states:
                    logging.warning(f"Client '{client_name_recv}' disconnected. Closing RAW video file: {video_writer_states[client_name_recv]['path']}")
                    state = video_writer_states.pop(client_name_recv)
                    state['writer'].release()
                    save_video_metadata_to_db(db_conn, client_name_recv, state['path'], state['start_time'], datetime.now(), table="recorded_videos")
                with latest_frame_data["lock"]:
                    latest_frame_data["frame"] = None
                time.sleep(1)
                continue

            except Exception as e:
                logging.error(f"Error in image receiver thread: {e}", exc_info=True)
                time.sleep(2)

    finally:
        logging.info("Image receiver thread shutting down. Finalizing all RAW recordings...")
        for client, state in video_writer_states.items():
            state['writer'].release()
            logging.info(f"Finalized RAW recording for {client}: {state['path']}")
            save_video_metadata_to_db(db_conn, client, state['path'], state['start_time'], datetime.now(), table="recorded_videos")
        release_db_connection(db_conn)
        logging.info("Database connection for raw media released.")


def annotated_frame_processor_thread():
    """
    Thread ini mengambil frame terbaru, menjalankan model AI, dan menyimpan hasilnya.
    """
    logging.info("Annotated frame processor thread started.")
    db_conn = get_db_connection()
    model = YOLO(TRAINED_MODEL_PATH) if os.path.exists(TRAINED_MODEL_PATH) else None
    if not model:
        logging.warning("Annotated processor: Model not found. This thread will not save annotated media.")

    video_writer = None
    video_start_time = None
    video_path = None
    last_annotated_image_save_time = time.time()

    try:
        while True:
            frame_copy = None
            client_name = "unknown_client"

            with latest_frame_data["lock"]:
                if latest_frame_data["frame"] is not None:
                    frame_copy = latest_frame_data["frame"].copy()
                    client_name = latest_frame_data["client_name"]

            if frame_copy is None:
                if video_writer:
                    logging.info(f"No active frame. Completing ANNOTATED video segment: {video_path}")
                    video_writer.release()
                    save_video_metadata_to_db(db_conn, client_name, video_path, video_start_time, datetime.now(), table="recorded_videos_annotated")
                    video_writer = None
                time.sleep(1)
                continue

            if not model:
                time.sleep(2)
                continue

            annotated_frame = model(frame_copy, verbose=False)[0].plot()
            now_datetime = datetime.now()
            current_time = time.time()

            if video_writer is None:
                video_start_time = now_datetime
                timestamp_str = video_start_time.strftime("%Y%m%d_%H%M%S")
                video_path = os.path.join(RECORDINGS_ANNOTATED_DIR, f"{client_name}_annotated_{timestamp_str}.mp4")
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                height, width, _ = annotated_frame.shape
                video_writer = cv2.VideoWriter(video_path, fourcc, 20.0, (width, height))
                logging.info(f"Starting new ANNOTATED video recording for {client_name}: {video_path}")

            video_writer.write(annotated_frame)

            if (now_datetime - video_start_time).total_seconds() >= ANNOTATED_VIDEO_RECORD_DURATION_MINUTES * 60:
                logging.info(f"Completing ANNOTATED video segment for {client_name}: {video_path}")
                video_writer.release()
                save_video_metadata_to_db(db_conn, client_name, video_path, video_start_time, now_datetime, table="recorded_videos_annotated")
                video_writer = None

            if current_time - last_annotated_image_save_time >= ANNOTATED_IMAGE_SAVE_INTERVAL_SECONDS:
                save_annotated_image(db_conn, client_name, annotated_frame, original_image_id=None)
                last_annotated_image_save_time = current_time

    finally:
        logging.info("Annotated processor thread shutting down. Finalizing any active recording...")
        if video_writer:
            video_writer.release()
            logging.info(f"Finalized annotated recording: {video_path}")
            save_video_metadata_to_db(db_conn, client_name, video_path, video_start_time, datetime.now(), table="recorded_videos_annotated")
        release_db_connection(db_conn)
        logging.info("Database connection for annotated media released.")


# --- RUTE-RUTE HALAMAN ---
@app.route('/')
def home():
    conn = None
    stats = {'total_images': 0, 'total_videos': 0, 'annotated_images': 0, 'unannotated_images': 0,
             'model_exists': False, 'progress': 0.0}
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
            stats.update({
                'total_images': total_images, 'total_videos': total_videos, 'annotated_images': annotated_images,
                'unannotated_images': total_images - annotated_images
            })
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
def gallery(): return render_template('gallery.html')


@app.route('/data_anotasi')
def data_cleaning_page(): return render_template('data_cleaning.html')


@app.route('/train')
def train_page(): return render_template('train.html')


@app.route('/live_inference')
def live_inference_page(): return render_template('inference.html')


@app.route('/annotate/<int:image_id>')
def annotate(image_id):
    conn = None
    context = request.args.get('context', 'unannotated')
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, file_path FROM captured_images WHERE id = %s", (image_id,))
            image_info = cur.fetchone()
            if not image_info: return "Image not found", 404

            image_path = image_info['file_path']
            if not image_path or not os.path.exists(image_path):
                cur.execute("SELECT image_data FROM captured_images WHERE id = %s", (image_id,))
                img_data_row = cur.fetchone()
                if not img_data_row or not img_data_row['image_data']:
                    return "Image file and image data not found", 404
                image_data = img_data_row['image_data']
            else:
                with open(image_path, "rb") as f:
                    image_data = f.read()

            cur.execute("SELECT * FROM annotations WHERE image_id = %s ORDER BY id", (image_id,))
            annotations = [dict(row) for row in cur.fetchall()]

            nav_ids_query_map = {
                'annotated': "SELECT DISTINCT image_id AS id FROM annotations ORDER BY image_id ASC",
                'unannotated': "SELECT id FROM captured_images WHERE NOT EXISTS (SELECT 1 FROM annotations WHERE image_id = captured_images.id) ORDER BY id ASC"
            }
            cur.execute(nav_ids_query_map.get(context, nav_ids_query_map['unannotated']))
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
    results = []
    for row in rows:
        item = dict(row)
        if 'thumbnail_data' in item and item['thumbnail_data']:
            item['thumbnail_b64'] = base64.b64encode(item['thumbnail_data']).decode('utf-8')
        else:
            item['thumbnail_b64'] = None
        if item.get('timestamp'):
            item['timestamp_str'] = item['timestamp'].strftime('%d %b %Y, %H:%M:%S')
        if item.get('filename'):
            item['filename'] = os.path.basename(item['filename'])
        item.pop('thumbnail_data', None)
        item.pop('image_data', None)
        results.append(item)
    return results


@app.route('/api/gallery_images')
def get_gallery_images():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            query = """
                SELECT
                    'image' as type, id, client_name, thumbnail_data, created_at as timestamp,
                    file_path as filename
                FROM captured_images
                ORDER BY timestamp DESC
                LIMIT %s OFFSET %s;
            """
            cur.execute(query, (per_page, offset))
            media = process_media_rows(cur.fetchall())
        return jsonify(media)
    except Exception as e:
        logging.error(f"Error fetching gallery images: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: release_db_connection(conn)


@app.route('/api/gallery_videos')
def get_gallery_videos():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            query = """
                SELECT
                    'video' as type, id, client_name, NULL as thumbnail_data, start_time as timestamp,
                    file_path as filename
                FROM recorded_videos
                ORDER BY timestamp DESC
                LIMIT %s OFFSET %s;
            """
            cur.execute(query, (per_page, offset))
            media = process_media_rows(cur.fetchall())
        return jsonify(media)
    except Exception as e:
        logging.error(f"Error fetching gallery videos: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: release_db_connection(conn)


@app.route('/api/gallery_images_annotated')
def get_gallery_images_annotated():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            query = """
                SELECT 
                    'image_annotated' as type, id, client_name, NULL as thumbnail_data, created_at as timestamp, 
                    file_path as filename
                FROM captured_images_annotated
                ORDER BY timestamp DESC
                LIMIT %s OFFSET %s;
            """
            cur.execute(query, (per_page, offset))
            media = process_media_rows(cur.fetchall())
        return jsonify(media)
    except Exception as e:
        logging.error(f"Error fetching annotated gallery images: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: release_db_connection(conn)

# [PENAMBAHAN] Endpoint baru untuk mengambil video AI
@app.route('/api/gallery_videos_annotated')
def get_gallery_videos_annotated():
    """Endpoint untuk mengambil daftar video yang sudah diproses AI."""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            query = """
                SELECT
                    'video_annotated' as type, id, client_name, NULL as thumbnail_data, start_time as timestamp,
                    file_path as filename
                FROM recorded_videos_annotated
                ORDER BY timestamp DESC
                LIMIT %s OFFSET %s;
            """
            cur.execute(query, (per_page, offset))
            media = process_media_rows(cur.fetchall())
        return jsonify(media)
    except Exception as e:
        logging.error(f"Error fetching annotated gallery videos: {e}", exc_info=True)
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
    if sort_order.lower() not in ['asc', 'desc']: sort_order = 'desc'

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            base_query = "SELECT id, created_at, thumbnail_data, 'image' as type FROM captured_images i"
            if status == 'unannotated':
                query = f"{base_query} WHERE NOT EXISTS (SELECT 1 FROM annotations a WHERE a.image_id = i.id) ORDER BY i.created_at {sort_order.upper()} LIMIT %s OFFSET %s;"
            else:
                query = f"{base_query} WHERE EXISTS (SELECT 1 FROM annotations a WHERE a.image_id = i.id) ORDER BY i.created_at {sort_order.upper()} LIMIT %s OFFSET %s;"
            cur.execute(query, (per_page, offset))
            images = process_media_rows(cur.fetchall())
        return jsonify(images)
    except Exception as e:
        logging.error(f"Error fetching {status} data: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: release_db_connection(conn)


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
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn: release_db_connection(conn)


@app.route('/api/delete_media/<string:media_type>/<int:media_id>', methods=['DELETE'])
def delete_media(media_type, media_id):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            table_map = {
                'image': 'captured_images', 'video': 'recorded_videos',
                'image_annotated': 'captured_images_annotated',
                'video_annotated': 'recorded_videos_annotated'
            }
            table_name = table_map.get(media_type)
            if not table_name:
                return jsonify({"status": "error", "message": "Tipe media tidak valid"}), 400

            cur.execute(f"SELECT file_path FROM {table_name} WHERE id = %s", (media_id,))
            row = cur.fetchone()
            if row and row[0] and os.path.exists(row[0]):
                os.remove(row[0])
                logging.info(f"File fisik '{row[0]}' telah dihapus.")

            if media_type == 'image':
                cur.execute("DELETE FROM annotations WHERE image_id = %s", (media_id,))
                cur.execute("DELETE FROM captured_images_annotated WHERE original_image_id = %s", (media_id,))

            cur.execute(f"DELETE FROM {table_name} WHERE id = %s", (media_id,))

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
        media_type, ids_to_delete = data.get('media_type'), data.get('ids')
        if not all([media_type, isinstance(ids_to_delete, list)]): return jsonify(
            {"status": "error", "message": "Payload tidak lengkap atau format salah."}), 400
        if not ids_to_delete: return jsonify(
            {"status": "success", "message": "Tidak ada item yang dipilih untuk dihapus."})

        conn = get_db_connection()
        with conn.cursor() as cur:
            id_tuple = tuple(ids_to_delete)
            table_map = {
                'image': 'captured_images', 'video': 'recorded_videos',
                'image_annotated': 'captured_images_annotated',
                'video_annotated': 'recorded_videos_annotated'
            }
            table_name = table_map.get(media_type)

            if not table_name:
                return jsonify({"status": "error", "message": "Tipe media tidak valid"}), 400

            cur.execute(f"SELECT file_path FROM {table_name} WHERE id IN %s", (id_tuple,))
            for row in cur.fetchall():
                if row and row[0] and os.path.exists(row[0]):
                    os.remove(row[0])

            if media_type == 'image':
                cur.execute("DELETE FROM annotations WHERE image_id IN %s", (id_tuple,))
                cur.execute("DELETE FROM captured_images_annotated WHERE original_image_id IN %s", (id_tuple,))

            cur.execute(f"DELETE FROM {table_name} WHERE id IN %s", (id_tuple,))
            deleted_count = cur.rowcount

        conn.commit()
        return jsonify({"status": "success", "message": f"{deleted_count} {media_type.replace('_', ' ')} berhasil dihapus."})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn: release_db_connection(conn)


def run_training_in_thread(yaml_path):
    try:
        command = [sys.executable, '-u', 'run_training.py', yaml_path]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   encoding='utf-8', errors='replace')
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
        while not training_log_queue.empty(): training_log_queue.get()
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
                if latest_frame_data["frame"] is not None:
                    frame = latest_frame_data["frame"].copy()

            if frame is None:
                placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(placeholder, "Menunggu stream dari client...", (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1,
                            (255, 255, 255), 2)
                (flag, encodedImage) = cv2.imencode(".jpg", placeholder)
                yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + bytearray(encodedImage) + b'\r\n')
                time.sleep(1)
                continue

            if model:
                annotated_frame = model(frame, verbose=False)[0].plot()
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
                if not success: break

                if model:
                    annotated_frame = model(frame, verbose=False)[0].plot()
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


@app.route('/videos_annotated/<path:filename>')
def serve_annotated_video(filename):
    """Menyajikan file video yang telah direkam dan diannotasi."""
    return send_from_directory(RECORDINGS_ANNOTATED_DIR, filename)

@app.route('/images_annotated/<path:filename>')
def serve_annotated_image(filename):
    """Menyajikan file gambar yang telah disimpan dan diannotasi."""
    return send_from_directory(IMAGES_ANNOTATED_DIR, filename)


@app.route('/videos/<path:filename>')
def serve_video(filename):
    """Menyajikan file video mentah yang telah direkam."""
    return send_from_directory(RECORDINGS_DIR, filename)


@app.route('/images/<path:filename>')
def serve_image(filename):
    """Menyajikan file gambar mentah yang telah disimpan."""
    return send_from_directory(IMAGES_DIR, filename)


# --- ENTRY POINT ---
if __name__ == '__main__':
    print("=====================================================================")
    print("### PERINGATAN ###")
    print("Server ini adalah server pengembangan Flask dan TIDAK UNTUK PRODUKSI.")
    print("=====================================================================")

    receiver_thread = threading.Thread(target=image_receiver_thread, daemon=True)
    receiver_thread.start()

    processor_thread = threading.Thread(target=annotated_frame_processor_thread, daemon=True)
    processor_thread.start()

    logging.info("Memulai server web Flask di http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)