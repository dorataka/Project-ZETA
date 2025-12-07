import sys
from PyQt6.QtWidgets import QApplication
from gui.splash import ZetaSplashScreen
from gui.main_window import ZetaViewer
import time

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 1. スプラッシュ起動
    splash = ZetaSplashScreen()
    splash.show()

    # 2. 起動ログのアニメーション
    for _ in range(18): # 行数と合わせる
        if not splash.progress():
            break
        time.sleep(0.12)
        app.processEvents()

    time.sleep(1.0)
    
    # 3. メイン画面起動
    window = ZetaViewer()
    window.show()
    
    splash.finish(window)
    
    sys.exit(app.exec())