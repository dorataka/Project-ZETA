from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QLineEdit, QLabel)
from PyQt6.QtCore import Qt
import pydicom

class DicomTagWindow(QDialog):
    def __init__(self, dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DICOM Tag Viewer")
        self.resize(600, 700)
        self.dataset = dataset
        self.setup_ui()
        self.load_tags()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # ★変更: 目に優しいダークテーマのスタイルシートを適用
        self.setStyleSheet("""
            QDialog {
                background-color: #121212;
                color: #e0e0e0;
            }
            QLineEdit {
                background-color: #1e1e1e;
                color: #e0e0e0;
                border: 1px solid #444;
                padding: 6px;
                border-radius: 4px;
                font-family: 'Consolas', 'Courier New', monospace;
            }
            QLineEdit:focus {
                border: 1px solid #0078d4;
            }
            QTableWidget {
                background-color: #1e1e1e;
                color: #e0e0e0;
                gridline-color: #333333; /* 眩しくないグリッド線 */
                border: none;
                font-family: 'Consolas', 'Courier New', monospace; /* 等幅フォントで見やすく */
                font-size: 10pt;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QTableWidget::item:selected {
                background-color: #004c8c; /* 選択行は落ち着いた青 */
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #2d2d2d;
                color: #b0b0b0;
                padding: 4px;
                border: 1px solid #333333;
                font-weight: bold;
            }
            /* スクロールバーもダークに */
            QScrollBar:vertical {
                background: #1e1e1e;
                width: 12px;
            }
            QScrollBar::handle:vertical {
                background: #444;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                background: none;
            }
        """)

        # 検索バー
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search Tag, Name or Value...")
        self.search_bar.textChanged.connect(self.filter_tags)
        layout.addWidget(self.search_bar)

        # テーブル
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Tag", "Name", "VR", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch) 
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        # 行の高さを見やすく調整
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.verticalHeader().setVisible(False) # 行番号は不要なら隠す
        
        layout.addWidget(self.table)

    def load_tags(self):
        if not self.dataset: return
        
        self.table.setRowCount(0)
        row = 0
        
        # 再帰的に全てのタグを取得するのは複雑になるので、まずはフラットに表示
        for elem in self.dataset.iterall():
            self.table.insertRow(row)
            
            # Tag (0010, 0010) のカッコを外してシンプルに
            tag_str = f"{elem.tag}".replace("(", "").replace(")", "").upper()
            tag_item = QTableWidgetItem(tag_str)
            tag_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, tag_item)
            
            # Name
            name_str = elem.name
            self.table.setItem(row, 1, QTableWidgetItem(name_str))
            
            # VR
            vr_str = elem.VR
            vr_item = QTableWidgetItem(vr_str)
            vr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, vr_item)
            
            # Value (長すぎる場合はカット)
            val_str = str(elem.value)
            if len(val_str) > 200: val_str = val_str[:200] + "..."
            self.table.setItem(row, 3, QTableWidgetItem(val_str))
            
            row += 1

    def filter_tags(self, text):
        text = text.lower()
        for i in range(self.table.rowCount()):
            match = False
            for j in range(4):
                item = self.table.item(i, j)
                if item and text in item.text().lower():
                    match = True
                    break
            self.table.setRowHidden(i, not match)