import os
import csv
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
from datetime import datetime


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
    """显示详细信息与重采按钮的弹窗"""
    def __init__(self, data_record, record_index=None, parent=None):
        super().__init__(parent)
        self.data_record = data_record
        self.record_index = record_index
        self.parent_window = parent
        self.setWindowTitle(f"{data_record['name']} - 详细信息")
        self.setMinimumWidth(350)
        # 移除窗口标题栏的问号按钮
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint)

        layout = QtWidgets.QVBoxLayout(self)

        # --- 上半部分：信息展示 ---
        info_layout = QtWidgets.QFormLayout()
        info_layout.setContentsMargins(10, 10, 10, 10)
        
        start_time = data_record.get('start_time')
        end_time = data_record.get('end_time')
        num_samples = len(data_record['data'][0]) if data_record['data'] else 0
        duration = end_time - start_time if start_time and end_time else None

        info_layout.addRow("开始时间:", QtWidgets.QLabel(start_time.strftime('%H:%M:%S') if start_time else "N/A"))
        info_layout.addRow("结束时间:", QtWidgets.QLabel(end_time.strftime('%H:%M:%S') if end_time else "N/A"))
        info_layout.addRow("采样总时间:", QtWidgets.QLabel(str(duration).split('.')[0] if duration else "N/A"))
        info_layout.addRow("断面数:", QtWidgets.QLabel(str(num_samples)))
        
        layout.addLayout(info_layout)

        # --- 分隔线 ---
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # --- 下部：重采按钮与关闭 ---
        btn_layout = QtWidgets.QHBoxLayout()
        self.recollect_btn = QtWidgets.QPushButton("重采")
        self.recollect_btn.clicked.connect(self.on_recollect)
        btn_layout.addWidget(self.recollect_btn)
        close_btn = QtWidgets.QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def on_recollect(self):
        """触发父窗口的重采逻辑并关闭弹窗"""
        if not self.parent_window or self.record_index is None:
            QtWidgets.QMessageBox.warning(self, "错误", "无法找到重采目标。")
            return
        reply = QtWidgets.QMessageBox.question(self, "确认操作", 
                                               "重新采集将覆盖该记录的现有数据，是否继续？",
                                               QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                                               QtWidgets.QMessageBox.StandardButton.No)
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            # 调用父窗口的重采方法，但跳过父窗口的二次确认
            self.parent_window.recollect_data(self.record_index, confirm=False)
            self.accept()


