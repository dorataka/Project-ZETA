import os
import re 
from PyQt6.QtWidgets import (QMainWindow, QLabel, QVBoxLayout, QHBoxLayout, QWidget, 
                             QPushButton, QMessageBox, QListWidget, QListWidgetItem, 
                             QButtonGroup, QGridLayout, QSpinBox, QFrame, QProgressBar,
                             QFileDialog, QComboBox) 
from PyQt6.QtCore import Qt, QPoint, QMimeData, QByteArray
from PyQt6.QtGui import QKeyEvent, QDrag

from gui.viewport import ZetaViewport
from core.loader import DicomScanWorker

class DraggableListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True) 
    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item: return
        uid = item.data(Qt.ItemDataRole.UserRole)
        if not uid: return
        mime = QMimeData()
        mime.setData("application/x-zeta-series-uid", QByteArray(uid.encode('utf-8')))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(supportedActions)

class ZetaViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Project Z.E.T.A. - MIP/MinIP (mm Edition)")
        self.resize(1600, 900)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.all_series_data = {} 
        self.viewports = [] 
        self.selected_viewports = set()
        self.scan_worker = None
        self.setup_ui()
        self.apply_styles()
        self.update_grid_layout(1, 1)

    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        self.left_panel = QWidget()
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_panel.setFixedWidth(280)
        
        # 1. Grid
        self.grid_label = QLabel("GRID LAYOUT")
        self.left_layout.addWidget(self.grid_label)
        self.grid_ctrl_layout = QHBoxLayout()
        self.spin_rows = QSpinBox(); self.spin_rows.setRange(1, 5); self.spin_rows.setValue(1)
        self.spin_cols = QSpinBox(); self.spin_cols.setRange(1, 5); self.spin_cols.setValue(1)
        self.spin_rows.setPrefix("R:"); self.spin_cols.setPrefix("C:")
        self.btn_apply_grid = QPushButton("APPLY")
        self.btn_apply_grid.clicked.connect(self.on_apply_grid_clicked)
        self.grid_ctrl_layout.addWidget(self.spin_rows)
        self.grid_ctrl_layout.addWidget(self.spin_cols)
        self.grid_ctrl_layout.addWidget(self.btn_apply_grid)
        self.left_layout.addLayout(self.grid_ctrl_layout)
        self.left_layout.addSpacing(20)

        # 2. MPR & MIP Controls
        self.mpr_label = QLabel("3D RECONSTRUCTION")
        self.left_layout.addWidget(self.mpr_label)
        
        self.btn_mpr_enable = QPushButton("ENABLE MPR MODE")
        self.btn_mpr_enable.setCheckable(True)
        self.btn_mpr_enable.clicked.connect(self.toggle_mpr_mode)
        self.left_layout.addWidget(self.btn_mpr_enable)
        
        self.mpr_btns_layout = QHBoxLayout()
        self.btn_axial = QPushButton("AXIAL"); self.btn_axial.setCheckable(True); self.btn_axial.setChecked(True)
        self.btn_axial.clicked.connect(lambda: self.set_mpr_plane('Axial'))
        self.btn_coronal = QPushButton("COR"); self.btn_coronal.setCheckable(True)
        self.btn_coronal.clicked.connect(lambda: self.set_mpr_plane('Coronal'))
        self.btn_sagittal = QPushButton("SAG"); self.btn_sagittal.setCheckable(True)
        self.btn_sagittal.clicked.connect(lambda: self.set_mpr_plane('Sagittal'))
        self.mpr_group = QButtonGroup(self)
        self.mpr_group.addButton(self.btn_axial); self.mpr_group.addButton(self.btn_coronal); self.mpr_group.addButton(self.btn_sagittal)
        self.mpr_btns_layout.addWidget(self.btn_axial); self.mpr_btns_layout.addWidget(self.btn_coronal); self.mpr_btns_layout.addWidget(self.btn_sagittal)
        self.left_layout.addLayout(self.mpr_btns_layout)

        # MIP/MinIP 設定
        self.mip_layout = QHBoxLayout()
        
        self.combo_mip_mode = QComboBox()
        self.combo_mip_mode.addItems(["AVG", "MIP", "MinIP"])
        self.combo_mip_mode.currentIndexChanged.connect(self.update_mip_settings)
        
        # 厚み指定 (ComboBox + Editable)
        self.combo_thickness = QComboBox()
        self.combo_thickness.setEditable(True) 
        presets = [f"{i} mm" for i in range(8)] # 0 mm ... 7 mm
        presets.extend(["10 mm", "15 mm", "20 mm", "50 mm"])
        self.combo_thickness.addItems(presets)
        self.combo_thickness.setCurrentText("0 mm") 
        
        self.combo_thickness.editTextChanged.connect(self.update_mip_settings)
        self.combo_thickness.currentIndexChanged.connect(self.update_mip_settings)
        
        self.mip_layout.addWidget(self.combo_mip_mode, 4)
        self.mip_layout.addWidget(self.combo_thickness, 6)
        self.left_layout.addLayout(self.mip_layout)
        
        self.update_mpr_buttons_state(False)
        self.left_layout.addSpacing(20)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0); self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("QProgressBar { border: 1px solid #555; border-radius: 3px; text-align: center; color: white; } QProgressBar::chunk { background-color: #00FF00; }")
        self.left_layout.addWidget(self.progress_bar)
        self.left_layout.addSpacing(10)

        # 3. Tools
        self.mode_label = QLabel("CONTROLLER MODE")
        self.left_layout.addWidget(self.mode_label)
        self.btn_nav = QPushButton("NAVIGATE"); self.btn_nav.setCheckable(True); self.btn_nav.setChecked(True)
        self.btn_nav.clicked.connect(lambda: self.set_mode(0))
        self.btn_ruler = QPushButton("RULER"); self.btn_ruler.setCheckable(True)
        self.btn_ruler.clicked.connect(lambda: self.set_mode(1))
        self.btn_roi = QPushButton("ROI"); self.btn_roi.setCheckable(True)
        self.btn_roi.clicked.connect(lambda: self.set_mode(2))
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_nav); self.mode_group.addButton(self.btn_ruler); self.mode_group.addButton(self.btn_roi)
        self.left_layout.addWidget(self.btn_nav); self.left_layout.addWidget(self.btn_ruler); self.left_layout.addWidget(self.btn_roi)
        self.left_layout.addSpacing(20)
        
        # 4. Series List
        self.series_label = QLabel("SERIES LIST")
        self.left_layout.addWidget(self.series_label)
        self.series_list_widget = DraggableListWidget()
        self.series_list_widget.itemClicked.connect(self.on_series_clicked) 
        self.left_layout.addWidget(self.series_list_widget)
        self.open_btn = QPushButton("OPEN FOLDER")
        self.open_btn.clicked.connect(self.open_folder_dialog)
        self.left_layout.addWidget(self.open_btn)
        self.main_layout.addWidget(self.left_panel)

        # Right Panel
        self.right_panel = QWidget()
        self.grid_layout = QGridLayout(self.right_panel)
        self.grid_layout.setContentsMargins(0,0,0,0)
        self.grid_layout.setSpacing(2) 
        self.main_layout.addWidget(self.right_panel, 1)

    # --- ★変更: コンボボックスを見やすくしたスタイル ---
    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #050505; }
            QLabel { color: #00FF00; font-family: 'Consolas'; font-weight: bold; } 
            
            /* リストと共通パーツ */
            QListWidget {
                background-color: #111; border: 1px solid #005500; color: #00DD00; font-family: 'Consolas';
            }
            QListWidget::item:selected { background-color: #004400; color: #FFFFFF; }
            
            /* ボタン */
            QPushButton { 
                background-color: #1a1a1a; color: #00FF00; border: 1px solid #005500; padding: 8px; font-family: 'Consolas'; font-weight: bold;
            }
            QPushButton:hover { background-color: #003300; }
            QPushButton:checked { background-color: #FFFF00; color: #000000; border: 1px solid #FFFF00; }
            QPushButton:disabled { background-color: #111; color: #555; border: 1px solid #333; }
            
            /* 入力系 (スピンボックス・コンボボックス) */
            QSpinBox {
                background-color: #1a1a1a; color: #00FF00; border: 1px solid #005500; padding: 5px; font-family: 'Consolas';
            }
            
            /* ★コンボボックスの視認性向上 */
            QComboBox {
                background-color: #1a1a1a;
                color: #00FF00;
                border: 1px solid #005500;
                padding: 5px;
                padding-right: 20px; /* 矢印スペース確保 */
                font-family: 'Consolas';
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left-width: 1px;
                border-left-color: #005500;
                border-left-style: solid;
                background-color: #222; /* ボタン背景を少し明るく */
            }
            /* 下向き矢印をCSSで描画 */
            QComboBox::down-arrow {
                width: 0; 
                height: 0; 
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #00FF00; /* 緑の三角形 */
                margin-right: 5px;
            }
            /* ドロップダウンリストの中身 */
            QComboBox QAbstractItemView {
                background-color: #111;
                color: #00FF00;
                border: 1px solid #005500;
                selection-background-color: #004400;
            }
            /* 直接入力エリアのスタイル */
            QComboBox QLineEdit {
                color: #00FF00; 
                background-color: #1a1a1a;
                border: none;
            }
        """)

    def update_mip_settings(self):
        mode_idx = self.combo_mip_mode.currentIndex()
        mode_str = 'AVG'
        if mode_idx == 1: mode_str = 'MIP'
        elif mode_idx == 2: mode_str = 'MinIP'
        
        text = self.combo_thickness.currentText()
        thickness_mm = 0.0
        try:
            nums = re.findall(r"[-+]?\d*\.\d+|\d+", text)
            if nums: thickness_mm = float(nums[0])
        except: thickness_mm = 0.0
        
        for vp in self.selected_viewports:
            vp.set_mip_params(mode_str, thickness_mm)

    def toggle_mpr_mode(self):
        is_mpr = self.btn_mpr_enable.isChecked()
        self.update_mpr_buttons_state(is_mpr)
        for vp in self.selected_viewports:
            vp.toggle_mpr(is_mpr)
        if not is_mpr: self.btn_axial.setChecked(True)

    def update_mpr_buttons_state(self, enabled):
        self.btn_axial.setEnabled(enabled)
        self.btn_coronal.setEnabled(enabled)
        self.btn_sagittal.setEnabled(enabled)
        self.combo_mip_mode.setEnabled(enabled)
        self.combo_thickness.setEnabled(enabled)
        if enabled:
            self.mpr_label.setText("3D RECONSTRUCTION [ON]")
            self.mpr_label.setStyleSheet("color: #FF00FF;")
        else:
            self.mpr_label.setText("3D RECONSTRUCTION [OFF]")
            self.mpr_label.setStyleSheet("color: #555555;")

    def set_mpr_plane(self, plane):
        if not self.btn_mpr_enable.isChecked(): return
        for vp in self.selected_viewports: vp.set_view_plane(plane)

    def on_apply_grid_clicked(self):
        rows = self.spin_rows.value(); cols = self.spin_cols.value()
        self.update_grid_layout(rows, cols)
    def update_grid_layout(self, rows, cols):
        for i in reversed(range(self.grid_layout.count())): 
            widget = self.grid_layout.itemAt(i).widget()
            if widget: widget.setParent(None); widget.deleteLater()
        self.viewports = []
        self.selected_viewports = set()
        for r in range(rows):
            for c in range(cols):
                vp = ZetaViewport()
                vp.activated.connect(self.on_viewport_activated)
                vp.series_dropped.connect(self.on_viewport_series_dropped)
                vp.scrolled.connect(self.on_viewport_scrolled)
                vp.panned.connect(self.on_viewport_panned)
                vp.wl_changed.connect(self.on_viewport_wl_changed)
                vp.zoomed.connect(self.on_viewport_zoomed)
                vp.processing_start.connect(self.on_process_start)
                vp.processing_progress.connect(self.on_process_progress)
                vp.processing_finish.connect(self.on_process_finish)
                self.grid_layout.addWidget(vp, r, c)
                self.viewports.append(vp)
        if self.viewports: self.select_single_viewport(self.viewports[0])
    
    def on_process_start(self, message):
        self.progress_bar.setVisible(True); self.progress_bar.setValue(0); self.mpr_label.setText(f"BUSY: {message}")
    def on_process_progress(self, val): self.progress_bar.setValue(val)
    def on_process_finish(self):
        self.progress_bar.setVisible(False); self.mpr_label.setText("3D RECONSTRUCTION [ON]")

    def on_viewport_activated(self, viewport, modifiers):
        is_shift = (modifiers & Qt.KeyboardModifier.ShiftModifier)
        if is_shift:
            if viewport in self.selected_viewports:
                if len(self.selected_viewports) > 1:
                    viewport.set_active(False); self.selected_viewports.remove(viewport)
            else:
                viewport.set_active(True); self.selected_viewports.add(viewport)
        else:
            if viewport in self.selected_viewports: pass
            else: self.select_single_viewport(viewport)
        self.apply_tool_mode_to_selected()
        if self.selected_viewports:
            any_mpr = any(vp.is_mpr_enabled for vp in self.selected_viewports)
            self.btn_mpr_enable.setChecked(any_mpr)
            self.update_mpr_buttons_state(any_mpr)
            first = list(self.selected_viewports)[0]
            idx = 0
            if first.mip_mode == 'MIP': idx = 1
            elif first.mip_mode == 'MinIP': idx = 2
            self.combo_mip_mode.setCurrentIndex(idx)
            self.combo_thickness.setCurrentText(f"{first.slab_thickness_mm} mm")

    def select_single_viewport(self, viewport):
        for vp in self.viewports: vp.set_active(False)
        self.selected_viewports = {viewport}
        viewport.set_active(True)

    def on_viewport_scrolled(self, sender, steps):
        for vp in self.selected_viewports:
            if vp != sender: vp.scroll_step(steps, emit_sync=False)
    def on_viewport_panned(self, sender, dx, dy):
        for vp in self.selected_viewports:
            if vp != sender: vp.apply_pan(dx, dy)
    def on_viewport_wl_changed(self, sender, dw, dl):
        for vp in self.selected_viewports:
            if vp != sender: vp.apply_wl(dw, dl)
    def on_viewport_zoomed(self, sender, delta_factor):
        for vp in self.selected_viewports:
            if vp != sender: vp.apply_zoom(delta_factor)
    def on_viewport_series_dropped(self, target_viewport, uid):
        self.select_single_viewport(target_viewport)
        if uid in self.all_series_data:
            files = self.all_series_data[uid]['files']
            target_viewport.load_series(files)
    def set_mode(self, mode):
        if mode == 0: self.mode_label.setText("CONTROLLER MODE (NAV)"); self.mode_label.setStyleSheet("color: #00FF00;")
        elif mode == 1: self.mode_label.setText("CONTROLLER MODE (RULER)"); self.mode_label.setStyleSheet("color: #FFFF00;")
        elif mode == 2: self.mode_label.setText("CONTROLLER MODE (ROI)"); self.mode_label.setStyleSheet("color: #00FFFF;")
        self.apply_tool_mode_to_selected(mode)
    def apply_tool_mode_to_selected(self, mode=None):
        if mode is None:
            if self.btn_ruler.isChecked(): mode = 1
            elif self.btn_roi.isChecked(): mode = 2
            else: mode = 0
        for vp in self.selected_viewports: vp.set_tool_mode(mode)
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.accept()
        else: event.ignore()
    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if os.path.isdir(path): self.start_folder_scan(path)
            elif os.path.isfile(path): self.start_folder_scan(os.path.dirname(path))
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Delete or event.key() == Qt.Key.Key_Backspace:
            for vp in self.selected_viewports: vp.delete_measurement()
        super().keyPressEvent(event)
    def open_folder_dialog(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Select DICOM Folder")
        if folder_path: self.start_folder_scan(folder_path)
    def start_folder_scan(self, folder_path):
        self.series_list_widget.clear(); self.series_list_widget.addItem("Scanning...")
        self.scan_worker = DicomScanWorker(folder_path)
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.error.connect(self.on_worker_error)
        self.scan_worker.start()
    def on_scan_finished(self, series_info, message):
        self.all_series_data = series_info; self.series_list_widget.clear()
        for uid, info in series_info.items():
            count = len(info['files'])
            item = QListWidgetItem(f"[{info['modality']}] {info['desc']} ({count})")
            item.setData(Qt.ItemDataRole.UserRole, uid); self.series_list_widget.addItem(item)
    def on_series_clicked(self, item):
        if not self.selected_viewports: QMessageBox.warning(self, "Info", "No viewport selected."); return
        uid = item.data(Qt.ItemDataRole.UserRole)
        if uid in self.all_series_data:
            files = self.all_series_data[uid]['files']
            for vp in self.selected_viewports: vp.load_series(files)
    def on_worker_error(self, message): QMessageBox.warning(self, "Error", message)