import numpy as np
import pydicom
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QMenu
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import QImage, QPixmap, QColor, QPalette, QAction, QCursor
from gui.canvas import ImageCanvas
from core.loader import SeriesLoadWorker, MprBuilderWorker
from gui.tag_window import DicomTagWindow
from core.mpr_logic import get_resampled_slice, get_rotation_matrix

class ZetaViewport(QFrame):
    activated = pyqtSignal(object, object)
    series_dropped = pyqtSignal(object, str)
    
    scrolled = pyqtSignal(object, int)          
    panned = pyqtSignal(object, float, float)       
    wl_changed = pyqtSignal(object, float, float) 
    zoomed = pyqtSignal(object, float)
    
    processing_start = pyqtSignal(str)
    processing_progress = pyqtSignal(int)
    processing_finish = pyqtSignal()
    
    cross_ref_pos_changed = pyqtSignal(object, int, int, int)

    rotation_changed = pyqtSignal(object, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(2)
        self.setAcceptDrops(True)
        self.set_active(False)
        
        # マウス移動を常に追跡 (プローブ用)
        self.setMouseTracking(True)

        self.current_slices = []
        self.current_file_paths = []
        self.volume_data = None
        self.voxel_spacing = (1.0, 1.0, 1.0)
        self.mpr_loaded = False
        
        self.current_index = 0
        self.view_plane = 'Axial'
        self.is_mpr_enabled = False 

        self.rotation_angle = 0
        
        self.mip_mode = 'AVG'
        self.slab_thickness_mm = 0.0 
        
        self.is_probe_mode = False

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

        self.is_rotating_line = False
        self.drag_angle_offset = 0.0

        self.is_grabbing_sagittal = False

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.canvas = ImageCanvas()
        self.layout.addWidget(self.canvas)

    def set_active(self, active: bool):
        self.is_active = active
        if active: self.setStyleSheet("border: 2px solid #00FF00;") 
        else: self.setStyleSheet("border: 1px solid #333333;")

    # --- プローブモード切替 ---
    def set_probe_mode(self, active):
        self.is_probe_mode = active
        # 現在のマウス位置を取得して即時反映
        if active:
            # グローバル座標からローカル座標へ変換
            local_pos = self.canvas.mapFromGlobal(QCursor.pos())
            if self.canvas.rect().contains(local_pos):
                self.canvas.set_probe_active(True, local_pos)
        else:
            self.canvas.set_probe_active(False)

    # --- ヘルパー ---
    def _get_safe_dicom_value(self, ds, tag, default=None):
        val = ds.get(tag, default)
        if val is None: return default
        if isinstance(val, (list, pydicom.multival.MultiValue)):
            return float(val[0]) if len(val) > 0 else default
        try: return float(val)
        except: return default

    def get_current_coordinates(self):
        if self.volume_data is None: return 0, 0, 0
        vc = self.volume_data.shape # (Z, Y, X)
        cx, cy, cz = vc[2]//2, vc[1]//2, vc[0]//2
        if self.view_plane == 'Axial': cz = self.current_index
        elif self.view_plane == 'Coronal': cy = self.current_index
        elif self.view_plane == 'Sagittal': cx = self.current_index
        return cx, cy, cz

    # ★追加2: 線をクリアする
    def clear_cross_refs(self):
        self.canvas.cross_ref_lines = []
        self.canvas.update()

    # ★追加3: 指定したビューポート(sender_vp)に対応する線を追加する
    def add_cross_ref_line(self, sender_vp):
        if self.volume_data is None: return

        # 座標は相手から直接取得
        cx, cy, cz = sender_vp.get_current_coordinates()
        
        # 画面サイズ等の取得
        if self.canvas.pixmap is None: return
        img_w = self.canvas.pixmap.width(); img_h = self.canvas.pixmap.height()
        screen_center_x = img_w / 2; screen_center_y = img_h / 2
        
        vc = self.volume_data.shape
        vol_center_x = vc[2] // 2; vol_center_y = vc[1] // 2; vol_center_z = vc[0] // 2
        
        sp_z, sp_y, sp_x = self.voxel_spacing
        if sp_x <= 0: sp_x = 1.0; 
        if sp_y <= 0: sp_y = 1.0; 
        if sp_z <= 0: sp_z = 1.0
        
        scale_x = 1.0
        scale_y = sp_x / sp_y
        scale_z = sp_x / sp_z

        new_lines = [] # 追加する線リスト

        if self.view_plane == 'Axial':
            my_cx = screen_center_x + (cx - vol_center_x) * scale_x
            my_cy = screen_center_y + (cy - vol_center_y) * scale_y
            angle = sender_vp.rotation_angle 
            diag_len = (img_w**2 + img_h**2)**0.5 * 1.5

            def get_rotated_line(center_x, center_y, angle_deg, color_code):
                rad = np.radians(angle_deg)
                dx = np.cos(rad) * diag_len
                dy = np.sin(rad) * diag_len
                p1 = QPointF(center_x - dx, center_y - dy)
                p2 = QPointF(center_x + dx, center_y + dy)
                return {'start': p1, 'end': p2, 'color': QColor(color_code)}

            if sender_vp.view_plane == 'Coronal':
                new_lines.append(get_rotated_line(my_cx, my_cy, angle, "#0000FF"))
            elif sender_vp.view_plane == 'Sagittal':
                new_lines.append(get_rotated_line(my_cx, my_cy, angle + 90, "#FF0000"))
            
        else: # Coronal / Sagittal
            target_idx_x = cx if self.view_plane == 'Coronal' else cy
            center_idx_x = vol_center_x if self.view_plane == 'Coronal' else vol_center_y
            chk_scale_x  = scale_x if self.view_plane == 'Coronal' else scale_y
            pos_x = screen_center_x + (target_idx_x - center_idx_x) * chk_scale_x
            
            target_idx_y = cz
            center_idx_y = vol_center_z
            chk_scale_y  = scale_z
            pos_y = screen_center_y - (target_idx_y - center_idx_y) * chk_scale_y
            
            # Axial線を追加
            #if sender_vp.view_plane == 'Axial':
            #    new_lines.append({'type': 'H', 'pos': pos_y, 'color': QColor("#00FF00")}) # 緑 (Axial用)
            
            # 互いの線 (Sagittal <-> Coronal)
            if self.view_plane == 'Coronal' and sender_vp.view_plane == 'Sagittal':
                new_lines.append({'type': 'V', 'pos': pos_x, 'color': QColor("#FF0000")})
            if self.view_plane == 'Sagittal' and sender_vp.view_plane == 'Coronal':
                new_lines.append({'type': 'V', 'pos': pos_x, 'color': QColor("#0000FF")})

        # リストに追加（上書きしない）
        self.canvas.cross_ref_lines.extend(new_lines)
        self.canvas.update()

    # --- 位置情報発信 ---
    def notify_position_change(self):
        if not self.is_mpr_enabled or self.volume_data is None: return
        vc = self.volume_data.shape
        cx, cy, cz = vc[2]//2, vc[1]//2, vc[0]//2
        if self.view_plane == 'Axial': cz = self.current_index
        elif self.view_plane == 'Coronal': cy = self.current_index
        elif self.view_plane == 'Sagittal': cx = self.current_index
        self.cross_ref_pos_changed.emit(self, cx, cy, cz)

    # --- 描画更新 ---
    def update_display(self, emit_position=True):
        if self.is_mpr_enabled and self.volume_data is not None:
            self._render_mpr()
            if emit_position: self.notify_position_change()
        elif self.current_slices:
            self._render_2d()

    def scroll_step(self, steps, emit_sync=True):
        max_idx = self.get_max_index()
        new_index = int(np.clip(self.current_index + steps, 0, max_idx))
        if new_index != self.current_index:
            self.current_index = new_index
            self.update_display(emit_position=emit_sync)
            if emit_sync: self.scrolled.emit(self, steps)

    def apply_pan(self, dx, dy):
        if abs(dx)>1000 or abs(dy)>1000: return
        self.canvas.pan_x += dx
        self.canvas.pan_y += dy
        self.canvas.update()

    def apply_wl(self, dw, dl):
        if abs(dw)>10000 or abs(dl)>10000: return
        self.window_width = max(1, self.window_width + dw)
        self.window_level += dl
        self.update_display()

    def apply_zoom(self, delta_factor):
        if hasattr(self.canvas, 'zoom_factor'):
            new_zoom = self.canvas.zoom_factor + delta_factor
            self.canvas.zoom_factor = max(0.1, min(10.0, new_zoom))
            self.canvas.update()

    # --- 状態保存・復元 ---
    def get_state(self):
        return {
            'file_paths': self.current_file_paths,
            'slices': self.current_slices,
            'volume': self.volume_data,
            'spacing': self.voxel_spacing,
            'mpr_loaded': self.mpr_loaded,
            'index': self.current_index,
            'plane': self.view_plane,
            'mpr_enabled': self.is_mpr_enabled,
            'mip_mode': self.mip_mode,
            'thickness': self.slab_thickness_mm,
            'wl': self.window_level,
            'ww': self.window_width,
            'cached_wl': self._cached_wl,
            'cached_ww': self._cached_ww,
            'pan_x': self.canvas.pan_x,
            'pan_y': self.canvas.pan_y,
            'zoom': self.canvas.zoom_factor,
            'tool_mode': self.current_tool_mode,
            'measurements': self.canvas.measurements,
            'rois': self.canvas.rois
        }

    def restore_state(self, state):
        if not state.get('file_paths'): return
        self.current_file_paths = state['file_paths']
        self.current_slices = state['slices']
        self.volume_data = state['volume']
        self.voxel_spacing = state['spacing']
        self.mpr_loaded = state['mpr_loaded']
        self.current_index = state['index']
        self.view_plane = state['plane']
        self.is_mpr_enabled = state['mpr_enabled']
        self.mip_mode = state['mip_mode']
        self.slab_thickness_mm = state['thickness']
        self.window_level = state['wl']
        self.window_width = state['ww']
        self._cached_wl = state['cached_wl']
        self._cached_ww = state['cached_ww']
        self.canvas.pan_x = state['pan_x']
        self.canvas.pan_y = state['pan_y']
        self.canvas.zoom_factor = state['zoom']
        self.canvas.measurements = state['measurements']
        self.canvas.rois = state['rois']
        self.current_tool_mode = state['tool_mode']
        self.update_display(emit_position=False)

    def set_mip_params(self, mode, thickness_mm):
        if not self.is_mpr_enabled: return
        self.mip_mode = mode
        self.slab_thickness_mm = max(0.0, float(thickness_mm))
        self.update_display()

    # --- MPR描画 ---
    def _render_mpr(self):
        # ボリュームが無ければ何もしない
        if self.volume_data is None: return
        
        vc = self.volume_data.shape # (Z, Y, X)
        
        # ボリュームの中心
        center_x = vc[2] // 2
        center_y = vc[1] // 2
        center_z = vc[0] // 2
        
        # スクロールによる中心移動の反映
        if self.view_plane == 'Axial':
            center_z = self.current_index
        elif self.view_plane == 'Coronal':
            center_y = self.current_index
        elif self.view_plane == 'Sagittal':
            center_x = self.current_index

        center_point = (center_x, center_y, center_z)
        
        # ★修正ポイント1: ベクトル定義と回転軸の統一
        # 重複していたコードを削除し、ここで定義します。
        # 重要なのは axis_rot = 'z' です。どの断面でも「人体の上下方向(Z)」を軸に回転させます。

        axis_rot = 'z' # 全ビューポートでZ軸回転（Swivel）を採用

        if self.view_plane == 'Axial':
            # Axial: 通常のXY平面
            vec_right  = np.array([1, 0, 0])
            vec_down   = np.array([0, 1, 0])
            vec_normal = np.array([0, 0, 1]) # 奥行き (Z)
        elif self.view_plane == 'Coronal':
            # Coronal: XZ平面だが、Z軸回転させるためにX軸とY軸(奥行き)を回す
            vec_right  = np.array([1, 0, 0])
            vec_down   = np.array([0, 0, -1]) # Z軸(下)は固定
            vec_normal = np.array([0, 1, 0])  # Y軸(奥行き)
        elif self.view_plane == 'Sagittal':
            # Sagittal: YZ平面
            vec_right  = np.array([0, 1, 0])
            vec_down   = np.array([0, 0, -1]) # Z軸(下)は固定
            vec_normal = np.array([1, 0, 0])  # X軸(奥行き)

        # ★重複コード削除: ここにあった rot_mat の計算などは削除し、tryブロック内にまとめます

        try:
            # 1. ボクセルスペーシングを取得 (Z, Y, X)
            sp_z, sp_y, sp_x = self.voxel_spacing
            
            # 安全策: ゼロ除算防止
            if sp_x <= 0: sp_x = 1.0
            if sp_y <= 0: sp_y = 1.0
            if sp_z <= 0: sp_z = 1.0

            scale_x = 1.0               # X軸基準
            scale_y = sp_x / sp_y       # Y軸の補正値
            scale_z = sp_x / sp_z       # Z軸の補正値

            spacing_scale = np.array([scale_x, scale_y, scale_z])

            # 3. 回転行列の適用
            # axis_rot は上で 'z' に固定しました
            rot_mat = get_rotation_matrix(axis_rot, self.rotation_angle)
            
            vec_right_rot  = rot_mat @ vec_right
            vec_down_rot   = rot_mat @ vec_down
            vec_normal_rot = rot_mat @ vec_normal
            
            # 4. 物理サイズに基づくスケーリングを適用
            vec_right_final  = vec_right_rot  * spacing_scale
            vec_down_final   = vec_down_rot   * spacing_scale
            vec_normal_final = vec_normal_rot * spacing_scale

            # 表示サイズ
            dim = max(vc)
            req_w = int(dim * 1.2)
            req_h = int(dim * 1.2)
            
            # リサンプリング実行
            slice_img = get_resampled_slice(
                self.volume_data,
                center_point,
                vec_right_final,
                vec_down_final,
                vec_normal_final,
                req_w, req_h,
                self.voxel_spacing,
                self.slab_thickness_mm,
                self.mip_mode
            )
            
            # --- 画像生成と表示 ---
            ds = self.current_slices[0] if self.current_slices else None
            hu_image = slice_img.astype(np.float32)

            self._process_and_send_image(hu_image, 1.0, ds)
            
        except Exception as e:
            print(f"MPR Render Error: {e}")
            import traceback
            traceback.print_exc()

    def _project_slab(self, slab, axis):
        if slab.shape[axis] == 0: return np.zeros((1,1), dtype=np.float32)
        if slab.shape[axis] == 1: 
            if axis == 0: return slab[0, :, :]
            if axis == 1: return slab[:, 0, :]
            if axis == 2: return slab[:, :, 0]
        if self.mip_mode == 'MIP': return np.max(slab, axis=axis)
        elif self.mip_mode == 'MinIP': return np.min(slab, axis=axis)
        else: return np.mean(slab, axis=axis)

    # --- オーバーレイ ---
    def create_overlay_info(self, ds):
        info = {}
        name = ""; pid = ""; date = ""; inst = ""; desc = ""
        if ds:
            def get_tag(tag, default=""): return str(ds.get(tag, default))
            name = str(ds.get('PatientName', ''))
            pid = str(ds.get('PatientID', ''))
            sex = str(ds.get('PatientSex', ''))
            age = str(ds.get('PatientAge', ''))
            date = get_tag('StudyDate')
            inst = get_tag('InstitutionName')
            desc = get_tag('SeriesDescription')
            info['TL'] = [name, pid, f"{sex} {age}"]
            info['TR'] = [inst, date, desc]
        
        total = self.get_max_index() + 1
        mode_str = "Axial (2D)"
        if self.is_mpr_enabled:
            mode_str = f"{self.view_plane}"
            if self.slab_thickness_mm > 0:
                mode_str += f" [{self.mip_mode} {self.slab_thickness_mm:.1f}mm]"
        
        info['BL'] = [f"{mode_str}: {self.current_index + 1} / {total}", f"Zoom: {self.canvas.zoom_factor:.1f}x"]
        info['BR'] = [f"WL: {int(self.window_level)} WW: {int(self.window_width)}"]

        markers = {}
        if self.is_mpr_enabled:
            if self.view_plane == 'Axial': markers = {'T': 'A', 'B': 'P', 'L': 'R', 'R': 'L'}
            elif self.view_plane == 'Coronal': markers = {'T': 'S', 'B': 'I', 'L': 'R', 'R': 'L'}
            elif self.view_plane == 'Sagittal': markers = {'T': 'S', 'B': 'I', 'L': 'A', 'R': 'P'}
        elif ds and 'ImageOrientationPatient' in ds:
            try:
                iop = [float(x) for x in ds.ImageOrientationPatient]
                row_vec = iop[0:3]
                col_vec = iop[3:6]
                markers['R'] = self._get_orientation_label(row_vec)
                markers['L'] = self._get_orientation_label([-x for x in row_vec])
                markers['B'] = self._get_orientation_label(col_vec)
                markers['T'] = self._get_orientation_label([-x for x in col_vec])
            except: pass
        info['Markers'] = markers
        return info

    def _get_orientation_label(self, vector):
        if not vector or len(vector) != 3: return ""
        abs_vec = [abs(v) for v in vector]
        dominant_axis = abs_vec.index(max(abs_vec))
        val = vector[dominant_axis]
        if dominant_axis == 0: return "L" if val > 0 else "R"
        if dominant_axis == 1: return "P" if val > 0 else "A"
        if dominant_axis == 2: return "S" if val > 0 else "I"
        return ""

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
                self.update_display(emit_position=True)
        else:
            self.view_plane = 'Axial'
            self.current_index = min(self.current_index, len(self.current_slices)-1)
            self.update_display(emit_position=False)

    def on_mpr_finished(self, volume, spacing):
        self.processing_finish.emit() 
        if volume is None:
            self.canvas.overlay_data['BL'] = ["MPR Error"]; self.canvas.update(); return
        self.volume_data = volume; self.voxel_spacing = spacing; self.mpr_loaded = True
        self.set_view_plane('Axial')
        self.window_level = self._cached_wl; self.window_width = self._cached_ww
        self.update_display(emit_position=True)

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
        self.update_display(emit_position=False)

    def update_display(self, emit_position=True):
        if self.is_mpr_enabled and self.volume_data is not None:
            self._render_mpr()
            if emit_position: self.notify_position_change()
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

    def get_max_index(self):
        if self.is_mpr_enabled and self.volume_data is not None:
            if self.view_plane == 'Axial': return self.volume_data.shape[0] - 1
            elif self.view_plane == 'Coronal': return self.volume_data.shape[1] - 1
            elif self.view_plane == 'Sagittal': return self.volume_data.shape[2] - 1
        elif self.current_slices: return len(self.current_slices) - 1
        return 0

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

    # --- イベントハンドラ ---
    def mousePressEvent(self, event):
        self.activated.emit(self, event.modifiers())
        self.last_mouse_pos = event.position()
        self.drag_accumulator = 0
        if event.button() == Qt.MouseButton.RightButton: self.is_right_dragged = False
        
        if event.button() == Qt.MouseButton.LeftButton:
            if self.view_plane == 'Axial' and self.current_tool_mode == 0:
                canvas_pos = self.canvas.mapFrom(self, event.position().toPoint())
                hit_type, hit_index = self.canvas.hit_test(canvas_pos)
                
                if hit_type == 'cross_ref':
                    self.is_rotating_line = True
                    
                    # 1. 掴んだ線を取得
                    line = self.canvas.cross_ref_lines[hit_index]
                    
                    # 2. その線の現在の角度を計算 (start -> end のベクトルから)
                    # これにより、現在表示されている線の角度を正確に取得できる
                    p1 = line['start']
                    p2 = line['end']
                    line_dx = p2.x() - p1.x()
                    line_dy = p2.y() - p1.y() # Y軸は画面下方向が正
                    current_line_angle = np.degrees(np.arctan2(line_dy, line_dx))
                    
                    # 3. マウスの角度を計算
                    rect = self.rect()
                    center = rect.center()
                    dx = event.position().x() - center.x()
                    dy = event.position().y() - center.y()
                    mouse_angle = np.degrees(np.arctan2(dy, dx))
                    
                    # 4. オフセット計算 (掴んだ場所と線の角度ズレ)
                    self.drag_angle_offset = current_line_angle - mouse_angle
                    
                    # 5. 色で「Sagittal線（赤）」かどうか判定
                    # 赤(#FF0000)なら Sagittal線。これは本来の角度(Coronal)より+90度進んでいる
                    self.is_grabbing_sagittal = False
                    color = line.get('color', QColor("#FFFF00"))
                    if color.name() == "#ff0000": # 赤色
                        self.is_grabbing_sagittal = True
                        
                    return 

            self.notify_position_change()

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
        current_pos = event.position()
        if self.is_probe_mode: self.canvas.update_probe_pos(current_pos)
        
        if self.view_plane == 'Axial' and self.current_tool_mode == 0 and not (event.buttons() & Qt.MouseButton.LeftButton):
             canvas_pos = self.canvas.mapFrom(self, current_pos.toPoint())
             hit_type, _ = self.canvas.hit_test(canvas_pos)
             if hit_type == 'cross_ref':
                 self.setCursor(Qt.CursorShape.PointingHandCursor)
             else:
                 self.setCursor(Qt.CursorShape.ArrowCursor)

        if self.last_mouse_pos is None:
            self.last_mouse_pos = current_pos
            return

        # ★修正: 回転ロジック
        if self.is_rotating_line:
             rect = self.rect()
             center = rect.center()
             dx = current_pos.x() - center.x()
             dy = current_pos.y() - center.y()
             
             mouse_angle = np.degrees(np.arctan2(dy, dx))
             
             # 1. 線の「新しい角度」を計算
             new_line_angle = mouse_angle + self.drag_angle_offset
             
             # 2. メインウィンドウに送る「基準角度（Coronal）」に変換
             base_angle = new_line_angle
             
             if self.is_grabbing_sagittal:
                 # Sagittal線を掴んでいる場合、その線は Coronal + 90度 の位置にある
                 # なので、基準角度に戻すには 90度引く
                 base_angle = new_line_angle - 90.0
             
             self.rotation_changed.emit(self, base_angle)
             self.last_mouse_pos = current_pos
             return

        delta_x = float(current_pos.x() - self.last_mouse_pos.x())
        delta_y = float(current_pos.y() - self.last_mouse_pos.y())
        buttons = event.buttons()
        modifiers = event.modifiers()

        if (buttons & Qt.MouseButton.LeftButton) and (modifiers & Qt.KeyboardModifier.AltModifier):
             # 画面中心からの角度を計算
             rect = self.rect()
             center = rect.center()
             
             # 現在のマウス位置と中心との差分
             dx = current_pos.x() - center.x()
             dy = current_pos.y() - center.y()
             
             angle_rad = np.arctan2(dy, dx)
             angle_deg = np.degrees(angle_rad)
             
             self.rotation_changed.emit(self, angle_deg)
             
             self.last_mouse_pos = current_pos
             return

        if (buttons & Qt.MouseButton.LeftButton) and (buttons & Qt.MouseButton.RightButton):
            self.is_right_dragged = True
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
        if self.is_rotating_line:
            self.is_rotating_line = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
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