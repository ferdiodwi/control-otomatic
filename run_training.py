# run_training.py
import sys
import os
from ultralytics import YOLO

def train_model(data_yaml_path):
    """
    Fungsi untuk melatih model YOLOv8.
    File ini dijalankan sebagai proses terpisah.
    """
    if not os.path.exists(data_yaml_path):
        print(f"Error: File konfigurasi dataset tidak ditemukan di {data_yaml_path}", file=sys.stderr)
        return

    print("Memuat model pre-trained YOLOv8n...")
    # Load model pre-trained untuk hasil yang lebih baik (transfer learning)
    model = YOLO('yolov8n.pt')

    print(f"Memulai pelatihan dengan dataset dari: {data_yaml_path}")
    print("Hasil akan disimpan di direktori 'runs/train/exp'...")
    
    # Melatih model. Sesuaikan epochs sesuai kebutuhan.
    # 50-100 epochs adalah awal yang baik.
    results = model.train(
        data=data_yaml_path,
        epochs=50,
        imgsz=640,
        project="runs/train",
        name="exp",
        exist_ok=True # Timpa hasil training sebelumnya jika ada
    )
    
    print("\n--- PELATIHAN SELESAI ---")
    print(f"Model terbaik disimpan di: {results.save_dir}/weights/best.pt")

if __name__ == '__main__':
    # Argumen dari baris perintah adalah path ke file data.yaml
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
        train_model(config_path)
    else:
        print("Error: Path ke file data.yaml tidak disediakan.", file=sys.stderr)
        print("Usage: python run_training.py <path_to_data.yaml>")