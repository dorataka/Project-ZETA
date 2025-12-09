from PyQt6.QtWidgets import QWidget, QPushButton, QMenu, QWidgetAction, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen

class GridSelectorWidget(QWidget):
    # 行と列を通知するシグナル
    selected = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.max_rows = 5
        self.max_cols = 5
        self.cell_size = 25
        self.hover_row = 0
        self.hover_col = 0
        
        # ウィジェットのサイズを固定 (余白を考慮)
        w = self.max_cols * self.cell_size + 1
        h = self.max_rows * self.cell_size + 25 # 下部にテキスト表示用スペース
        self.setFixedSize(w, h)
        self.setMouseTracking(True) # マウス移動を常に検知

    def mouseMoveEvent(self, event):
        # マウス位置から現在の行・列を計算
        x = event.position().x()
        y = event.position().y()
        
        c = int(x // self.cell_size) + 1
        r = int(y // self.cell_size) + 1
        
        # 範囲制限
        c = max(1, min(c, self.max_cols))
        r = max(1, min(r, self.max_rows))
        
        if c != self.hover_col or r != self.hover_row:
            self.hover_col = c
            self.hover_row = r
            self.update() # 再描画

    def mousePressEvent(self, event):
        # クリックで確定
        self.selected.emit(self.hover_row, self.hover_col)

    def paintEvent(self, event):
        painter = QPainter(self)
        
        # 背景
        painter.fillRect(self.rect(), QColor("#1a1a1a"))
        
        # グリッド描画
        pen = QPen(QColor("#555555"))
        pen.setWidth(1)
        painter.setPen(pen)
        
        for r in range(self.max_rows):
            for c in range(self.max_cols):
                x = c * self.cell_size
                y = r * self.cell_size
                
                # 選択範囲内なら緑、それ以外は黒
                if r < self.hover_row and c < self.hover_col:
                    painter.fillRect(x, y, self.cell_size, self.cell_size, QColor("#005500"))
                else:
                    painter.fillRect(x, y, self.cell_size, self.cell_size, QColor("#000000"))
                
                painter.drawRect(x, y, self.cell_size, self.cell_size)

        # 下部に現在のサイズを表示
        text = f"{self.hover_row} x {self.hover_col}"
        painter.setPen(QColor("#00FF00"))
        # テキストを下部中央に配置
        rect = self.rect()
        rect.setTop(self.max_rows * self.cell_size)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

class GridSelectionButton(QPushButton):
    grid_changed = pyqtSignal(int, int)

    def __init__(self, text="GRID", parent=None):
        super().__init__(text, parent)
        self.setCheckable(False)
        self.menu = QMenu(self)
        self.menu.setStyleSheet("QMenu { border: 1px solid #005500; background-color: #1a1a1a; }")
        
        # カスタムウィジェットをメニューのアクションとして配置
        self.grid_widget = GridSelectorWidget()
        self.grid_widget.selected.connect(self.on_grid_selected)
        
        action = QWidgetAction(self.menu)
        action.setDefaultWidget(self.grid_widget)
        self.menu.addAction(action)
        
        self.setMenu(self.menu)

    def on_grid_selected(self, rows, cols):
        self.menu.hide() # メニューを閉じる
        self.setText(f"GRID: {rows}x{cols}")
        self.grid_changed.emit(rows, cols)