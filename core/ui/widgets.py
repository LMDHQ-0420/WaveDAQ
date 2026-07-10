import os
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
from datetime import datetime

from core.export.csv_exporter import build_filepath, export_to_csv


class CustomLinearRegionItem(pg.LinearRegionItem):
    sigDragStarted = QtCore.Signal()
    sigDragFinished = QtCore.Signal()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.sigDragStarted.emit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.sigDragFinished.emit()
        super().mouseReleaseEvent(event)


class DetailsDialog(QtWidgets.QDialog):
    def __init__(self, data_record, record_index=None, parent=None):
        super().__init__(parent)
        self.data_record = data_record
        self.record_index = record_index
        self._parent_window = parent
        self.setWindowTitle(f"{data_record['name']} - 详细信息")
        self.setMinimumWidth(350)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint)

        layout = QtWidgets.QVBoxLayout(self)

        info = QtWidgets.QFormLayout()
        info.setContentsMargins(10, 10, 10, 10)
        start_time = data_record.get('start_time')
        end_time = data_record.get('end_time')
        num_samples = len(data_record['data'][0]) if data_record['data'] else 0
        duration = end_time - start_time if start_time and end_time else None
        info.addRow("开始时间:", QtWidgets.QLabel(start_time.strftime('%H:%M:%S') if start_time else "N/A"))
        info.addRow("结束时间:", QtWidgets.QLabel(end_time.strftime('%H:%M:%S') if end_time else "N/A"))
        info.addRow("采样总时间:", QtWidgets.QLabel(str(duration).split('.')[0] if duration else "N/A"))
        info.addRow("断面数:", QtWidgets.QLabel(str(num_samples)))
        layout.addLayout(info)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        btn_row = QtWidgets.QHBoxLayout()
        recollect_btn = QtWidgets.QPushButton("重采")
        recollect_btn.clicked.connect(self._on_recollect)
        close_btn = QtWidgets.QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(recollect_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _on_recollect(self):
        if not self._parent_window or self.record_index is None:
            QtWidgets.QMessageBox.warning(self, "错误", "无法找到重采目标。")
            return
        reply = QtWidgets.QMessageBox.question(
            self, "确认操作",
            "重新采集将覆盖该记录的现有数据，是否继续？",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self._parent_window._recollect_data(self.record_index, confirm=False)
            self.accept()


class ExportDialog(QtWidgets.QDialog):
    def __init__(self, data_record, parent=None):
        super().__init__(parent)
        self.data_record = data_record
        self._parent_window = parent
        self.setWindowTitle(f"{data_record['name']} - 导出")
        self.setMinimumWidth(350)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint)

        # Export settings (set by caller before exec)
        self.default_dir = None
        self.default_filename = None
        self.append_date = False
        self.append_time = False
        self.threshold_enabled = False
        self.threshold_low = 0.0
        self.threshold_high = 0.0

        layout = QtWidgets.QVBoxLayout(self)

        grid = QtWidgets.QGridLayout()
        self.channel_checkboxes = []
        for i in range(8):
            cb = QtWidgets.QCheckBox(f"通道 {i+1}")
            cb.setChecked(True)
            self.channel_checkboxes.append(cb)
            grid.addWidget(cb, i // 4, i % 4)
        layout.addLayout(grid)

        btn_row = QtWidgets.QHBoxLayout()
        self.btn_export_original = QtWidgets.QPushButton("导出原始")
        self.btn_export_filtered = QtWidgets.QPushButton("导出滤波结果")
        self.btn_export_original.clicked.connect(self._export_original)
        self.btn_export_filtered.clicked.connect(self._export_filtered)
        self.btn_export_filtered.setEnabled(False)
        btn_row.addWidget(self.btn_export_original)
        btn_row.addWidget(self.btn_export_filtered)
        layout.addLayout(btn_row)

    def _export_original(self):
        self._do_export(filtered=False)

    def _export_filtered(self):
        self._do_export(filtered=True)

    def _do_export(self, filtered: bool):
        selected = [i for i, cb in enumerate(self.channel_checkboxes) if cb.isChecked()]
        if not selected:
            QtWidgets.QMessageBox.warning(self, "提示", "请至少选择一个通道进行导出。")
            return

        if filtered and not self.threshold_enabled:
            QtWidgets.QMessageBox.warning(self, "提示", "阈值滤波未启用，无法导出滤波结果。")
            return

        filter_suffix = None
        if filtered:
            def fmt(v):
                return ('%g' % float(v)).replace('-', 'm').replace('.', 'p')
            filter_suffix = f"_thr_{fmt(self.threshold_low)}_{fmt(self.threshold_high)}"

        suggested = build_filepath(
            record_name=self.data_record.get('name', 'data'),
            default_filename=self.default_filename,
            default_dir=self.default_dir,
            append_date=self.append_date,
            append_time=self.append_time,
            filter_suffix=filter_suffix,
        )

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "保存文件", suggested, "CSV Files (*.csv)")
        if not path:
            return

        try:
            export_to_csv(
                data=self.data_record['data'],
                channels=selected,
                filepath=path,
                filtered=filtered,
                filter_low=self.threshold_low,
                filter_high=self.threshold_high,
            )
            QtWidgets.QMessageBox.information(self, "成功", f"数据已成功导出到:\n{path}")
            self.accept()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "错误", f"导出失败: {e}")


class DataControlPanel(QtWidgets.QWidget):
    def __init__(self, name, index, start_time, view_callback, details_callback, export_callback):
        super().__init__()
        self.index = index
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.name_label = QtWidgets.QLabel(name)
        time_text = start_time.strftime('%H:%M:%S') if isinstance(start_time, datetime) else (start_time or "")
        self.time_label = QtWidgets.QLabel(time_text)
        self.time_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        header.addWidget(self.name_label, 1)
        header.addWidget(self.time_label)
        layout.addLayout(header)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        sep.setStyleSheet("color: #e0e0e0;")
        layout.addWidget(sep)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        for label, cb in [("查看", view_callback), ("详细", details_callback), ("导出", export_callback)]:
            btn = QtWidgets.QPushButton(label)
            btn.setFixedWidth(50)
            btn.clicked.connect(lambda _, f=cb: f(self.index))
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