class ExportDialog(QtWidgets.QDialog):
    """用于导出单条记录的通道选择与保存对话框"""
    def __init__(self, data_record, parent=None):
        super().__init__(parent)
        self.data_record = data_record
        self.parent_window = parent
        self.setWindowTitle(f"{data_record['name']} - 导出")
        self.setMinimumWidth(350)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint)

        layout = QtWidgets.QVBoxLayout(self)

        checkbox_grid = QtWidgets.QGridLayout()
        self.channel_checkboxes = []
        for i in range(8):
            cb = QtWidgets.QCheckBox(f"通道 {i+1}")
            cb.setChecked(True)
            self.channel_checkboxes.append(cb)
            checkbox_grid.addWidget(cb, i // 4, i % 4)
        layout.addLayout(checkbox_grid)

        row = QtWidgets.QHBoxLayout()
        self.btn_export_original = QtWidgets.QPushButton("导出原始")
        self.btn_export_filtered = QtWidgets.QPushButton("导出滤波结果")
        self.btn_export_original.clicked.connect(self.export_original)
        self.btn_export_filtered.clicked.connect(self.export_filtered)
        row.addWidget(self.btn_export_original)
        row.addWidget(self.btn_export_filtered)
        layout.addLayout(row)
        # 默认情况下滤波导出按钮由调用者根据阈值启用状态设置；先禁用
        self.btn_export_filtered.setEnabled(False)

    def _do_export(self, save_filtered=False):
        selected = [i for i, cb in enumerate(self.channel_checkboxes) if cb.isChecked()]
        if not selected:
            QtWidgets.QMessageBox.warning(self, "提示", "请至少选择一个通道进行导出。")
            return

        default_filename = getattr(self, 'default_filename', f"{self.data_record['name']}.csv")
        default_dir = getattr(self, 'default_dir', None)

        now = datetime.now()
        date_str = now.strftime('%Y%m%d')
        time_str = now.strftime('%H%M%S')

        processed = default_filename.replace('{name}', self.data_record.get('name', 'data'))
        processed = processed.replace('{date}', date_str).replace('{time}', time_str)

        append_date = getattr(self, 'append_date', False)
        append_time = getattr(self, 'append_time', False)
        has_date_placeholder = '{date}' in default_filename
        has_time_placeholder = '{time}' in default_filename

        base, ext = os.path.splitext(processed)
        if not ext:
            ext = '.csv'
        suffix = ''
        if append_date and not has_date_placeholder:
            suffix += '_' + date_str
        if append_time and not has_time_placeholder:
            suffix += '_' + time_str
        final_name = base + suffix + ext
        start_path = os.path.join(default_dir, final_name) if default_dir else final_name

        thr_enabled = getattr(self, 'threshold_enabled', False)
        thr_low = getattr(self, 'threshold_low', None)
        thr_high = getattr(self, 'threshold_high', None)

        if save_filtered:
            if not thr_enabled or thr_low is None or thr_high is None:
                QtWidgets.QMessageBox.warning(self, "提示", "阈值滤波未启用或阈值未设置，无法导出滤波结果。")
                return
            def fmt_val(v):
                s = ('%g' % float(v))
                s = s.replace('-', 'm').replace('.', 'p')
                return s
            thr_tag = f"_thr_{fmt_val(thr_low)}_{fmt_val(thr_high)}"
            base2 = base + thr_tag
            final_name = base2 + suffix + ext
            start_path = os.path.join(default_dir, final_name) if default_dir else final_name

        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "保存文件", start_path, "CSV Files (*.csv)")
        if path:
            try:
                data_to_export = []
                for i in selected:
                    arr = self.data_record['data'][i]
                    if save_filtered and thr_enabled and hasattr(self.parent_window, 'apply_filters'):
                        try:
                            filtered = self.parent_window.apply_filters(arr)
                            data_to_export.append(filtered)
                        except Exception:
                            data_to_export.append(arr)
                    else:
                        data_to_export.append(arr)

                transposed = np.array(data_to_export).T
                with open(path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerows(transposed)
                QtWidgets.QMessageBox.information(self, "成功", f"数据已成功导出到:\n{path}")
                self.accept()
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "错误", f"导出失败: {e}")

    def export_original(self):
        self._do_export(save_filtered=False)

    def export_filtered(self):
        self._do_export(save_filtered=True)


class DataControlPanel(QtWidgets.QWidget):
    """单个数据采集记录的控制面板"""
    def __init__(self, name, index, start_time, view_callback, details_callback, export_callback):
        super().__init__()
        self.index = index
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(4)

        # header: 左侧名称，右侧时间
        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        self.name_label = QtWidgets.QLabel(name)
        # time string
        time_text = start_time.strftime('%H:%M:%S') if isinstance(start_time, datetime) else (start_time or "")
        self.time_label = QtWidgets.QLabel(time_text)
        self.time_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        header_layout.addWidget(self.name_label, 1)
        header_layout.addWidget(self.time_label)
        main_layout.addLayout(header_layout)
        
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        separator.setStyleSheet("color: #e0e0e0;")

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        self.view_button = QtWidgets.QPushButton("查看")
        self.details_button = QtWidgets.QPushButton("详细")
        self.recollect_button = QtWidgets.QPushButton("导出")

        self.view_button.setFixedWidth(50)
        self.details_button.setFixedWidth(50)
        self.recollect_button.setFixedWidth(50)

        self.view_button.clicked.connect(lambda: view_callback(self.index))
        self.details_button.clicked.connect(lambda: details_callback(self.index))
        self.recollect_button.clicked.connect(lambda: export_callback(self.index))

        button_layout.addWidget(self.view_button)
        button_layout.addWidget(self.details_button)
        button_layout.addWidget(self.recollect_button)
        button_layout.addStretch()

        # separator placed after header
        main_layout.addWidget(separator)
        main_layout.addLayout(button_layout)
