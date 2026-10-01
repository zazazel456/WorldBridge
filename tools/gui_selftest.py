"""Headless check that the GUI can be built (used by run.sh after pruning Qt)."""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from worldbridge.gui.app import MainWindow  # noqa: E402

w = MainWindow(remember=False)
w.show()
for i in range(w.tabs.count()):
    w.tabs.setCurrentIndex(i)
    app.processEvents()
    w.grab()
w.close()
print("GUI ok")
