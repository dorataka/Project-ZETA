from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QPen, QFont, QColor
from PyQt6.QtCore import Qt, QPointF, QPoint, QRectF
import math
import numpy as np

# --- ヘルパー関数 ---
def distance_point_to_segment(p, a, b):
    ab = b - a
    ap = p - a
    len_sq = ab.x()**2 + ab.y()**2
    if len_sq == 0:
        return math.sqrt(ap.x()**2 + ap.y()**2)
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
        
        self.measurements = []
        self.rois = []
        self.selected_type = None
        self.selected_index = None
        self.current_drawing_start = None 
        self.current_drawing_end = None
        self.current_mode = None 

        self.pixel_spacing = None
        self.current_slice_index = 0
        
        # ★追加: 表示アスペクト比 (デフォルト1.0)
        self.target_aspect_ratio = 1.0 

        self.setStyleSheet("background-color: #000000;")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True) 

    # ★変更: aspect_ratio 引数を追加
    def set_pixmap(self, pixmap, pixel_spacing=None, slice_index=0, hu_grid=None, aspect_ratio=1.0):
        self.pixmap = pixmap
        self.pixel_spacing = pixel_spacing
        self.current_slice_index = slice_index
        self.hu_grid = hu_grid 
        self.target_aspect_ratio = aspect_ratio # 記憶
        self.update()

    def reset_view(self):
        self.pan_x = 0
        self.pan_y = 0
        self.measurements = []
        self.rois = []
        self.selected_index = None
        self.selected_type = None
        self.current_drawing_start = None
        self.current_drawing_end = None
        self.target_aspect_ratio = 1.0
        self.update()

    def hit_test(self, screen_pos):
        if isinstance(screen_pos, QPoint):
            target_point = QPointF(screen_pos)
        else:
            target_point = screen_pos
        threshold = 8.0
        
        for i, roi in enumerate(self.rois):
            if roi.get('slice_index', -1) != self.current_slice_index: continue
            rect_img = roi['rect']
            top_left = self.image_to_screen(rect_img.topLeft())
            bottom_right = self.image_to_screen(rect_img.bottomRight())
            rect_scr = QRectF(top_left, bottom_right).normalized()
            cx = rect_scr.center().x()
            cy = rect_scr.center().y()
            rx = rect_scr.width() / 2.0
            ry = rect_scr.height() / 2.0
            if rx > 0 and ry > 0:
                normalized_dist = ((target_point.x() - cx) / rx)**2 + ((target_point.y() - cy) / ry)**2
                if normalized_dist <= 1.2: return ('roi', i)

        min_dist = float('inf')
        closest_ruler = None
        for i, m in enumerate(self.measurements):
            if m.get('slice_index', -1) != self.current_slice_index: continue
            p1 = self.image_to_screen(m['start'])
            p2 = self.image_to_screen(m['end'])
            dist = distance_point_to_segment(target_point, p1, p2)
            if dist < threshold and dist < min_dist:
                min_dist = dist
                closest_ruler = i
        if closest_ruler is not None: return ('ruler', closest_ruler)
        return (None, None)

    def delete_selected_measurement(self):
        if self.selected_index is None: return False
        if self.selected_type == 'ruler':
            if 0 <= self.selected_index < len(self.measurements):
                self.measurements.pop(self.selected_index)
                self.selected_index = None; self.selected_type = None; self.update(); return True
        elif self.selected_type == 'roi':
            if 0 <= self.selected_index < len(self.rois):
                self.rois.pop(self.selected_index)
                self.selected_index = None; self.selected_type = None; self.update(); return True
        return False

    def calculate_roi_stats(self, rect):
        if self.hu_grid is None: return "N/A"
        h, w = self.hu_grid.shape
        norm_rect = rect.normalized()
        x = int(norm_rect.x())
        y = int(norm_rect.y())
        rw = int(norm_rect.width())
        rh = int(norm_rect.height())
        if rw <= 0 or rh <= 0: return "N/A"
        x_start = max(0, x); y_start = max(0, y)
        x_end = min(w, x + rw + 1); y_end = min(h, y + rh + 1)
        if x_start >= x_end or y_start >= y_end: return "N/A"
        sub_img = self.hu_grid[y_start:y_end, x_start:x_end]
        cx = x + rw / 2.0; cy = y + rh / 2.0
        rx = rw / 2.0; ry = rh / 2.0
        y_idx, x_idx = np.ogrid[y_start:y_end, x_start:x_end]
        if rx == 0 or ry == 0: return "N/A"
        mask = ((x_idx - cx)**2 / rx**2) + ((y_idx - cy)**2 / ry**2) <= 1.0
        roi_values = sub_img[mask]
        if len(roi_values) == 0: return "N/A"
        mean_val = np.mean(roi_values)
        std_val = np.std(roi_values)
        max_val = np.max(roi_values)
        min_val = np.min(roi_values)
        if self.pixel_spacing:
            pixel_area = self.pixel_spacing[0] * self.pixel_spacing[1]
            area_mm2 = len(roi_values) * pixel_area
        else:
            area_mm2 = len(roi_values) 
        return mean_val, std_val, max_val, min_val, area_mm2

    # --- 座標変換 (アスペクト比対応) ---
    def screen_to_image(self, screen_pos):
        if self.pixmap is None: return None
        win_w, win_h = self.width(), self.height()
        img_w, img_h = self.pixmap.width(), self.pixmap.height()
        
        # ★アスペクト比を考慮した表示サイズ計算
        # 画像の高さを「見かけ上」target_aspect_ratio倍にする
        display_img_h = img_h * self.target_aspect_ratio
        
        # フィッティング計算
        scale = min(win_w / img_w, win_h / display_img_h)
        draw_w = int(img_w * scale)
        draw_h = int(display_img_h * scale)
        
        offset_x = (win_w - draw_w) // 2 + self.pan_x
        offset_y = (win_h - draw_h) // 2 + self.pan_y
        
        # 逆変換
        img_x = (screen_pos.x() - offset_x) / scale
        img_y = (screen_pos.y() - offset_y) / scale
        
        # Y軸はアスペクト比で割って元の画像座標に戻す
        img_y = img_y / self.target_aspect_ratio
        
        return QPointF(img_x, img_y)

    def image_to_screen(self, img_point):
        if self.pixmap is None: return QPointF(0,0)
        win_w, win_h = self.width(), self.height()
        img_w, img_h = self.pixmap.width(), self.pixmap.height()
        
        display_img_h = img_h * self.target_aspect_ratio
        scale = min(win_w / img_w, win_h / display_img_h)
        draw_w = int(img_w * scale)
        draw_h = int(display_img_h * scale)
        
        offset_x = (win_w - draw_w) // 2 + self.pan_x
        offset_y = (win_h - draw_h) // 2 + self.pan_y
        
        scr_x = img_point.x() * scale + offset_x
        # Y軸にアスペクト比を掛ける
        scr_y = (img_point.y() * self.target_aspect_ratio) * scale + offset_y
        
        return QPointF(scr_x, scr_y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))
        if self.pixmap is None:
            painter.setPen(QColor("#003300"))
            painter.setFont(QFont("Consolas", 14))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "[ NO SIGNAL ]")
            return

        win_w, win_h = self.width(), self.height()
        img_w, img_h = self.pixmap.width(), self.pixmap.height()
        
        # ★描画サイズ計算 (アスペクト比反映)
        display_img_h = img_h * self.target_aspect_ratio
        scale = min(win_w / img_w, win_h / display_img_h)
        draw_w = int(img_w * scale)
        draw_h = int(display_img_h * scale)

        offset_x = (win_w - draw_w) // 2 + self.pan_x
        offset_y = (win_h - draw_h) // 2 + self.pan_y

        # 画像描画 (指定した矩形に引き伸ばして描画される)
        target_rect = QRectF(float(offset_x), float(offset_y), float(draw_w), float(draw_h))
        # source_rect = QRectF(0, 0, img_w, img_h)
        # drawPixmap(target, pixmap, source)
        painter.drawPixmap(target_rect.toRect(), self.pixmap)

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
                dx_px = self.current_drawing_end.x() - self.current_drawing_start.x()
                dy_px = self.current_drawing_end.y() - self.current_drawing_start.y()
                # アスペクト比を考慮した距離計算は非常に複雑になるため、
                # MPR時は簡易的にピクセル距離、または軸ごとのSpacingを考慮する必要がある。
                # 現状は簡易実装とする。
                dist_px = math.sqrt(dx_px**2 + dy_px**2)
                if self.pixel_spacing:
                    dist_mm = dist_px * self.pixel_spacing[0] 
                    text = f"{dist_mm:.2f} mm"
                else:
                    text = f"{dist_px:.1f} px"
                self.draw_ruler(painter, p1, p2, text, QColor("#FFFF00"))
                
            elif self.current_mode == 'roi':
                rect_img = QRectF(self.current_drawing_start, self.current_drawing_end).normalized()
                rect_scr = QRectF(p1, p2).normalized()
                stats = self.calculate_roi_stats(rect_img)
                if stats != "N/A":
                    mean, std, mx, mn, area = stats
                    text = f"Mean:{mean:.1f} SD:{std:.1f}\nMax:{mx:.0f} Min:{mn:.0f}\nArea:{area:.0f}mm2"
                else:
                    text = "..."
                self.draw_roi(painter, rect_scr, text, QColor("#00FFFF"))

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