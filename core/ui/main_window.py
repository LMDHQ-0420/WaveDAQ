import gc
import socket
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore

from core.acquisition.data_manager import DataManager, MAX_COLLECTIONS
from core.ui.plot_controller import PlotController
from core.ui.widgets import CustomLinearRegionItem, DataControlPanel, DetailsDialog, ExportDialog
from core.export.csv_exporter import build_filepath, export_to_csv


class WavePlotter(QtWidgets.QWidget):
    def __init__(self, data_manager: DataManager, sock: socket.socket):
        super().__init__()
        self.dm = data_manager
        self.sock = sock
        self.setWindowTitle("8通道数据采集操作台")
        self.resize(1200, 800)

        self.recollect_target_index = None
        self.save_dir = None
        self.default_filename = None
        self.append_date = False
        self.append_time = False

        self.default_colors = [
            '#FF7F50', '#8A2BE2', '#00CED1', '#FFD700',
            '#FF69B4', '#00FF7F', '#1E90FF', '#FF8C00',
        ]

        self._build_ui()
        self._init_plot_controller()
        self._connect_signals()

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._on_timer)
        self.timer.start(33)

    # ------------------------------------------------------------------ #
    # UI construction                                                       #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        main_layout = QtWidgets.QHBoxLayout(self)

        # --- Left panel ---
        left = QtWidgets.QVBoxLayout()

        btn_row = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton("▶ 开始")
        self.stop_button = QtWidgets.QPushButton("■ 结束")
        self.start_button.setStyleSheet(
            "QPushButton{background:#28a745;color:white;border:none;padding:5px;border-radius:3px;}"
            "QPushButton:disabled{background:#6c757d;}")
        self.stop_button.setStyleSheet(
            "QPushButton{background:#dc3545;color:white;border:none;padding:5px;border-radius:3px;}"
            "QPushButton:disabled{background:#6c757d;}")
        self.stop_button.setEnabled(False)
        btn_row.addWidget(self.start_button)
        btn_row.addWidget(self.stop_button)
        left.addLayout(btn_row)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:1px solid black;}")
        scroll.setMinimumWidth(200)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_content = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.scroll_content)
        left.addWidget(scroll, 1)

        channel_grid = QtWidgets.QGridLayout()
        self.color_buttons = []
        self.checkboxes = []
        for i in range(8):
            row = QtWidgets.QHBoxLayout()
            btn = QtWidgets.QPushButton("")
            btn.setFixedSize(24, 24)
            btn.setStyleSheet(
                f"background-color:{pg.mkColor(self.default_colors[i]).name()}; border:1px solid gray;")
            btn.clicked.connect(lambda _, idx=i: self._change_curve_color(idx))
            row.addWidget(btn)
            self.color_buttons.append(btn)
            cb = QtWidgets.QCheckBox(f'通道{i+1}')
            cb.setChecked(True)
            cb.stateChanged.connect(self._update_visibility)
            row.addWidget(cb)
            self.checkboxes.append(cb)
            channel_grid.addLayout(row, i // 2, i % 2)
        left.addLayout(channel_grid)

        bottom_btns = QtWidgets.QHBoxLayout()
        self.defaults_btn = QtWidgets.QPushButton("默认设置")
        self.filter_btn = QtWidgets.QPushButton("滤波设置")
        self.defaults_btn.clicked.connect(self._open_defaults_dialog)
        self.filter_btn.clicked.connect(self._open_filter_dialog)
        bottom_btns.addWidget(self.defaults_btn)
        bottom_btns.addWidget(self.filter_btn)
        left.addLayout(bottom_btns)

        main_layout.addLayout(left, stretch=0)

        # --- Right plot area ---
        plot_layout = QtWidgets.QVBoxLayout()

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMouseEnabled(x=True, y=False)
        self.plot_widget.hideButtons()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        plot_layout.addWidget(self.plot_widget, stretch=1)

        self.filtered_plot = pg.PlotWidget()
        self.filtered_plot.setMouseEnabled(x=True, y=False)
        self.filtered_plot.hideButtons()
        self.filtered_plot.showGrid(x=True, y=True, alpha=0.3)
        self.filtered_plot.setVisible(False)
        plot_layout.addWidget(self.filtered_plot, stretch=1)

        overview_row = QtWidgets.QHBoxLayout()
        self.overview_plot = pg.PlotWidget()
        self.overview_plot.setFixedHeight(80)
        self.overview_plot.setMouseEnabled(x=False, y=False)
        self.overview_plot.hideAxis('left')
        self.overview_plot.hideButtons()
        overview_row.addWidget(self.overview_plot)

        ctrl_col = QtWidgets.QVBoxLayout()
        self.reset_button = QtWidgets.QPushButton("复位")
        self.reset_button.setFixedWidth(50)
        self.reset_button.clicked.connect(self._reset_zoom)
        ctrl_col.addWidget(self.reset_button)
        self.bg_color_button = QtWidgets.QPushButton("背景")
        self.bg_color_button.setFixedWidth(50)
        self.bg_color_button.clicked.connect(self._change_background_color)
        ctrl_col.addWidget(self.bg_color_button)
        self.clear_all_button = QtWidgets.QPushButton("清除")
        self.clear_all_button.setFixedWidth(50)
        self.clear_all_button.setStyleSheet(
            "QPushButton{background:#dc3545;color:white;border:none;padding:3px;border-radius:5px;}")
        self.clear_all_button.clicked.connect(self._clear_all_data)
        ctrl_col.addWidget(self.clear_all_button)
        self.guide_button = QtWidgets.QPushButton("指南")
        self.guide_button.setFixedWidth(50)
        self.guide_button.clicked.connect(self._open_guide_dialog)
        ctrl_col.addWidget(self.guide_button)
        overview_row.addLayout(ctrl_col)
        plot_layout.addLayout(overview_row, stretch=1)

        self.status_label = QtWidgets.QLabel("无采集数据。")
        plot_layout.addWidget(self.status_label)

        main_layout.addLayout(plot_layout, stretch=1)

    def _init_plot_controller(self):
        self.curves = []
        self.overview_curves = []
        self.filtered_curves = []
        for i in range(8):
            c = self.plot_widget.plot(
                pen=pg.mkPen(color=self.default_colors[i], width=1),
                name=f'通道{i+1}',
            )
            self.curves.append(c)
            oc = self.overview_plot.plot(pen=pg.mkPen(color=self.default_colors[i], width=0.8))
            self.overview_curves.append(oc)
            fc = self.filtered_plot.plot(
                pen=pg.mkPen(color=self.default_colors[i], width=1,
                             style=QtCore.Qt.PenStyle.DashLine),
            )
            self.filtered_curves.append(fc)

        self.region = CustomLinearRegionItem()
        normal_pen = pg.mkPen(color='#FFD700', width=3)
        hover_pen = pg.mkPen(color='w', width=4)
        self._active_pen = pg.mkPen(color='w', width=4)
        self._normal_pen = normal_pen
        self._hover_pen = hover_pen
        for line in self.region.lines:
            line.setPen(normal_pen)
            line.setHoverPen(hover_pen)
        self.region.setZValue(10)
        self.overview_plot.addItem(self.region, ignoreBounds=True)

        self.pc = PlotController(
            plot_widget=self.plot_widget,
            overview_plot=self.overview_plot,
            filtered_plot=self.filtered_plot,
            region=self.region,
            curves=self.curves,
            overview_curves=self.overview_curves,
            filtered_curves=self.filtered_curves,
            checkboxes=self.checkboxes,
            data_manager=self.dm,
        )

    def _connect_signals(self):
        self.start_button.clicked.connect(self._start_collection)
        self.stop_button.clicked.connect(self._stop_collection)

        self.region.sigDragStarted.connect(self._on_region_drag_start)
        self.region.sigDragFinished.connect(self._on_region_drag_finish)
        self.region.sigRegionChanged.connect(self.pc.on_region_changed)

        self.plot_widget.getViewBox().sigRangeChangedManually.connect(self.pc.on_manual_pan_zoom)
        self.plot_widget.sigXRangeChanged.connect(self.pc.on_main_plot_changed)
        self.plot_widget.scene().sigMouseClicked.connect(self._on_plot_double_clicked)

        self.overview_plot.enterEvent = self.pc.on_overview_enter
        self.overview_plot.leaveEvent = self.pc.on_overview_leave

        try:
            self.filtered_plot.getViewBox().sigRangeChangedManually.connect(
                self.pc.on_filtered_plot_changed)
        except Exception:
            self.filtered_plot.sigXRangeChanged.connect(self.pc.on_filtered_plot_changed)

    # ------------------------------------------------------------------ #
    # Timer                                                                 #
    # ------------------------------------------------------------------ #

    def _on_timer(self):
        self.pc.update()
        self._update_status_label()

    # ------------------------------------------------------------------ #
    # Collection control                                                    #
    # ------------------------------------------------------------------ #

    def _start_collection(self):
        if (len(self.dm.collected_data) >= MAX_COLLECTIONS
                and self.recollect_target_index is None):
            QtWidgets.QMessageBox.warning(
                self, "提示", f"最多只能采集 {MAX_COLLECTIONS} 个数据。")
            return
        self.dm.start_collection()
        self.pc.switch_view(-1)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self._update_status_label()

    def _stop_collection(self):
        record = self.dm.stop_collection()
        if record is None:
            return
        if self.recollect_target_index is not None:
            idx = self.recollect_target_index
            record['name'] = self.dm.collected_data[idx]['name']
            self.dm.overwrite_record(idx, record)
            self.pc.switch_view(idx)
            try:
                for i in range(self.scroll_layout.count()):
                    w = self.scroll_layout.itemAt(i).widget()
                    if w and getattr(w, 'index', None) == idx:
                        if hasattr(w, 'time_label') and record['start_time']:
                            w.time_label.setText(record['start_time'].strftime('%H:%M:%S'))
                        break
            except Exception:
                pass
            self.recollect_target_index = None
        else:
            new_idx = len(self.dm.collected_data)
            display_name = f"数据{new_idx + 1}"
            self.dm.commit_record(record, display_name)
            self._add_record_panel(display_name, new_idx, record['start_time'])
            self.pc.switch_view(new_idx)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self._update_status_label()

    def _recollect_data(self, index, confirm=True):
        if self.dm.is_collecting:
            QtWidgets.QMessageBox.warning(self, "操作提示", "请先结束当前的采集任务。")
            return
        name = self.dm.collected_data[index]['name']
        if confirm:
            reply = QtWidgets.QMessageBox.question(
                self, "确认操作",
                f"重新采集将覆盖 <b>{name}</b> 的现有数据，\n是否继续？",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No)
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self.recollect_target_index = index
        self._start_collection()

    # ------------------------------------------------------------------ #
    # Record panel                                                          #
    # ------------------------------------------------------------------ #

    def _add_record_panel(self, name, index, start_time):
        panel = DataControlPanel(
            name, index, start_time,
            self._view_data, self._show_details, self._export_record,
        )
        self.scroll_layout.insertWidget(0, panel)

    def _view_data(self, index):
        if self.dm.is_collecting:
            QtWidgets.QMessageBox.warning(self, "操作提示", "请先结束当前的采集任务。")
            return
        self.pc.switch_view(index)
        self._update_status_label()

    def _show_details(self, index):
        if index < len(self.dm.collected_data):
            dlg = DetailsDialog(self.dm.collected_data[index], index, self)
            dlg.exec()

    def _export_record(self, index):
        if index < 0 or index >= len(self.dm.collected_data):
            return
        record = self.dm.collected_data[index]
        dlg = ExportDialog(record, self)
        if self.save_dir:
            dlg.default_dir = self.save_dir
        if self.default_filename:
            dlg.default_filename = self.default_filename
        dlg.append_date = self.append_date
        dlg.append_time = self.append_time
        dlg.threshold_enabled = self.pc.threshold_enabled
        dlg.threshold_low = self.pc.threshold_low
        dlg.threshold_high = self.pc.threshold_high
        if hasattr(dlg, 'btn_export_filtered'):
            dlg.btn_export_filtered.setEnabled(self.pc.threshold_enabled)
        dlg.exec()

    # ------------------------------------------------------------------ #
    # Plot interactions                                                     #
    # ------------------------------------------------------------------ #

    def _reset_zoom(self):
        self.pc.reset_zoom()
        self._update_status_label()

    def _on_plot_double_clicked(self, event):
        if event.double():
            self._reset_zoom()

    def _on_region_drag_start(self):
        self.pc.auto_pan_enabled = False
        self.region.lines[0].setPen(self._active_pen)
        self.region.lines[1].setPen(self._active_pen)

    def _on_region_drag_finish(self):
        for line in self.region.lines:
            line.setPen(self._normal_pen)
            line.setHoverPen(self._hover_pen)

    def _update_visibility(self):
        for i, cb in enumerate(self.checkboxes):
            self.curves[i].setVisible(cb.isChecked())
            self.overview_curves[i].setVisible(cb.isChecked())

    def _change_curve_color(self, idx):
        color = QtWidgets.QColorDialog.getColor()
        if color.isValid():
            pen = pg.mkPen(color=color, width=1)
            self.curves[idx].setPen(pen)
            self.overview_curves[idx].setPen(pen)
            self.color_buttons[idx].setStyleSheet(
                f"background-color:{color.name()}; border:1px solid gray;")

    def _change_background_color(self):
        color = QtWidgets.QColorDialog.getColor()
        if color.isValid():
            self.plot_widget.setBackground(color)
            self.overview_plot.setBackground(color)

    # ------------------------------------------------------------------ #
    # Clear all                                                             #
    # ------------------------------------------------------------------ #

    def _clear_all_data(self):
        if self.dm.is_collecting:
            QtWidgets.QMessageBox.warning(self, "操作禁止", "正在采集中，无法清除数据，请先结束采集。")
            return
        reply = QtWidgets.QMessageBox.question(
            self, "确认清除",
            "此操作将清除所有已采集的数据并无法恢复，是否继续？",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.dm.clear_all()
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for c in self.curves + self.overview_curves + self.filtered_curves:
            c.clear()
        self.pc.current_view_index = -1
        self.pc._last_render_len = -1
        gc.collect()
        self._update_status_label()

    # ------------------------------------------------------------------ #
    # Status label                                                          #
    # ------------------------------------------------------------------ #

    def _update_status_label(self):
        dm = self.dm
        pc = self.pc
        if dm.is_collecting:
            if self.recollect_target_index is not None:
                text = f"正在重采数据{self.recollect_target_index + 1}..."
            else:
                text = f"正在采集数据{len(dm.collected_data) + 1}..."
        else:
            if pc.current_view_index == -1:
                text = "无采集数据。"
            else:
                text = f"正在查看数据{pc.current_view_index + 1}。"
        if pc.threshold_enabled:
            text += f"  |  滤波: 已启用 (幅值 {pc.threshold_low:.2f} ~ {pc.threshold_high:.2f})"
        else:
            text += "  |  滤波: 已禁用"
        self.status_label.setText(text)

    # ------------------------------------------------------------------ #
    # Settings dialogs                                                      #
    # ------------------------------------------------------------------ #

    def _open_defaults_dialog(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("默认设置")
        dlg.setMinimumWidth(420)
        v = QtWidgets.QVBoxLayout(dlg)

        v.addWidget(QtWidgets.QLabel("默认保存路径:"))
        path_row = QtWidgets.QHBoxLayout()
        path_edit = QtWidgets.QLineEdit(self.save_dir or "")
        browse_btn = QtWidgets.QPushButton("浏览")

        def on_browse():
            sel = QtWidgets.QFileDialog.getExistingDirectory(
                self, "选择默认保存文件夹", self.save_dir or "")
            if sel:
                path_edit.setText(sel)

        browse_btn.clicked.connect(on_browse)
        path_row.addWidget(path_edit)
        path_row.addWidget(browse_btn)
        v.addLayout(path_row)

        v.addWidget(QtWidgets.QLabel("默认文件名:"))
        name_edit = QtWidgets.QLineEdit(self.default_filename or "")
        v.addWidget(name_edit)

        opts = QtWidgets.QHBoxLayout()
        chk_date = QtWidgets.QCheckBox("追加采集日期")
        chk_time = QtWidgets.QCheckBox("追加采集时间")
        chk_date.setChecked(self.append_date)
        chk_time.setChecked(self.append_time)
        opts.addWidget(chk_date)
        opts.addWidget(chk_time)
        opts.addStretch()
        v.addLayout(opts)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        new_dir = path_edit.text().strip()
        if new_dir:
            self.save_dir = new_dir
        new_name = name_edit.text().strip()
        if new_name:
            self.default_filename = new_name
        self.append_date = chk_date.isChecked()
        self.append_time = chk_time.isChecked()

    def _open_filter_dialog(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("阈值滤波设置")
        dlg.setMinimumWidth(380)
        v = QtWidgets.QVBoxLayout(dlg)

        chk = QtWidgets.QCheckBox("启用阈值滤波")
        chk.setChecked(self.pc.threshold_enabled)
        v.addWidget(chk)

        t_row = QtWidgets.QHBoxLayout()
        low_spin = QtWidgets.QDoubleSpinBox()
        low_spin.setRange(0.0, 1e9)
        low_spin.setDecimals(6)
        low_spin.setSingleStep(0.1)
        low_spin.setValue(self.pc.threshold_low)
        high_spin = QtWidgets.QDoubleSpinBox()
        high_spin.setRange(0.0, 1e9)
        high_spin.setDecimals(6)
        high_spin.setSingleStep(0.1)
        high_spin.setValue(self.pc.threshold_high)
        t_row.addWidget(QtWidgets.QLabel("下限:"))
        t_row.addWidget(low_spin)
        t_row.addWidget(QtWidgets.QLabel("上限:"))
        t_row.addWidget(high_spin)
        v.addLayout(t_row)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        self.pc.threshold_enabled = chk.isChecked()
        self.pc.threshold_low = float(low_spin.value())
        self.pc.threshold_high = float(high_spin.value())
        self.pc._last_render_len = -1  # force redraw
        self.filtered_plot.setVisible(self.pc.threshold_enabled)
        self._update_status_label()

    def _open_guide_dialog(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("使用指南 — 滤波与绘图说明")
        dlg.setMinimumSize(640, 420)
        v = QtWidgets.QVBoxLayout(dlg)
        text = QtWidgets.QTextEdit()
        text.setReadOnly(True)
        text.setHtml("""
        <h2>使用指南（快速操作）</h2>
        <p>本界面用于实时/回放查看 8 通道采集数据，并能对波形做简单的幅值阈值滤波、导出与管理。</p>
        <h3>采集控制</h3>
        <ul>
            <li>点击 <strong>▶ 开始</strong> 开始实时采集，点击 <strong>■ 结束</strong> 停止并保存。</li>
            <li>在记录列表点击 <em>查看</em> 可切换到回放模式。</li>
            <li>点击 <em>滤波设置</em> 可启用阈值滤波：保留满足 <code>low ≤ |x| ≤ high</code> 的样点。</li>
        </ul>
        <h3>波形图说明</h3>
        <ul>
            <li>为保证流畅，程序对 overview 做下采样显示（不改变原始数据）。</li>
            <li>鼠标左键拖动波形图可缩放区间；底部 overview 拖动黄色边框调整主图区间。</li>
            <li>左侧通道复选框控制显示；颜色按钮可修改曲线颜色。</li>
        </ul>
        <h3>导出与清理</h3>
        <ul>
            <li>导出时可选 <strong>导出原始</strong> 或 <strong>导出滤波结果</strong>（需先启用滤波）。</li>
            <li>"清除" 删除所有记录并释放内存，操作需确认。</li>
        </ul>
        """)
        v.addWidget(text)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
        btns.accepted.connect(dlg.accept)
        v.addWidget(btns)
        dlg.exec()
