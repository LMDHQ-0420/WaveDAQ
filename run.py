"""Launcher for the DAQ application. This file keeps the original entrypoint
but delegates implementation to modules under core/ to preserve original logic
while making the project modular.
"""

import threading
from pyqtgraph.Qt import QtWidgets

from core.udp_receiver import udp_receive_thread
from core.plotter import WavePlotter


if __name__ == "__main__":
    t1 = threading.Thread(target=udp_receive_thread, daemon=True)
    t1.start()
    app = QtWidgets.QApplication([])
    win = WavePlotter()
    win.show()
    app.exec()