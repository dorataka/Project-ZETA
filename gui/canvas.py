from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QPen, QFont, QColor, QFontMetrics
from PyQt6.QtCore import Qt, QPointF, QPoint, QRectF
import math
import numpy as np

def distance_point_to_segment(p, a, b):
    ab = b - a
    ap = p - a
    len_sq = ab.x()**2 + ab.y()**2
    if len_sq == 0: return math.sqrt(ap.x()**2 + ap.y()**2)
    t = (ap.x() * ab.x() + ap.y() * ab.y()) / len_sq
    t = max(0.0, min(1.0, t))
    closest = a + t * ab
    dist = p - closest
    return math.sqrt(dist.x()**2 + dist.y()**2)

class ImageCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = None
        self.hu_grid = None 
        self.pan_x = 0
        self.pan_y = 0
        self.zoom_factor = 1.0
        
        self.measurements = []
        self.rois = []
        self.cross_ref_lines = []
        
        self.selected_type = None
        self.selected_index = None
        self.current_drawing_start = None 
        self.current_drawing_end = None
        self.current_mode = None 

        self.is_probe_active = False
        self.probe_pos = None

        self.pixel_spacing = None
        self.current_slice_index = 0
        
        self.overlay_data = {'TL': [], 'TR': [], 'BL': [], 'BR': [], 'Markers': {}}
        self.target_aspect_ratio = 1.0

        self.setStyleSheet("background-color: #000000;")
        
        # ★修正: ここを False -> True に変更しないと、クリックなしの移動を検知できません
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False) 
        
        # ★追加: マウス追跡を有効化 (これでクリックなしでも moveEvent が発生する)
        self.setMouseTracking(True)

    def set_pixmap(self, pixmap, pixel_spacing=None, slice_index=0, hu_grid=None, overlay_data=None, aspect_ratio=1.0):
        self.pixmap = pixmap
        self.pixel_spacing = pixel_spacing
        self.current_slice_index = slice_index
        self.hu_grid = hu_grid
        if overlay_data: self.overlay_data = overlay_data
        self.target_aspect_ratio = aspect_ratio
        self.update()

    def reset_view(self):
        self.pan_x = 0
        self.pan_y = 0
        self.zoom_factor = 1.0
        self.measurements = []
        self.rois = []
        self.cross_ref_lines = []
        self.selected_index = None
        self.selected_type = None
        self.current_drawing_start = None
        self.current_drawing_end = None
        self.target_aspect_ratio = 1.0
        self.update()

    def set_probe_active(self, active, pos=None):
        self.is_probe_active = active
        if pos: self.probe_pos = pos
        self.update()

    def update_probe_pos(self, pos):
        if self.is_probe_active:
            self.probe_pos = pos
            self.update()

    def get_scale_and_offset(self):
        if self.pixmap is None: return 1.0, 0, 0
        if math.isnan(self.zoom_factor) or math.isinf(self.zoom_factor) or self.zoom_factor <= 0.001: self.zoom_factor = 1.0
        if math.isnan(self.pan_x) or math.isinf(self.pan_x): self.pan_x = 0
        if math.isnan(self.pan_y) or math.isinf(self.pan_y): self.pan_y = 0
        
        win_w, win_h = self.width(), self.height()
        img_w, img_h = self.pixmap.width(), self.pixmap.height()
        display_h = img_h * self.target_aspect_ratio
        if display_h == 0: display_h = 1
        
        base_scale = min(win_w / img_w, win_h / display_h)
        final_scale = base_scale * self.zoom_factor
        
        draw_w = img_w * final_scale
        draw_h = display_h * final_scale
        offset_x = (win_w - draw_w) / 2 + self.pan_x
        offset_y = (win_h - draw_h) / 2 + self.pan_y
        return final_scale, offset_x, offset_y

    def screen_to_image(self, screen_pos):
        if self.pixmap is None: return None
        scale, off_x, off_y = self.get_scale_and_offset()
        if scale <= 0: return None
        img_x = (screen_pos.x() - off_x) / scale
        img_y = (screen_pos.y() - off_y) / scale
        img_y = img_y / self.target_aspect_ratio
        return QPointF(img_x, img_y)

    def image_to_screen(self, img_point):
        if self.pixmap is None: return QPointF(0,0)
        scale, off_x, off_y = self.get_scale_and_offset()
        scr_x = img_point.x() * scale + off_x
        scr_y = (img_point.y() * self.target_aspect_ratio) * scale + off_y
        return QPointF(scr_x, scr_y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))

        if self.pixmap is None:
            painter.setPen(QColor("#003300"))
            painter.setFont(QFont("Consolas", 14))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "[ NO SIGNAL ]")
            return

        if self.pixmap.isNull(): return

        scale, off_x, off_y = self.get_scale_and_offset()
        if scale <= 0.001: return

        img_w = self.pixmap.width()
        img_h = self.pixmap.height()
        draw_w = img_w * scale
        draw_h = (img_h * self.target_aspect_ratio) * scale
        target_rect = QRectF(off_x, off_y, draw_w, draw_h)
        
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(target_rect.toRect(), self.pixmap)

        self.draw_cross_refs(painter)
        self.draw_overlays(painter)

        painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        for i, m in enumerate(self.measurements):
            if m.get('slice_index', -1) != self.current_slice_index: continue
            is_selected = (self.selected_type == 'ruler' and i == self.selected_index)
            color = QColor("#FF0000") if is_selected else QColor("#FFFF00")
            p1 = self.image_to_screen(m['start'])
            p2 = self.image_to_screen(m['end'])
            self.draw_ruler(painter, p1, p2, m['dist_text'], color)

        for i, roi in enumerate(self.rois):
            if roi.get('slice_index', -1) != self.current_slice_index: continue
            is_selected = (self.selected_type == 'roi' and i == self.selected_index)
            color = QColor("#FF0000") if is_selected else QColor("#00FFFF")
            rect_img = roi['rect']
            top_left = self.image_to_screen(rect_img.topLeft())
            bottom_right = self.image_to_screen(rect_img.bottomRight())
            rect_scr = QRectF(top_left, bottom_right)
            self.draw_roi(painter, rect_scr, roi['text'], color)

        if self.current_drawing_start and self.current_drawing_end:
            p1 = self.image_to_screen(self.current_drawing_start)
            p2 = self.image_to_screen(self.current_drawing_end)
            if self.current_mode == 'ruler':
                dx_img = self.current_drawing_end.x() - self.current_drawing_start.x()
                dy_img = self.current_drawing_end.y() - self.current_drawing_start.y()
                dist_px = math.sqrt(dx_img**2 + (dy_img * self.target_aspect_ratio)**2)
                if self.pixel_spacing: dist_mm = dist_px * self.pixel_spacing[0]; text = f"{dist_mm:.2f} mm"
                else: text = f"{dist_px:.1f} px"
                self.draw_ruler(painter, p1, p2, text, QColor("#FFFF00"))
            elif self.current_mode == 'roi':
                rect_img = QRectF(self.current_drawing_start, self.current_drawing_end).normalized()
                rect_scr = QRectF(p1, p2).normalized()
                stats = self.calculate_roi_stats(rect_img)
                if stats != "N/A":
                    mean, std, mx, mn, area = stats
                    text = f"Mean:{mean:.1f} SD:{std:.1f}\nMax:{mx:.0f} Min:{mn:.0f}\nArea:{area:.0f}mm2"
                else: text = "..."
                self.draw_roi(painter, rect_scr, text, QColor("#00FFFF"))
        
        self.draw_probe(painter)

    def draw_probe(self, painter):
        if not self.is_probe_active or self.probe_pos is None: return
        img_pt = self.screen_to_image(self.probe_pos)
        if not img_pt: return
        ix, iy = int(img_pt.x()), int(img_pt.y())
        if self.hu_grid is not None:
            h, w = self.hu_grid.shape
            if 0 <= ix < w and 0 <= iy < h:
                val = self.hu_grid[iy, ix]
                text = f"HU: {int(val)}"
                x = self.probe_pos.x() + 15
                y = self.probe_pos.y() + 25
                if x + 80 > self.width(): x -= 100
                if y + 20 > self.height(): y -= 40
                
                font = QFont("Arial", 11, QFont.Weight.Bold)
                painter.setFont(font)
                fm = QFontMetrics(font)
                text_rect = fm.boundingRect(text)
                
                bg_rect = QRectF(x - 4, y - text_rect.height(), text_rect.width() + 8, text_rect.height() + 4)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, 180))
                painter.drawRoundedRect(bg_rect, 4, 4)
                
                painter.setPen(QColor("#00FF00"))
                painter.drawText(int(x), int(y), text)

    def draw_cross_refs(self, painter):
        if not self.cross_ref_lines: return
        
        painter.setClipRect(self.rect())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        
        for line in self.cross_ref_lines:
            color = line.get('color', QColor("#FFFF00"))
            pen = QPen(color)
            pen.setWidth(2)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            
            # ★修正: 「斜めの線」情報 (start/end) を持っている場合
            if 'start' in line and 'end' in line:
                p1 = self.image_to_screen(line['start'])
                p2 = self.image_to_screen(line['end'])
                painter.drawLine(p1, p2)
                
            # ★修正: 「従来の水平・垂直線」情報 (type/pos) を持っている場合
            # (ここを elif にしてキーの存在確認をしないと、KeyErrorになります)
            elif 'type' in line and 'pos' in line:
                pos_img = line['pos']
                if line['type'] == 'V':
                    p_top = self.image_to_screen(QPointF(pos_img, 0))
                    p_bottom = self.image_to_screen(QPointF(pos_img, self.pixmap.height()))
                    painter.drawLine(int(p_top.x()), 0, int(p_bottom.x()), self.height())
                elif line['type'] == 'H':
                    p_left = self.image_to_screen(QPointF(0, pos_img))
                    p_right = self.image_to_screen(QPointF(self.pixmap.width(), pos_img))
                    painter.drawLine(0, int(p_left.y()), self.width(), int(p_right.y()))
                    
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setClipping(False)

    def draw_overlays(self, painter):
        font = QFont("Consolas", 11, QFont.Weight.Bold); painter.setFont(font)
        margin_x = 10; margin_y = 10; line_height = 18; win_w = self.width(); win_h = self.height()
        def draw_lines(lines, align_x, align_y):
            for i, text in enumerate(lines):
                if not text: continue
                fm = QFontMetrics(font); text_w = fm.horizontalAdvance(text)
                if align_x == 'left': x = margin_x
                else: x = win_w - margin_x - text_w
                if align_y == 'top': y = margin_y + (i + 1) * line_height
                else: y = win_h - margin_y - (len(lines) - 1 - i) * line_height
                painter.setPen(QColor("#000000")); painter.drawText(int(x)+1, int(y)+1, text)
                painter.setPen(QColor("#FFFFFF")); painter.drawText(int(x), int(y), text)
        draw_lines(self.overlay_data.get('TL', []), 'left', 'top')
        draw_lines(self.overlay_data.get('TR', []), 'right', 'top')
        draw_lines(self.overlay_data.get('BL', []), 'left', 'bottom')
        draw_lines(self.overlay_data.get('BR', []), 'right', 'bottom')
        markers = self.overlay_data.get('Markers', {})
        marker_font = QFont("Arial", 14, QFont.Weight.Bold); painter.setFont(marker_font); fm = QFontMetrics(marker_font)
        def draw_marker(text, x, y):
            if not text: return
            painter.setPen(QColor("#000000")); painter.drawText(int(x)+1, int(y)+1, text)
            painter.setPen(QColor("#FFFF00")); painter.drawText(int(x), int(y), text)
        if 'T' in markers: t = markers['T']; w = fm.horizontalAdvance(t); draw_marker(t, (win_w - w)/2, margin_y + 20)
        if 'B' in markers: t = markers['B']; w = fm.horizontalAdvance(t); draw_marker(t, (win_w - w)/2, win_h - margin_y)
        if 'L' in markers: t = markers['L']; w = fm.horizontalAdvance(t); draw_marker(t, margin_x, win_h/2)
        if 'R' in markers: t = markers['R']; w = fm.horizontalAdvance(t); draw_marker(t, win_w - margin_x - w, win_h/2)

    def draw_ruler(self, painter, p1, p2, text, color):
        pen = QPen(color); pen.setWidth(2); painter.setPen(pen)
        painter.drawLine(p1, p2)
        r = 3.0
        painter.drawLine(QPointF(p1.x()-r, p1.y()-r), QPointF(p1.x()+r, p1.y()+r))
        painter.drawLine(QPointF(p1.x()-r, p1.y()+r), QPointF(p1.x()+r, p1.y()-r))
        painter.drawLine(QPointF(p2.x()-r, p2.y()-r), QPointF(p2.x()+r, p2.y()+r))
        painter.drawLine(QPointF(p2.x()-r, p2.y()+r), QPointF(p2.x()+r, p2.y()-r))
        mid_x = (p1.x() + p2.x()) / 2; mid_y = (p1.y() + p2.y()) / 2
        painter.setPen(QColor("#000000")); painter.drawText(int(mid_x)+1, int(mid_y)-6, text)
        painter.setPen(color); painter.drawText(int(mid_x), int(mid_y)-7, text)

    def draw_roi(self, painter, rect, text, color):
        pen = QPen(color); pen.setWidth(2); pen.setStyle(Qt.PenStyle.DashLine); painter.setPen(pen)
        painter.drawEllipse(rect)
        lines = text.split('\n'); line_height = 14
        text_x = int(rect.center().x()); text_y = int(rect.bottom() + 15)
        pen.setStyle(Qt.PenStyle.SolidLine)
        for i, line in enumerate(lines):
            y_pos = text_y + (i * line_height)
            painter.setPen(QColor("#000000")); painter.drawText(text_x, y_pos+1, line)
            painter.setPen(color); painter.drawText(text_x-1, y_pos, line)

    def hit_test(self, screen_pos):
        if isinstance(screen_pos, QPoint): target_point = QPointF(screen_pos)
        else: target_point = screen_pos
        
        # 1. ROIの判定
        for i, roi in enumerate(self.rois):
            if roi.get('slice_index', -1) != self.current_slice_index: continue
            rect_img = roi['rect']
            top_left = self.image_to_screen(rect_img.topLeft())
            bottom_right = self.image_to_screen(rect_img.bottomRight())
            rect_scr = QRectF(top_left, bottom_right).normalized()
            cx = rect_scr.center().x(); cy = rect_scr.center().y()
            rx = rect_scr.width() / 2.0; ry = rect_scr.height() / 2.0
            if rx > 0 and ry > 0:
                normalized_dist = ((target_point.x() - cx) / rx)**2 + ((target_point.y() - cy) / ry)**2
                if normalized_dist <= 1.2: return ('roi', i)

        # 2. 線（定規 または リファレンス線）の判定
        min_dist = float('inf')
        closest_item = None
        item_type = None

        # A. 計測定規 (Ruler) のチェック
        for i, m in enumerate(self.measurements):
            if m.get('slice_index', -1) != self.current_slice_index: continue
            p1 = self.image_to_screen(m['start'])
            p2 = self.image_to_screen(m['end'])
            dist = distance_point_to_segment(target_point, p1, p2)
            if dist < 8.0 and dist < min_dist:
                min_dist = dist
                closest_item = i
                item_type = 'ruler'
        
        # B. クロスリファレンス線のチェック
        if self.cross_ref_lines:
            for i, line in enumerate(self.cross_ref_lines):
                # start/end を持つ（斜め線）場合のみ判定
                if 'start' in line and 'end' in line:
                    p1 = self.image_to_screen(line['start'])
                    p2 = self.image_to_screen(line['end'])
                    dist = distance_point_to_segment(target_point, p1, p2)

                # ★追加: 垂直線 (Coronal/Sagittal画面)
                elif line.get('type') == 'V' and 'pos' in line:
                    # 垂直線との距離 = X座標の差の絶対値
                    # 線は画像上のX座標(pos)にあるので、スクリーン座標に変換して判定
                    line_x_screen = self.image_to_screen(QPointF(line['pos'], 0)).x()
                    dist = abs(target_point.x() - line_x_screen)
                
                # ★追加: 水平線 (Coronal/Sagittal画面)
                elif line.get('type') == 'H' and 'pos' in line:
                    # 水平線との距離 = Y座標の差の絶対値
                    line_y_screen = self.image_to_screen(QPointF(0, line['pos'])).y()
                    dist = abs(target_point.y() - line_y_screen)
                    
                # 定規よりも近ければこちらを優先（または同じ距離なら上書き）
                if dist < 8.0 and dist < min_dist:
                        min_dist = dist
                        closest_item = i
                        item_type = 'cross_ref'

        if closest_item is not None: return (item_type, closest_item)
        return (None, None)

    def delete_selected_measurement(self):
        if self.selected_index is None: return False
        if self.selected_type == 'ruler':
            if 0 <= self.selected_index < len(self.measurements):
                self.measurements.pop(self.selected_index); self.selected_index = None; self.selected_type = None; self.update(); return True
        elif self.selected_type == 'roi':
            if 0 <= self.selected_index < len(self.rois):
                self.rois.pop(self.selected_index); self.selected_index = None; self.selected_type = None; self.update(); return True
        return False

    def calculate_roi_stats(self, rect):
        if self.hu_grid is None: return "N/A"
        h, w = self.hu_grid.shape
        norm_rect = rect.normalized()
        x = int(norm_rect.x()); y = int(norm_rect.y()); rw = int(norm_rect.width()); rh = int(norm_rect.height())
        if rw <= 0 or rh <= 0: return "N/A"
        x_start = max(0, x); y_start = max(0, y); x_end = min(w, x + rw + 1); y_end = min(h, y + rh + 1)
        if x_start >= x_end or y_start >= y_end: return "N/A"
        sub_img = self.hu_grid[y_start:y_end, x_start:x_end]
        cx = x + rw / 2.0; cy = y + rh / 2.0; rx = rw / 2.0; ry = rh / 2.0
        y_idx, x_idx = np.ogrid[y_start:y_end, x_start:x_end]
        if rx == 0 or ry == 0: return "N/A"
        mask = ((x_idx - cx)**2 / rx**2) + ((y_idx - cy)**2 / ry**2) <= 1.0
        roi_values = sub_img[mask]
        if len(roi_values) == 0: return "N/A"
        mean_val = np.mean(roi_values); std_val = np.std(roi_values); max_val = np.max(roi_values); min_val = np.min(roi_values)
        if self.pixel_spacing: pixel_area = self.pixel_spacing[0] * self.pixel_spacing[1]; area_mm2 = len(roi_values) * pixel_area
        else: area_mm2 = len(roi_values) 
        return mean_val, std_val, max_val, min_val, area_mm2