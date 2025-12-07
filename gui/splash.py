from PyQt6.QtWidgets import QSplashScreen
from PyQt6.QtGui import QPixmap, QFont, QColor
from PyQt6.QtCore import Qt

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
            "Activating Overlay HUD System...",
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