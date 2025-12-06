import sys
import time
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QFileDialog, QLabel, 
                             QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QMessageBox, 
                             QSplashScreen, QSizePolicy, QListWidget, QListWidgetItem)
from PyQt6.QtGui import QPixmap, QImage, QFont, QColor, QPainter
from PyQt6.QtCore import Qt, QPoint
import pydicom
import numpy as np

# --- 1. スプラッシュスクリーン (変更なし) ---
class ZetaSplashScreen(QSplashScreen):
    def __init__(self):
        pixmap = QPixmap(800, 500)
        pixmap.fill(QColor("#000000"))
        super().__init__(pixmap)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.font_console = QFont("Consolas", 11) 
        self.font_logo = QFont("Impact", 48, QFont.Weight.Bold)
        self.logs = [] 
        self.max_lines = 18 
        self.boot_sequence = [
            "Initializing kernel...",
            "Loading Neural Linkage...",
            "Checking GPU Architecture (RTX Series)... DETECTED",
            "Loading DICOM Libraries (pydicom/numpy)... DONE",
            "Initializing Custom Rendering Engine...",
            "Calibrating Middle-Mouse Sensors...", # 更新
            "Activating Smooth-Paging Accumulator...", # 更新
            "Locking Layout Geometry...",
            "System Configure: CLINICAL MODE",
            "----------------------------------------",
            "Z.E.T.A. SYSTEM BOOT SEQUENCE",
            "----------------------------------------",
            "Waiting for user input...",
            "SYSTEM ONLINE."
        ]

    def drawContents(self, painter):
        painter.fillRect(self.rect(), QColor("#000000"))
        painter.setFont(self.font_console)
        painter.setPen(QColor("#00FF00"))
        y = 40
        for log in self.logs[-self.max_lines:]:
            painter.drawText(30, y, log)
            y += 24
        if len(self.logs) >= len(self.boot_sequence):
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(self.font_logo)
            rect = self.rect()
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Z.E.T.A.")
            painter.setFont(QFont("Arial", 12))
            painter.setPen(QColor("#AAAAAA"))
            painter.drawText(rect.adjusted(0, 70, 0, 0), Qt.AlignmentFlag.AlignCenter, 
                             "Zero-latency Executive Tomography Algorithm")

    def progress(self):
        if self.boot_sequence:
            line = self.boot_sequence.pop(0)
            self.logs.append(line)
            self.repaint()
            return True
        return False

# --- 2. 画像表示専用カスタムウィジェット ---
class ImageCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = None
        self.pan_x = 0
        self.pan_y = 0
        self.setStyleSheet("background-color: #000000;")
        # ★重要: マウスイベントを親に渡さずここで処理する手もあるが、
        # 今回は親(ZetaViewer)で一括管理するため、透過設定にする
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True) 

    def set_pixmap(self, pixmap):
        self.pixmap = pixmap
        self.update()

    def reset_view(self):
        self.pan_x = 0
        self.pan_y = 0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))

        if self.pixmap is None:
            painter.setPen(QColor("#003300"))
            painter.setFont(QFont("Consolas", 14))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "[ NO SIGNAL ]")
            return

        win_w = self.width()
        win_h = self.height()
        img_w = self.pixmap.width()
        img_h = self.pixmap.height()

        scale_w = win_w / img_w
        scale_h = win_h / img_h
        scale = min(scale_w, scale_h)

        draw_w = int(img_w * scale)
        draw_h = int(img_h * scale)

        pos_x = (win_w - draw_w) // 2 + self.pan_x
        pos_y = (win_h - draw_h) // 2 + self.pan_y

        painter.drawPixmap(
            int(pos_x), int(pos_y), 
            int(draw_w), int(draw_h), 
            self.pixmap
        )

