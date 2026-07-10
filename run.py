import socket
import threading

from pyqtgraph.Qt import QtWidgets

from core.acquisition.data_manager import DataManager
from core.acquisition.udp_receiver import udp_receive_thread
from core.ui.main_window import WavePlotter

UDP_PORT = 8080
BUFFER_SIZE = 20_000_000

if __name__ == "__main__":
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", UDP_PORT))
    sock.settimeout(2.0)

    dm = DataManager()

    t = threading.Thread(target=udp_receive_thread, args=(dm, sock), daemon=True)
    t.start()

    app = QtWidgets.QApplication([])
    win = WavePlotter(dm, sock)
    win.show()
    app.exec()