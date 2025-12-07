import sys
import time
import os
import math
from PyQt6.QtWidgets import (QApplication, QMainWindow, QFileDialog, QLabel, 
                             QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QMessageBox, 
                             QSplashScreen, QListWidget, QListWidgetItem, QButtonGroup)
from PyQt6.QtGui import QPixmap, QImage, QFont, QColor, QKeyEvent
from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF
import numpy as np

# 自作モジュールのインポート
from gui.canvas import ImageCanvas
from core.loader import DicomScanWorker, SeriesLoadWorker

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
            "Loading DICOM Libraries... DONE",
            "Importing Graphic Engine (gui.canvas)... OK",
            "Importing Asynchronous Loader (core.loader)... OK",
            "Initializing Measurement System...",
            "  - Linear Ruler: ONLINE",
            "  - Elliptical ROI: ONLINE",
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

class ZetaViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Project Z.E.T.A. - Clinical Edition (Stable)")
        self.resize(1400, 900)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        self.all_series_data = {} 
        self.current_slices = []
        self.current_index = 0
        
        self.window_level = 40
        self.window_width = 400
        
        self.last_mouse_pos = None
        self.drag_accumulator = 0
        
        # モード管理 (0:Nav, 1:Ruler, 2:ROI)
        self.current_tool_mode = 0 
        
        self.scan_worker = None
        self.load_worker = None

        self.setup_ui()
        self.apply_styles()

    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        self.left_panel = QWidget()
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_panel.setFixedWidth(280)
        
        self.mode_label = QLabel("CONTROLLER MODE")
        self.left_layout.addWidget(self.mode_label)
        
        self.btn_nav = QPushButton("NAVIGATE")
        self.btn_nav.setCheckable(True)
        self.btn_nav.setChecked(True)
        self.btn_nav.clicked.connect(lambda: self.set_mode(0))
        
        self.btn_ruler = QPushButton("RULER (DIST)")
        self.btn_ruler.setCheckable(True)
        self.btn_ruler.clicked.connect(lambda: self.set_mode(1))

        self.btn_roi = QPushButton("ROI (ELLIPSE)")
        self.btn_roi.setCheckable(True)
        self.btn_roi.clicked.connect(lambda: self.set_mode(2))
        
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_nav)
        self.mode_group.addButton(self.btn_ruler)
        self.mode_group.addButton(self.btn_roi)
        
        self.left_layout.addWidget(self.btn_nav)
        self.left_layout.addWidget(self.btn_ruler)
        self.left_layout.addWidget(self.btn_roi)
        self.left_layout.addSpacing(20)
        
        self.series_label = QLabel("SERIES LIST")
        self.left_layout.addWidget(self.series_label)
        self.series_list_widget = QListWidget()
        self.series_list_widget.itemClicked.connect(self.on_series_clicked) 
        self.left_layout.addWidget(self.series_list_widget)
        
        self.open_btn = QPushButton("OPEN FOLDER")
        self.open_btn.clicked.connect(self.open_folder_dialog)
        self.left_layout.addWidget(self.open_btn)
        
        self.main_layout.addWidget(self.left_panel)

        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        
        self.header_label = QLabel("MODE: NAVIGATION | R-DRAG: W/L | L-DRAG: PAN")
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.right_layout.addWidget(self.header_label)

        self.image_canvas = ImageCanvas()
        self.right_layout.addWidget(self.image_canvas, 1)

        self.info_label = QLabel("WAITING FOR INPUT...")
        self.right_layout.addWidget(self.info_label)

        self.main_layout.addWidget(self.right_panel, 1)

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #050505; }
            QLabel { color: #00FF00; font-family: 'Consolas'; } 
            QListWidget {
                background-color: #111; border: 1px solid #005500; color: #00DD00; font-family: 'Consolas';
            }
            QListWidget::item:selected { background-color: #004400; color: #FFFFFF; }
            QPushButton { 
                background-color: #1a1a1a; color: #00FF00; border: 1px solid #005500; padding: 8px; font-family: 'Consolas'; font-weight: bold;
            }
            QPushButton:hover { background-color: #003300; }
            QPushButton:checked { background-color: #FFFF00; color: #000000; border: 1px solid #FFFF00; }
        """)

    def set_mode(self, mode):
        self.current_tool_mode = mode
        self.image_canvas.selected_index = None
        self.image_canvas.selected_type = None
        self.image_canvas.update()
        
        if mode == 0:
            self.header_label.setText("MODE: NAVIGATION | R-DRAG: W/L | L-DRAG: PAN")
            self.header_label.setStyleSheet("color: #00FF00;")
        elif mode == 1:
            self.header_label.setText("MODE: RULER | L-DRAG: DRAW DISTANCE")
            self.header_label.setStyleSheet("color: #FFFF00;")
        elif mode == 2:
            self.header_label.setText("MODE: ROI | L-DRAG: DRAW ELLIPSE")
            self.header_label.setStyleSheet("color: #00FFFF;")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.accept()
        else: event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if os.path.isdir(path): self.start_folder_scan(path)
            elif os.path.isfile(path): self.start_folder_scan(os.path.dirname(path))

    def open_folder_dialog(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Select DICOM Folder")
        if folder_path: self.start_folder_scan(folder_path)

    def start_folder_scan(self, folder_path):
        self.info_label.setText(f"SCANNING (Background Task): {folder_path} ...")
        self.series_list_widget.clear()
        self.image_canvas.set_pixmap(None)
        
        self.scan_worker = DicomScanWorker(folder_path)
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.error.connect(self.on_worker_error)
        self.scan_worker.start()

    def on_scan_finished(self, series_info, message):
        self.all_series_data = series_info
        self.info_label.setText(message)
        
        for uid, info in series_info.items():
            count = len(info['files'])
            item = QListWidgetItem(f"[{info['modality']}] {info['desc']} ({count})")
            item.setData(Qt.ItemDataRole.UserRole, uid) 
            self.series_list_widget.addItem(item)
            
        if self.series_list_widget.count() > 0:
            self.series_list_widget.setCurrentRow(0)
            self.on_series_clicked(self.series_list_widget.item(0))

    def on_series_clicked(self, item):
        uid = item.data(Qt.ItemDataRole.UserRole)
        target_files = self.all_series_data[uid]['files']
        desc = self.all_series_data[uid]['desc']
        
        self.info_label.setText(f"LOADING SERIES (0%): {desc}...")
        self.image_canvas.set_pixmap(None) 
        
        self.load_worker = SeriesLoadWorker(target_files)
        self.load_worker.progress.connect(self.on_load_progress)
        self.load_worker.finished.connect(self.on_load_finished)
        self.load_worker.start()

    def on_load_progress(self, percent):
        self.info_label.setText(f"LOADING SERIES... {percent}%")

    def on_load_finished(self, slices, pixel_spacing):
        self.current_slices = slices
        self.current_index = 0
        self.image_canvas.reset_view()
        self.image_canvas.pixel_spacing = pixel_spacing
        
        if slices:
            ds = slices[0]
            if 'WindowCenter' in ds and 'WindowWidth' in ds:
                # pydicomのMultiValue対策
                from pydicom.multival import MultiValue
                wc = ds.WindowCenter
                ww = ds.WindowWidth
                
                # リストなら最初の値、単一ならそのまま
                self.window_level = float(wc[0]) if isinstance(wc, (list, MultiValue)) else float(wc)
                self.window_width = float(ww[0]) if isinstance(ww, (list, MultiValue)) else float(ww)
            else:
                self.window_level = 40
                self.window_width = 400
        
        self.update_display()
        self.info_label.setText("LOAD complete.")

    def on_worker_error(self, message):
        self.info_label.setText(f"ERROR: {message}")
        QMessageBox.warning(self, "Error", message)

    def update_display(self):
        if not self.current_slices: return
        ds = self.current_slices[self.current_index]
        pid = ds.PatientID if 'PatientID' in ds else 'UNKNOWN'
        
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
            
            # 生データ(hu_image)も渡す(ROI計算用)
            self.image_canvas.set_pixmap(pixmap, self.image_canvas.pixel_spacing, self.current_index, hu_image)
            
            self.info_label.setText(f"ID: {pid} | WL: {int(self.window_level)} WW: {int(self.window_width)} | SLICE: {self.current_index + 1}/{len(self.current_slices)}")
            
        except Exception as e:
            self.info_label.setText(f"RENDER ERROR: {str(e)}")

    def keyPressEvent(self, event: QKeyEvent):
        if self.current_tool_mode in [1, 2]:
            if event.key() == Qt.Key.Key_Delete or event.key() == Qt.Key.Key_Backspace:
                if self.image_canvas.delete_selected_measurement():
                    self.info_label.setText("Measurement deleted.")
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        self.last_mouse_pos = event.position()
        self.drag_accumulator = 0
        
        if self.current_tool_mode in [1, 2] and (event.buttons() & Qt.MouseButton.LeftButton):
            canvas_pos = self.image_canvas.mapFrom(self, event.position().toPoint())
            hit_type, hit_index = self.image_canvas.hit_test(canvas_pos)
            
            if hit_index is not None:
                self.image_canvas.selected_type = hit_type
                self.image_canvas.selected_index = hit_index
                self.image_canvas.update()
                type_str = "Ruler" if hit_type == 'ruler' else "ROI"
                self.info_label.setText(f"{type_str} selected. Press DELETE to remove.")
            else:
                self.image_canvas.selected_index = None
                self.image_canvas.selected_type = None
                img_pos = self.image_canvas.screen_to_image(canvas_pos)
                if img_pos:
                    self.image_canvas.current_drawing_start = img_pos
                    self.image_canvas.current_drawing_end = img_pos
                    self.image_canvas.current_mode = 'ruler' if self.current_tool_mode == 1 else 'roi'
                    self.image_canvas.update()

    def mouseMoveEvent(self, event):
        if self.last_mouse_pos is None: return
        current_pos = event.position()
        delta_x = current_pos.x() - self.last_mouse_pos.x()
        delta_y = current_pos.y() - self.last_mouse_pos.y()
        
        if self.current_tool_mode in [1, 2] and (event.buttons() & Qt.MouseButton.LeftButton):
             if self.image_canvas.current_drawing_start:
                canvas_pos = self.image_canvas.mapFrom(self, current_pos.toPoint())
                img_pos = self.image_canvas.screen_to_image(canvas_pos)
                if img_pos:
                    self.image_canvas.current_drawing_end = img_pos
                    self.image_canvas.update()
        elif event.buttons() & Qt.MouseButton.RightButton:
            self.adjust_wl(delta_x, delta_y)
        elif event.buttons() & Qt.MouseButton.MiddleButton:
            self.paging(delta_y)
        elif self.current_tool_mode == 0 and (event.buttons() & Qt.MouseButton.LeftButton):
            self.image_canvas.pan_x += delta_x
            self.image_canvas.pan_y += delta_y
            self.image_canvas.update()
        self.last_mouse_pos = current_pos

    def mouseReleaseEvent(self, event):
        if self.current_tool_mode in [1, 2] and (event.button() == Qt.MouseButton.LeftButton):
            c = self.image_canvas
            if c.current_drawing_start and c.current_drawing_end:
                dx = c.current_drawing_end.x() - c.current_drawing_start.x()
                dy = c.current_drawing_end.y() - c.current_drawing_start.y()
                dist_px = math.sqrt(dx**2 + dy**2)
                
                if dist_px > 2: 
                    if self.current_tool_mode == 1: # Ruler
                        if c.pixel_spacing:
                            dist_mm = dist_px * c.pixel_spacing[0]
                            text = f"{dist_mm:.2f} mm"
                        else:
                            text = f"{dist_px:.1f} px"
                        c.measurements.append({
                            'start': c.current_drawing_start, 'end': c.current_drawing_end,
                            'dist_text': text, 'slice_index': self.current_index
                        })
                        c.selected_type = 'ruler'; c.selected_index = len(c.measurements) - 1
                        
                    elif self.current_tool_mode == 2: # ROI
                        rect_img = QRectF(c.current_drawing_start, c.current_drawing_end).normalized()
                        stats = c.calculate_roi_stats(rect_img)
                        if stats != "N/A":
                            mean, std, mx, mn, area = stats
                            text = f"Mean:{mean:.1f} SD:{std:.1f}\nMax:{mx:.0f} Min:{mn:.0f}\nArea:{area:.0f}mm2"
                        else:
                            text = "Error"
                        c.rois.append({
                            'rect': rect_img, 'text': text, 'slice_index': self.current_index
                        })
                        c.selected_type = 'roi'; c.selected_index = len(c.rois) - 1

                c.current_drawing_start = None; c.current_drawing_end = None; c.current_mode = None; c.update()
        self.last_mouse_pos = None

    def adjust_wl(self, dx, dy):
        if self.current_slices:
            self.window_width = max(1, self.window_width + dx)
            self.window_level += dy
            self.update_display()

    def paging(self, dy):
        if self.current_slices:
            self.drag_accumulator += dy
            threshold = 15
            if abs(self.drag_accumulator) > threshold:
                steps = int(self.drag_accumulator / threshold)
                if steps != 0:
                    self.current_index = int(np.clip(self.current_index + steps, 0, len(self.current_slices) - 1))
                    self.update_display()
                    self.drag_accumulator -= (steps * threshold)

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