# --- 3. メインウィンドウ (コクピット) ---
class ZetaViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Project Z.E.T.A. - PACS Console")
        self.resize(1400, 900)
        self.setAcceptDrops(True)
        
        # データ保持用
        self.all_series_data = {} 
        self.current_slices = []
        self.current_index = 0
        
        # 状態管理
        self.window_level = 40
        self.window_width = 400
        self.last_mouse_pos = None
        
        # ★修正: ホイールドラッグ用の移動量蓄積変数
        self.drag_accumulator = 0
        
        # スタイル設定
        self.setStyleSheet("""
            QMainWindow { background-color: #050505; }
            QLabel { color: #00FF00; font-family: 'Consolas'; } 
            QListWidget {
                background-color: #111;
                border: 1px solid #005500;
                color: #00DD00;
                font-family: 'Consolas';
                font-size: 13px;
            }
            QListWidget::item:selected {
                background-color: #004400;
                color: #FFFFFF;
            }
            QPushButton { 
                background-color: #1a1a1a; 
                color: #00FF00; 
                border: 1px solid #005500;
                padding: 10px;
                font-family: 'Consolas';
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #003300; }
        """)

        # UI構築
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        # --- 左パネル ---
        self.left_panel = QWidget()
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_panel.setFixedWidth(280)
        
        self.series_label = QLabel("SERIES LIST")
        self.left_layout.addWidget(self.series_label)
        
        self.series_list_widget = QListWidget()
        self.series_list_widget.itemClicked.connect(self.on_series_clicked) 
        self.left_layout.addWidget(self.series_list_widget)
        
        self.open_btn = QPushButton("OPEN FOLDER")
        self.open_btn.clicked.connect(self.open_folder_dialog)
        self.left_layout.addWidget(self.open_btn)
        
        self.main_layout.addWidget(self.left_panel)

        # --- 右パネル ---
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        
        self.header_label = QLabel("R-DRAG: W/L | L-DRAG: PAN | M-DRAG: PAGE")
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.right_layout.addWidget(self.header_label)

        # 画像キャンバス
        self.image_canvas = ImageCanvas()
        # ★ キャンバス上のマウスイベントを透過させて、Main Windowで受け取る
        self.image_canvas.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.right_layout.addWidget(self.image_canvas, 1)

        self.info_label = QLabel("WAITING FOR INPUT...")
        self.right_layout.addWidget(self.info_label)

        self.main_layout.addWidget(self.right_panel, 1)

    # --- ドラッグ＆ドロップ ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.accept()
        else: event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if os.path.isdir(path): self.load_volume(path)
            elif os.path.isfile(path): self.load_volume(os.path.dirname(path))

    # --- ★マウス操作イベント (PACS仕様・修正版) ---
    def mousePressEvent(self, event):
        self.last_mouse_pos = event.position()
        # ドラッグ開始時にアキュムレータをリセット
        self.drag_accumulator = 0

    def mouseMoveEvent(self, event):
        if self.last_mouse_pos is None:
            return

        current_pos = event.position()
        delta_x = current_pos.x() - self.last_mouse_pos.x()
        delta_y = current_pos.y() - self.last_mouse_pos.y()
        
        # --- [右ドラッグ] Window / Level 調整 ---
        if event.buttons() & Qt.MouseButton.RightButton:
            if self.current_slices:
                sensitivity = 1.0
                self.window_width += delta_x * sensitivity
                self.window_level += delta_y * sensitivity
                self.window_width = max(1, self.window_width)
                self.update_display()
            self.last_mouse_pos = current_pos

        # --- [左ドラッグ] パン (平行移動) ---
        elif event.buttons() & Qt.MouseButton.LeftButton:
            if self.current_slices:
                self.image_canvas.pan_x += delta_x
                self.image_canvas.pan_y += delta_y
                self.image_canvas.update()
            self.last_mouse_pos = current_pos

        # --- [中ドラッグ (ホイールドラッグ)] ページング (修正版) ---
        elif event.buttons() & Qt.MouseButton.MiddleButton:
            if self.current_slices:
                # 移動量を蓄積する
                self.drag_accumulator += delta_y
                
                # 閾値 (何ピクセル動いたら1枚めくるか)
                threshold = 15 # この値を小さくすると敏感になり、大きくすると鈍感になります
                
                # 蓄積量が閾値を超えたらページをめくる
                if abs(self.drag_accumulator) > threshold:
                    # めくる枚数を計算 (速く動かしたときは複数枚めくる)
                    steps = int(self.drag_accumulator / threshold)
                    
                    if steps != 0:
                        self.current_index = int(np.clip(self.current_index + steps, 0, len(self.current_slices) - 1))
                        self.update_display()
                        
                        # アキュムレーターから消費分を引く (余りを持越すことで滑らかにする)
                        self.drag_accumulator -= (steps * threshold)
            
            # ホイールドラッグ時は last_mouse_pos を更新してはいけない
            # (更新すると delta_y が毎回 0 付近になり、蓄積できないため)
            self.last_mouse_pos = current_pos

    def mouseReleaseEvent(self, event):
        self.last_mouse_pos = None

    # --- フォルダ読み込み処理 ---
    def open_folder_dialog(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Select DICOM Folder")
        if folder_path: self.load_volume(folder_path)

    def load_volume(self, folder_path):
        self.info_label.setText(f"SCANNING: {folder_path}")
        self.series_list_widget.clear()
        self.all_series_data = {}
        self.current_slices = []
        self.image_canvas.set_pixmap(None)
        QApplication.processEvents()
        
        try:
            files = os.listdir(folder_path)
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e)); return
        
        temp_series_info = {} 
        for f in files:
            full_path = os.path.join(folder_path, f)
            if os.path.isdir(full_path): continue
            try:
                ds = pydicom.dcmread(full_path, stop_before_pixels=True)
                uid = ds.SeriesInstanceUID if 'SeriesInstanceUID' in ds else 'Unknown'
                desc = ds.SeriesDescription if 'SeriesDescription' in ds else 'No Description'
                modality = ds.Modality if 'Modality' in ds else '??'
                if uid not in temp_series_info:
                    temp_series_info[uid] = {'desc': desc, 'modality': modality, 'files': []}
                temp_series_info[uid]['files'].append(full_path)
            except: continue 

        if not temp_series_info:
            QMessageBox.warning(self, "WARNING", "No DICOM files found."); return

        self.all_series_data = temp_series_info
        for uid, info in temp_series_info.items():
            count = len(info['files'])
            item = QListWidgetItem(f"[{info['modality']}] {info['desc']} ({count})")
            item.setData(Qt.ItemDataRole.UserRole, uid) 
            self.series_list_widget.addItem(item)
        
        self.info_label.setText(f"FOUND {len(temp_series_info)} SERIES.")
        if self.series_list_widget.count() > 0:
            self.series_list_widget.setCurrentRow(0)
            self.on_series_clicked(self.series_list_widget.item(0))

    def on_series_clicked(self, item):
        uid = item.data(Qt.ItemDataRole.UserRole)
        target_files = self.all_series_data[uid]['files']
        desc = self.all_series_data[uid]['desc']
        self.info_label.setText(f"LOADING SERIES: {desc}...")
        QApplication.processEvents()

        loaded_slices = []
        for f_path in target_files:
            try:
                ds = pydicom.dcmread(f_path)
                if hasattr(ds, 'PixelData'): loaded_slices.append(ds)
            except: pass
        
        try: loaded_slices.sort(key=lambda x: int(x.InstanceNumber))
        except: loaded_slices.sort(key=lambda x: x.filename)

        self.current_slices = loaded_slices
        self.current_index = 0
        self.image_canvas.reset_view()

        if loaded_slices:
            ds = loaded_slices[0]
            if 'WindowCenter' in ds and 'WindowWidth' in ds:
                wc = ds.WindowCenter
                ww = ds.WindowWidth
                self.window_level = wc[0] if isinstance(wc, pydicom.multival.MultiValue) else wc
                self.window_width = ww[0] if isinstance(ww, pydicom.multival.MultiValue) else ww
            else:
                self.window_level = 40
                self.window_width = 400
        
        self.update_display()

    def update_display(self):
        if not self.current_slices: return
        ds = self.current_slices[self.current_index]
        pid = ds.PatientID if 'PatientID' in ds else 'UNKNOWN'
        self.info_label.setText(f"ID: {pid} | WL: {int(self.window_level)} WW: {int(self.window_width)} | SLICE: {self.current_index + 1}/{len(self.current_slices)}")

        try:
            pixel_array = ds.pixel_array.astype(np.float32)
            slope = getattr(ds, 'RescaleSlope', 1)
            intercept = getattr(ds, 'RescaleIntercept', 0)
            hu_image = pixel_array * slope + intercept
            
            min_visible = self.window_level - (self.window_width / 2.0)
            max_visible = self.window_level + (self.window_width / 2.0)
            img_windowed = np.clip(hu_image, min_visible, max_visible)
            img_normalized = ((img_windowed - min_visible) / (max_visible - min_visible) * 255).astype(np.uint8)

            height, width = img_normalized.shape
            q_img = QImage(img_normalized.data, width, height, width, QImage.Format.Format_Grayscale8)
            pixmap = QPixmap.fromImage(q_img)
            self.image_canvas.set_pixmap(pixmap)
            
        except Exception as e:
            self.info_label.setText(f"RENDER ERROR: {str(e)}")

    # --- ホイール回転 (これもページ送りとして残す) ---
    def wheelEvent(self, event):
        if not self.current_slices: return
        delta = event.angleDelta().y()
        if delta > 0: self.current_index = max(0, self.current_index - 1)
        else: self.current_index = min(len(self.current_slices) - 1, self.current_index + 1)
        self.update_display()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    splash = ZetaSplashScreen()
    splash.show()
    for _ in range(15):
        if not splash.progress(): break
        time.sleep(0.1)
        app.processEvents()
    time.sleep(1.0)
    window = ZetaViewer()
    window.show()
    splash.finish(window)
    sys.exit(app.exec())