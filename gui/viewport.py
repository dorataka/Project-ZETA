import numpy as np
import pydicom
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QMenu
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QRectF
from PyQt6.QtGui import QImage, QPixmap, QColor, QPalette, QAction

from gui.canvas import ImageCanvas
from core.loader import SeriesLoadWorker, MprBuilderWorker
from gui.tag_window import DicomTagWindow

class ZetaViewport(QFrame):
    activated = pyqtSignal(object, object)
    series_dropped = pyqtSignal(object, str)
    scrolled = pyqtSignal(object, int)          
    panned = pyqtSignal(object, int, int)       
    wl_changed = pyqtSignal(object, float, float) 
    zoomed = pyqtSignal(object, float)
    
    processing_start = pyqtSignal(str)
    processing_progress = pyqtSignal(int)
    processing_finish = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(2)
        self.setAcceptDrops(True)
        self.set_active(False)

        self.current_slices = []
        self.current_file_paths = []
        self.volume_data = None
        self.voxel_spacing = (1.0, 1.0, 1.0) # z, y, x
        self.mpr_loaded = False
        
        self.current_index = 0
        self.view_plane = 'Axial'
        self.is_mpr_enabled = False 
        
        self.mip_mode = 'AVG'
        # ★変更: mm単位で保持
        self.slab_thickness_mm = 0.0 
        
        self.window_level = 40
        self.window_width = 400
        self.current_tool_mode = 0 
        self._img_buffer = None
        self._cached_wl = 40
        self._cached_ww = 400
        
        self.load_worker = None
        self.mpr_worker = None
        self.last_mouse_pos = None
        self.drag_accumulator = 0
        self.is_right_dragged = False

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.canvas = ImageCanvas()
        self.layout.addWidget(self.canvas)

    def set_active(self, active: bool):
        self.is_active = active
        if active: self.setStyleSheet("border: 2px solid #00FF00;") 
        else: self.setStyleSheet("border: 1px solid #333333;")

    # --- ★変更: mm単位で設定を受け取る ---
    def set_mip_params(self, mode, thickness_mm):
        if not self.is_mpr_enabled: return
        self.mip_mode = mode
        self.slab_thickness_mm = max(0.0, float(thickness_mm))
        self.update_display()

    def _render_mpr(self):
        max_idx = self.get_max_index()
        self.current_index = max(0, min(self.current_index, max_idx))
        try:
            slice_img = None
            aspect_ratio = 1.0
            sp_z, sp_y, sp_x = self.voxel_spacing
            
            # --- ★重要: mmから枚数への換算 ---
            # 視線方向(Depth)のスペーシングを取得
            depth_spacing = 1.0
            if self.view_plane == 'Axial': depth_spacing = sp_z
            elif self.view_plane == 'Coronal': depth_spacing = sp_y
            elif self.view_plane == 'Sagittal': depth_spacing = sp_x
            
            # 必要な枚数 (片側)
            if depth_spacing > 0:
                half_slices = int((self.slab_thickness_mm / depth_spacing) / 2)
            else:
                half_slices = 0
            
            # --- スラブ切り出し ---
            if self.view_plane == 'Axial':
                start = max(0, self.current_index - half_slices)
                end = min(self.volume_data.shape[0], self.current_index + half_slices + 1)
                slab = self.volume_data[start:end, :, :]
                slice_img = self._project_slab(slab, axis=0)
                aspect_ratio = 1.0

            elif self.view_plane == 'Coronal':
                start = max(0, self.current_index - half_slices)
                end = min(self.volume_data.shape[1], self.current_index + half_slices + 1)
                slab = self.volume_data[:, start:end, :]
                proj = self._project_slab(slab, axis=1)
                slice_img = np.flipud(proj)
                if sp_x > 0: aspect_ratio = sp_z / sp_x

            elif self.view_plane == 'Sagittal':
                start = max(0, self.current_index - half_slices)
                end = min(self.volume_data.shape[2], self.current_index + half_slices + 1)
                slab = self.volume_data[:, :, start:end]
                proj = self._project_slab(slab, axis=2)
                slice_img = np.flipud(proj)
                if sp_y > 0: aspect_ratio = sp_z / sp_y
                
            ds = self.current_slices[0] if self.current_slices else None
            hu_image = slice_img.astype(np.float32)
            self._process_and_send_image(hu_image, aspect_ratio, ds)
            
        except Exception as e:
            print(f"MPR Error: {e}")

    def _project_slab(self, slab, axis):
        if slab.shape[axis] == 0: return np.zeros((1,1), dtype=np.float32)
        if slab.shape[axis] == 1: 
            if axis == 0: return slab[0, :, :]
            if axis == 1: return slab[:, 0, :]
            if axis == 2: return slab[:, :, 0]

        if self.mip_mode == 'MIP': return np.max(slab, axis=axis)
        elif self.mip_mode == 'MinIP': return np.min(slab, axis=axis)
        else: return np.mean(slab, axis=axis)

    def create_overlay_info(self, ds):
        if not ds: return {}
        def get_tag(tag, default=""): return str(ds.get(tag, default))
        total = self.get_max_index() + 1
        
        mode_str = "Axial (2D)"
        if self.is_mpr_enabled:
            mode_str = f"{self.view_plane}"
            if self.slab_thickness_mm > 0:
                mode_str += f" [{self.mip_mode} {self.slab_thickness_mm:.1f}mm]"
        
        info = {
            'TL': [str(ds.get('PatientName', '')), str(ds.get('PatientID', '')), f"{ds.get('PatientSex','')} {ds.get('PatientAge','')}"],
            'TR': [get_tag('InstitutionName'), get_tag('StudyDate'), get_tag('SeriesDescription')],
            'BL': [f"{mode_str}: {self.current_index + 1} / {total}", f"Zoom: {self.canvas.zoom_factor:.1f}x"],
            'BR': [f"WL: {int(self.window_level)} WW: {int(self.window_width)}"]
        }
        return info

    # --- 以下、既存メソッド ---
    def toggle_mpr(self, enabled):
        if self.is_mpr_enabled == enabled: return
        self.is_mpr_enabled = enabled
        if enabled:
            self._cached_wl = self.window_level; self._cached_ww = self.window_width
            if not self.mpr_loaded and self.current_file_paths:
                self.processing_start.emit("Building 3D MPR...")
                self.mpr_worker = MprBuilderWorker(self.current_file_paths)
                self.mpr_worker.progress.connect(self.processing_progress)
                self.mpr_worker.finished.connect(self.on_mpr_finished)
                self.mpr_worker.start()
            else:
                self.set_view_plane('Axial')
                self.window_level = self._cached_wl; self.window_width = self._cached_ww
                self.update_display()
        else:
            self.view_plane = 'Axial'
            self.current_index = min(self.current_index, len(self.current_slices)-1)
            self.update_display()

    def on_mpr_finished(self, volume, spacing):
        self.processing_finish.emit() 
        if volume is None:
            self.canvas.overlay_data['BL'] = ["MPR Error"]; self.canvas.update(); return
        self.volume_data = volume; self.voxel_spacing = spacing; self.mpr_loaded = True
        self.set_view_plane('Axial')
        self.window_level = self._cached_wl; self.window_width = self._cached_ww
        self.update_display()

    def reset_wl_ww_to_dicom_defaults(self):
        if self.current_slices:
            ds = self.current_slices[0]
            self.window_level = self._get_safe_dicom_value(ds, 'WindowCenter', 40)
            self.window_width = self._get_safe_dicom_value(ds, 'WindowWidth', 400)
            if self.window_width <= 0: self.window_width = 100

    def set_view_plane(self, plane):
        if not self.is_mpr_enabled: return
        self.view_plane = plane
        max_idx = self.get_max_index()
        self.current_index = max_idx // 2
        self.canvas.reset_view(); self.update_display()

    def load_series(self, file_paths):
        self.current_file_paths = file_paths; self.mpr_loaded = False; self.volume_data = None; self.is_mpr_enabled = False 
        self.canvas.overlay_data['BL'] = ["LOADING..."]; self.canvas.update()
        if self.load_worker and self.load_worker.isRunning(): self.load_worker.terminate()
        self.load_worker = SeriesLoadWorker(file_paths)
        self.load_worker.finished.connect(self.on_load_finished)
        self.load_worker.start()

    def on_load_finished(self, slices, pixel_spacing):
        self.current_slices = slices; self.current_index = 0; self.canvas.reset_view(); self.canvas.pixel_spacing = pixel_spacing
        if slices:
            ds = slices[0]
            self.window_level = self._get_safe_dicom_value(ds, 'WindowCenter', 40)
            self.window_width = self._get_safe_dicom_value(ds, 'WindowWidth', 400)
            if self.window_width <= 0: self.window_width = 100
            self._cached_wl = self.window_level; self._cached_ww = self.window_width
        self.update_display()

    def update_display(self):
        if self.is_mpr_enabled and self.volume_data is not None: self._render_mpr()
        elif self.current_slices: self._render_2d()

    def _render_2d(self):
        self.current_index = max(0, min(self.current_index, len(self.current_slices) - 1))
        ds = self.current_slices[self.current_index]
        try:
            pixel_array = ds.pixel_array.astype(np.float32)
            slope = getattr(ds, 'RescaleSlope', 1.0); intercept = getattr(ds, 'RescaleIntercept', 0.0)
            hu_image = pixel_array * slope + intercept
            self._process_and_send_image(hu_image, 1.0, ds)
        except Exception as e: print(f"2D Error: {e}")

    def _process_and_send_image(self, hu_image, aspect_ratio, ds_meta):
        min_v = self.window_level - (self.window_width / 2.0); max_v = self.window_level + (self.window_width / 2.0)
        img_windowed = np.clip(hu_image, min_v, max_v)
        div = max_v - min_v; 
        if div == 0: div = 1
        img_norm = ((img_windowed - min_v) / div * 255).astype(np.uint8)
        img_norm = np.ascontiguousarray(img_norm)
        h, w = img_norm.shape
        self._img_buffer = img_norm.tobytes()
        q_img = QImage(self._img_buffer, w, h, w, QImage.Format.Format_Grayscale8).copy()
        pixmap = QPixmap.fromImage(q_img)
        overlay_info = self.create_overlay_info(ds_meta)
        self.canvas.set_pixmap(pixmap, self.canvas.pixel_spacing, self.current_index, hu_image, overlay_data=overlay_info, aspect_ratio=aspect_ratio)

    def _get_safe_dicom_value(self, ds, tag, default=None):
        val = ds.get(tag, default)
        if val is None: return default
        if isinstance(val, (list, pydicom.multival.MultiValue)): return float(val[0]) if len(val) > 0 else default
        try: return float(val)
        except: return default

    def get_max_index(self):
        if self.is_mpr_enabled and self.volume_data is not None:
            if self.view_plane == 'Axial': return self.volume_data.shape[0] - 1
            elif self.view_plane == 'Coronal': return self.volume_data.shape[1] - 1
            elif self.view_plane == 'Sagittal': return self.volume_data.shape[2] - 1
        elif self.current_slices: return len(self.current_slices) - 1
        return 0

    def scroll_step(self, steps, emit_sync=True):
        max_idx = self.get_max_index()
        new_index = int(np.clip(self.current_index + steps, 0, max_idx))
        if new_index != self.current_index:
            self.current_index = new_index; self.update_display()
            if emit_sync: self.scrolled.emit(self, steps)

    def apply_pan(self, dx, dy):
        if abs(dx)>1000 or abs(dy)>1000: return
        self.canvas.pan_x += dx; self.canvas.pan_y += dy; self.canvas.update()
    def apply_wl(self, dw, dl):
        if abs(dw)>10000 or abs(dl)>10000: return
        self.window_width = max(1, self.window_width + dw); self.window_level += dl; self.update_display()
    def apply_zoom(self, delta_factor):
        if hasattr(self.canvas, 'zoom_factor'):
            new_zoom = self.canvas.zoom_factor + delta_factor
            self.canvas.zoom_factor = max(0.1, min(10.0, new_zoom))
            self.canvas.update()

    def show_context_menu(self, global_pos):
        menu = QMenu(self)
        action_tags = QAction("Show DICOM Tags", self)
        action_tags.triggered.connect(self.open_dicom_tags)
        menu.addAction(action_tags)
        menu.exec(global_pos)

    def open_dicom_tags(self):
        ds = None
        if not self.is_mpr_enabled and self.current_slices:
            idx = max(0, min(self.current_index, len(self.current_slices)-1))
            ds = self.current_slices[idx]
        elif self.is_mpr_enabled and self.current_slices: ds = self.current_slices[0]
        if ds:
            dialog = DicomTagWindow(ds, self)
            dialog.exec()

    def mousePressEvent(self, event):
        self.activated.emit(self, event.modifiers())
        self.last_mouse_pos = event.position()
        self.drag_accumulator = 0
        if event.button() == Qt.MouseButton.RightButton: self.is_right_dragged = False
        buttons = event.buttons()
        if (buttons & Qt.MouseButton.LeftButton) and (buttons & Qt.MouseButton.RightButton): return
        if self.current_tool_mode in [1, 2] and (buttons & Qt.MouseButton.LeftButton):
            canvas_pos = self.canvas.mapFrom(self, event.position().toPoint())
            hit_type, hit_index = self.canvas.hit_test(canvas_pos)
            if hit_index is not None:
                self.canvas.selected_type = hit_type; self.canvas.selected_index = hit_index; self.canvas.update()
            else:
                self.canvas.selected_index = None; self.canvas.selected_type = None
                img_pos = self.canvas.screen_to_image(canvas_pos)
                if img_pos:
                    self.canvas.current_drawing_start = img_pos; self.canvas.current_drawing_end = img_pos
                    self.canvas.current_mode = 'ruler' if self.current_tool_mode == 1 else 'roi'; self.canvas.update()

    def mouseMoveEvent(self, event):
        if self.last_mouse_pos is None: return
        current_pos = event.position()
        delta_x = float(current_pos.x() - self.last_mouse_pos.x())
        delta_y = float(current_pos.y() - self.last_mouse_pos.y())
        buttons = event.buttons()
        if (buttons & Qt.MouseButton.LeftButton) and (buttons & Qt.MouseButton.RightButton):
            zoom_delta = -delta_y * 0.01; self.apply_zoom(zoom_delta); self.zoomed.emit(self, zoom_delta)
        elif self.current_tool_mode in [1, 2] and (buttons & Qt.MouseButton.LeftButton):
             if self.canvas.current_drawing_start:
                canvas_pos = self.canvas.mapFrom(self, current_pos.toPoint())
                img_pos = self.canvas.screen_to_image(canvas_pos)
                if img_pos: self.canvas.current_drawing_end = img_pos; self.canvas.update()
        elif buttons & Qt.MouseButton.RightButton:
            if abs(delta_x) > 1 or abs(delta_y) > 1: self.is_right_dragged = True
            self.apply_wl(delta_x, delta_y); self.wl_changed.emit(self, delta_x, delta_y)
        elif buttons & Qt.MouseButton.MiddleButton:
            self.paging_drag(delta_y)
        elif self.current_tool_mode == 0 and (buttons & Qt.MouseButton.LeftButton):
            self.apply_pan(delta_x, delta_y); self.panned.emit(self, delta_x, delta_y)
        self.last_mouse_pos = current_pos

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            if not self.is_right_dragged: self.show_context_menu(event.globalPosition().toPoint())
            self.is_right_dragged = False
        if self.current_tool_mode in [1, 2] and (event.button() == Qt.MouseButton.LeftButton):
            c = self.canvas
            if c.current_drawing_start and c.current_drawing_end:
                dx = c.current_drawing_end.x() - c.current_drawing_start.x()
                dy = c.current_drawing_end.y() - c.current_drawing_start.y()
                dist_px = (dx**2 + dy**2)**0.5
                if dist_px > 2: 
                    if self.current_tool_mode == 1: 
                        text = f"{dist_px:.1f} px" 
                        c.measurements.append({'start': c.current_drawing_start, 'end': c.current_drawing_end, 'dist_text': text, 'slice_index': self.current_index})
                        c.selected_type = 'ruler'; c.selected_index = len(c.measurements) - 1
                    elif self.current_tool_mode == 2: 
                        rect = QRectF(c.current_drawing_start, c.current_drawing_end).normalized()
                        stats = c.calculate_roi_stats(rect)
                        text = "..."
                        if stats != "N/A":
                            mean, std, mx, mn, area = stats
                            text = f"Mean:{mean:.1f} SD:{std:.1f}" 
                        c.rois.append({'rect': rect, 'text': text, 'slice_index': self.current_index})
                        c.selected_type = 'roi'; c.selected_index = len(c.rois) - 1
                c.current_drawing_start = None; c.current_drawing_end = None; c.update()
        self.last_mouse_pos = None

    def paging_drag(self, dy):
        self.drag_accumulator += dy
        if abs(self.drag_accumulator) > 15:
            steps = int(self.drag_accumulator / 15)
            if steps != 0: self.scroll_step(steps, emit_sync=True); self.drag_accumulator -= (steps * 15)

    def wheelEvent(self, event):
        steps = 1 if event.angleDelta().y() < 0 else -1
        self.scroll_step(steps, emit_sync=True)

    def set_tool_mode(self, mode):
        self.current_tool_mode = mode; self.canvas.selected_index = None; self.canvas.selected_type = None; self.canvas.update()
    def delete_measurement(self): return self.canvas.delete_selected_measurement()
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-zeta-series-uid"): event.accept(); self.setStyleSheet("border: 2px dashed #FFFFFF;")
        else: event.ignore()
    def dragLeaveEvent(self, event): self.set_active(self.is_active)
    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-zeta-series-uid"):
            uid = event.mimeData().data("application/x-zeta-series-uid").data().decode('utf-8')
            self.series_dropped.emit(self, uid); event.accept(); self.set_active(True)
        else: event.ignore()