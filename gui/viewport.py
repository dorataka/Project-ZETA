import numpy as np
import pydicom
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
# ★修正: QRectF を追加しました
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QRectF
from PyQt6.QtGui import QImage, QPixmap, QColor, QPalette

from gui.canvas import ImageCanvas
from core.loader import SeriesLoadWorker

class ZetaViewport(QFrame):
    # シグナル定義
    activated = pyqtSignal(object, object)
    series_dropped = pyqtSignal(object, str)
    
    # 同期用シグナル
    scrolled = pyqtSignal(object, int)          # ページング
    panned = pyqtSignal(object, int, int)       # パン (dx, dy)
    wl_changed = pyqtSignal(object, float, float) # WL/WW (delta_width, delta_level)
    zoomed = pyqtSignal(object, float)          # ズーム (delta_factor)

    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(2)
        self.setAcceptDrops(True)
        self.set_active(False)

        # データ管理
        self.current_slices = []
        self.current_index = 0
        self.window_level = 40
        self.window_width = 400
        self.current_tool_mode = 0 
        
        self.load_worker = None
        self.last_mouse_pos = None
        self.drag_accumulator = 0

        # UI構築
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.canvas = ImageCanvas()
        self.layout.addWidget(self.canvas)

    def set_active(self, active: bool):
        self.is_active = active
        if active:
            self.setStyleSheet("border: 2px solid #00FF00;") 
        else:
            self.setStyleSheet("border: 1px solid #333333;")

    # --- 外部からの操作適用 (同期用) ---
    def apply_scroll(self, steps):
        if not self.current_slices: return
        new_index = int(np.clip(self.current_index + steps, 0, len(self.current_slices) - 1))
        if new_index != self.current_index:
            self.current_index = new_index
            self.update_display()

    # --- scroll_step (Main Windowからの呼び出し互換) ---
    def scroll_step(self, steps, emit_sync=True):
        if not self.current_slices: return
        new_index = int(np.clip(self.current_index + steps, 0, len(self.current_slices) - 1))
        
        if new_index != self.current_index:
            self.current_index = new_index
            self.update_display()
            if emit_sync:
                self.scrolled.emit(self, steps)

    def apply_pan(self, dx, dy):
        self.canvas.pan_x += dx
        self.canvas.pan_y += dy
        self.canvas.update()

    def apply_wl(self, dw, dl):
        self.window_width = max(1, self.window_width + dw)
        self.window_level += dl
        self.update_display()

    def apply_zoom(self, delta_factor):
        if hasattr(self.canvas, 'zoom_factor'):
            new_zoom = self.canvas.zoom_factor + delta_factor
            self.canvas.zoom_factor = max(0.1, min(10.0, new_zoom))
            self.canvas.update()

    # --- ドラッグ＆ドロップ ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-zeta-series-uid"):
            event.accept()
            self.setStyleSheet("border: 2px dashed #FFFFFF;")
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.set_active(self.is_active)

    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-zeta-series-uid"):
            byte_data = event.mimeData().data("application/x-zeta-series-uid")
            uid = byte_data.data().decode('utf-8')
            self.series_dropped.emit(self, uid)
            event.accept()
            self.set_active(True)
        else:
            event.ignore()

    # --- 機能 ---
    def set_tool_mode(self, mode):
        self.current_tool_mode = mode
        self.canvas.selected_index = None
        self.canvas.selected_type = None
        self.canvas.update()

    def delete_measurement(self):
        return self.canvas.delete_selected_measurement()

    def load_series(self, file_paths):
        if 'BL' not in self.canvas.overlay_data: self.canvas.overlay_data['BL'] = []
        self.canvas.overlay_data['BL'] = ["LOADING..."]
        self.canvas.update()
        if self.load_worker and self.load_worker.isRunning():
            self.load_worker.terminate()
        self.load_worker = SeriesLoadWorker(file_paths)
        self.load_worker.finished.connect(self.on_load_finished)
        self.load_worker.start()

    def on_load_finished(self, slices, pixel_spacing):
        self.current_slices = slices
        self.current_index = 0
        self.canvas.reset_view()
        self.canvas.pixel_spacing = pixel_spacing
        if slices:
            ds = slices[0]
            wc = ds.get('WindowCenter', 40)
            ww = ds.get('WindowWidth', 400)
            try:
                from pydicom.multival import MultiValue
                self.window_level = float(wc[0]) if isinstance(wc, (list, MultiValue)) else float(wc)
                self.window_width = float(ww[0]) if isinstance(ww, (list, MultiValue)) else float(ww)
            except:
                self.window_level = 40
                self.window_width = 400
        self.update_display()

    def update_display(self):
        if not self.current_slices: return
        self.current_index = max(0, min(self.current_index, len(self.current_slices) - 1))
        ds = self.current_slices[self.current_index]
        try:
            pixel_array = ds.pixel_array.astype(np.float32)
            slope = float(getattr(ds, 'RescaleSlope', 1.0))
            intercept = float(getattr(ds, 'RescaleIntercept', 0.0))
            hu_image = pixel_array * slope + intercept
            min_v = self.window_level - (self.window_width / 2.0)
            max_v = self.window_level + (self.window_width / 2.0)
            img_windowed = np.clip(hu_image, min_v, max_v)
            img_norm = ((img_windowed - min_v) / (max_v - min_v) * 255).astype(np.uint8)
            h, w = img_norm.shape
            q_img = QImage(img_norm.data.tobytes(), w, h, w, QImage.Format.Format_Grayscale8)
            pixmap = QPixmap.fromImage(q_img)
            
            overlay_info = self.create_overlay_info(ds)
            # ズーム倍率表示
            if hasattr(self.canvas, 'zoom_factor'):
                zoom = self.canvas.zoom_factor
                if 'BL' in overlay_info:
                    overlay_info['BL'].append(f"Zoom: {zoom:.1f}x")
            
            self.canvas.set_pixmap(pixmap, self.canvas.pixel_spacing, self.current_index, hu_image, overlay_data=overlay_info)
        except Exception as e:
            print(f"Render Error: {e}")

    def create_overlay_info(self, ds):
        def get_tag(tag, default=""): return str(ds.get(tag, default))
        age = get_tag('PatientAge'); sex = get_tag('PatientSex')
        date = get_tag('StudyDate'); time_str = get_tag('StudyTime')
        if len(date)==8: date = f"{date[:4]}/{date[4:6]}/{date[6:]}"
        if len(time_str)>=4: time_str = f"{time_str[:2]}:{time_str[2:4]}"
        slice_info = f"Slice: {self.current_index + 1} / {len(self.current_slices)}"
        wl_info = f"WL: {int(self.window_level)} WW: {int(self.window_width)}"
        return {
            'TL': [str(ds.get('PatientName', 'No Name')), str(ds.get('PatientID', 'No ID')), f"{sex} {age}"],
            'TR': [get_tag('InstitutionName'), f"{date} {time_str}", get_tag('SeriesDescription')],
            'BL': [slice_info, f"Thk: {get_tag('SliceThickness')}mm"],
            'BR': [wl_info]
        }

    # --- イベントハンドリング ---
    def mousePressEvent(self, event):
        self.activated.emit(self, event.modifiers())
        self.last_mouse_pos = event.position()
        self.drag_accumulator = 0
        
        buttons = event.buttons()
        # ズーム操作(左右同時)の場合はツール描画を開始しない
        if (buttons & Qt.MouseButton.LeftButton) and (buttons & Qt.MouseButton.RightButton):
            return

        if self.current_tool_mode in [1, 2] and (buttons & Qt.MouseButton.LeftButton):
            canvas_pos = self.canvas.mapFrom(self, event.position().toPoint())
            hit_type, hit_index = self.canvas.hit_test(canvas_pos)
            if hit_index is not None:
                self.canvas.selected_type = hit_type
                self.canvas.selected_index = hit_index
                self.canvas.update()
            else:
                self.canvas.selected_index = None
                self.canvas.selected_type = None
                img_pos = self.canvas.screen_to_image(canvas_pos)
                if img_pos:
                    self.canvas.current_drawing_start = img_pos
                    self.canvas.current_drawing_end = img_pos
                    self.canvas.current_mode = 'ruler' if self.current_tool_mode == 1 else 'roi'
                    self.canvas.update()

    def mouseMoveEvent(self, event):
        if self.last_mouse_pos is None: return
        current_pos = event.position()
        delta_x = current_pos.x() - self.last_mouse_pos.x()
        delta_y = current_pos.y() - self.last_mouse_pos.y()
        buttons = event.buttons()

        # 1. ズーム (左+右ドラッグ)
        if (buttons & Qt.MouseButton.LeftButton) and (buttons & Qt.MouseButton.RightButton):
            zoom_delta = -delta_y * 0.01 
            self.apply_zoom(zoom_delta)
            self.zoomed.emit(self, zoom_delta) # 同期通知

        # 2. ツール描画
        elif self.current_tool_mode in [1, 2] and (buttons & Qt.MouseButton.LeftButton):
             if self.canvas.current_drawing_start:
                canvas_pos = self.canvas.mapFrom(self, current_pos.toPoint())
                img_pos = self.canvas.screen_to_image(canvas_pos)
                if img_pos:
                    self.canvas.current_drawing_end = img_pos
                    self.canvas.update()
        
        # 3. W/L調整
        elif buttons & Qt.MouseButton.RightButton:
            self.apply_wl(delta_x, delta_y)
            self.wl_changed.emit(self, delta_x, delta_y) # 同期通知
        
        # 4. ページング (中ドラッグ)
        elif buttons & Qt.MouseButton.MiddleButton:
            self.paging_drag(delta_y)
        
        # 5. パン (NAVモードのみ)
        elif self.current_tool_mode == 0 and (buttons & Qt.MouseButton.LeftButton):
            self.apply_pan(delta_x, delta_y)
            self.panned.emit(self, delta_x, delta_y) # 同期通知
            
        self.last_mouse_pos = current_pos

    def mouseReleaseEvent(self, event):
        if self.current_tool_mode in [1, 2] and (event.button() == Qt.MouseButton.LeftButton):
            c = self.canvas
            if c.current_drawing_start and c.current_drawing_end:
                dx = c.current_drawing_end.x() - c.current_drawing_start.x()
                dy = c.current_drawing_end.y() - c.current_drawing_start.y()
                dist_px = (dx**2 + dy**2)**0.5
                if dist_px > 2: 
                    if self.current_tool_mode == 1: 
                        if c.pixel_spacing:
                            dist_mm = dist_px * c.pixel_spacing[0]
                            text = f"{dist_mm:.2f} mm"
                        else: text = f"{dist_px:.1f} px"
                        c.measurements.append({'start': c.current_drawing_start, 'end': c.current_drawing_end, 'dist_text': text, 'slice_index': self.current_index})
                        c.selected_type = 'ruler'; c.selected_index = len(c.measurements) - 1
                    elif self.current_tool_mode == 2: 
                        rect = QRectF(c.current_drawing_start, c.current_drawing_end).normalized()
                        stats = c.calculate_roi_stats(rect)
                        text = "Error"
                        if stats != "N/A":
                            mean, std, mx, mn, area = stats
                            text = f"Mean:{mean:.1f} SD:{std:.1f}\nMax:{mx:.0f} Min:{mn:.0f}\nArea:{area:.0f}mm2"
                        c.rois.append({'rect': rect, 'text': text, 'slice_index': self.current_index})
                        c.selected_type = 'roi'; c.selected_index = len(c.rois) - 1
                c.current_drawing_start = None; c.current_drawing_end = None; c.update()
        self.last_mouse_pos = None

    def paging_drag(self, dy):
        if self.current_slices:
            self.drag_accumulator += dy
            threshold = 15
            if abs(self.drag_accumulator) > threshold:
                steps = int(self.drag_accumulator / threshold)
                if steps != 0:
                    self.scroll_step(steps, emit_sync=True)
                    self.drag_accumulator -= (steps * threshold)

    def wheelEvent(self, event):
        if not self.current_slices: return
        delta = event.angleDelta().y()
        steps = 1 if delta < 0 else -1
        self.scroll_step(steps, emit_sync=True)