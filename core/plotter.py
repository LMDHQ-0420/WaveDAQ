import os
import csv
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
from datetime import datetime
import gc

from . import state
from .widgets import CustomLinearRegionItem, DataControlPanel, DetailsDialog, ExportDialog


class WavePlotter(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("8通道数据采集操作台")
        self.resize(1200, 800)

        self.auto_pan_enabled = True
        self.is_overview_hovered = False
        self.current_view_index = -1
        self.collection_start_time = None
        self.recollect_target_index = None # 用于标记重采的目标索引

        main_layout = QtWidgets.QHBoxLayout(self)

        # --- 左侧面板 ---
        # 注意：不使用顶部 header 布局，按钮放到左侧最底部
        left_panel_layout = QtWidgets.QVBoxLayout()

        # 开始/结束按钮
        collect_btn_layout = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton("▶ 开始")
        self.stop_button = QtWidgets.QPushButton("■ 结束")
        
        # 定义按钮样式，包括禁用状态
        start_style = """
            QPushButton { background-color: #28a745; color: white; border: none; padding: 5px; border-radius: 3px; }
            QPushButton:disabled { background-color: #6c757d; }
        """
        stop_style = """
            QPushButton { background-color: #dc3545; color: white; border: none; padding: 5px; border-radius: 3px; }
            QPushButton:disabled { background-color: #6c757d; }
        """
        self.start_button.setStyleSheet(start_style)
        self.stop_button.setStyleSheet(stop_style)

        self.start_button.clicked.connect(self.start_collection)
        self.stop_button.clicked.connect(self.stop_collection)
        self.stop_button.setEnabled(False)
        collect_btn_layout.addWidget(self.start_button)
        collect_btn_layout.addWidget(self.stop_button)
        left_panel_layout.addLayout(collect_btn_layout)

        # 滚动窗口
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: 1px solid black; }")
        scroll_area.setMinimumWidth(200) # 加宽左侧列表
        # 禁用横向滚动条，隐藏纵向滚动条
        scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_content_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout(self.scroll_content_widget)
        self.scroll_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop) # 使内容从顶部开始排列
        scroll_area.setWidget(self.scroll_content_widget)
        left_panel_layout.addWidget(scroll_area, 1)

        # 颜色选择器 (改为2列网格布局)
        # （已搬到 header）

        # 全局默认保存目录与默认文件名
        self.save_dir = None
        self.default_filename = None

        # 全局开关：保存时是否追加日期/时间
        self.append_date = False
        self.append_time = False

        # 阈值滤波参数（两个参数为振幅大小，必须为正数）
        self.threshold_enabled = False
        self.threshold_low = 0.0
        self.threshold_high = 0.0
        # （不再使用）同步保存滤波结果选项已移除

        channel_grid_layout = QtWidgets.QGridLayout()
        self.color_buttons = []
        self.checkboxes = []
        self.default_colors = ['#FF7F50', '#8A2BE2', '#00CED1', '#FFD700', '#FF69B4', '#00FF7F', '#1E90FF', '#FF8C00']
        for i in range(8):
            row_layout = QtWidgets.QHBoxLayout()
            btn = QtWidgets.QPushButton("")
            btn.setFixedSize(24, 24)
            btn.setStyleSheet(f"background-color:{pg.mkColor(self.default_colors[i]).name()}; border:1px solid gray;")
            btn.clicked.connect(lambda checked, idx=i: self.change_curve_color(idx))
            row_layout.addWidget(btn)
            self.color_buttons.append(btn)
            cb = QtWidgets.QCheckBox(f'通道{i+1}')
            cb.setChecked(True)
            cb.stateChanged.connect(self.update_visibility)
            row_layout.addWidget(cb)
            self.checkboxes.append(cb)
            
            # 添加到网格中
            grid_row = i // 2
            grid_col = i % 2
            channel_grid_layout.addLayout(row_layout, grid_row, grid_col)
        
        left_panel_layout.addLayout(channel_grid_layout)
        # 保持左侧面板大小与通道选择面板不变，按钮固定在底部
        buttons_bottom_layout = QtWidgets.QHBoxLayout()
        self.defaults_btn = QtWidgets.QPushButton("默认设置")
        self.defaults_btn.clicked.connect(self.open_defaults_dialog)
        self.filter_btn = QtWidgets.QPushButton("滤波设置")
        self.filter_btn.clicked.connect(self.open_filter_dialog)
        buttons_bottom_layout.addWidget(self.defaults_btn)
        buttons_bottom_layout.addWidget(self.filter_btn)
        left_panel_layout.addLayout(buttons_bottom_layout)
        main_layout.addLayout(left_panel_layout, stretch=0)

        # --- 右侧绘图区 ---
        plot_layout = QtWidgets.QVBoxLayout()
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMouseEnabled(x=True, y=False)
        self.plot_widget.hideButtons()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3) # 添加网格
        # 主图与（可选的）阈值滤波图在同时显示时需要相同高度：两者使用相同的 stretch
        plot_layout.addWidget(self.plot_widget, stretch=1)
        # 新增：阈值滤波后波形显示（仅在启用阈值滤波时可见），放在主波形下方、overview 上方
        self.filtered_plot = pg.PlotWidget()
        self.filtered_plot.setMouseEnabled(x=True, y=False)
        self.filtered_plot.hideButtons()
        self.filtered_plot.showGrid(x=True, y=True, alpha=0.3)
        # 默认根据是否启用阈值滤波决定可见性
        self.filtered_plot.setVisible(self.threshold_enabled)
        plot_layout.addWidget(self.filtered_plot, stretch=1)
        overview_layout = QtWidgets.QHBoxLayout()
        self.overview_plot = pg.PlotWidget()
        self.overview_plot.setFixedHeight(80) 
        self.overview_plot.setMouseEnabled(x=False, y=False)
        self.overview_plot.hideAxis('left')
        self.overview_plot.hideButtons()
        self.overview_plot.enterEvent = self.on_overview_enter
        self.overview_plot.leaveEvent = self.on_overview_leave
        overview_layout.addWidget(self.overview_plot)
        controls_layout = QtWidgets.QVBoxLayout()
        self.reset_button = QtWidgets.QPushButton("复位")
        self.reset_button.setFixedWidth(50)
        self.reset_button.clicked.connect(self.reset_zoom)
        controls_layout.addWidget(self.reset_button)
        self.bg_color_button = QtWidgets.QPushButton("背景")
        self.bg_color_button.setFixedWidth(50)
        self.bg_color_button.clicked.connect(self.change_background_color)
        controls_layout.addWidget(self.bg_color_button)
        # 新增：清除所有已采集数据（危险操作，带确认）
        self.clear_all_button = QtWidgets.QPushButton("清除")
        self.clear_all_button.setFixedWidth(50)
        # 红色样式
        self.clear_all_button.setStyleSheet("QPushButton { background-color: #dc3545; color: white; border: none; padding: 3px; border-radius: 5px; }")
        self.clear_all_button.clicked.connect(self.clear_all_data)
        controls_layout.addWidget(self.clear_all_button)

        # 新增：使用指南按钮（显示滤波原理、降采样说明与缩放/平移用法）
        self.guide_button = QtWidgets.QPushButton("指南")
        self.guide_button.setFixedWidth(50)
        self.guide_button.clicked.connect(self.open_guide_dialog)
        controls_layout.addWidget(self.guide_button)
        overview_layout.addLayout(controls_layout)
        plot_layout.addLayout(overview_layout, stretch=1)
        
        # 状态显示标签
        self.status_label = QtWidgets.QLabel("无采集数据。")
        plot_layout.addWidget(self.status_label)
        
        main_layout.addLayout(plot_layout, stretch=1)

        # --- 曲线和滑轨初始化 ---
        self.curves = []
        self.overview_curves = []
        self.filtered_curves = []
        for i in range(8):
            curve = self.plot_widget.plot(pen=pg.mkPen(color=self.default_colors[i], width=1), name=f'通道{i+1}')
            self.curves.append(curve)
            overview_curve = self.overview_plot.plot(pen=pg.mkPen(color=self.default_colors[i], width=0.8))
            self.overview_curves.append(overview_curve)
            fcurve = self.filtered_plot.plot(pen=pg.mkPen(color=self.default_colors[i], width=1, style=QtCore.Qt.PenStyle.DashLine))
            self.filtered_curves.append(fcurve)
        self.region = CustomLinearRegionItem()
        self.normal_pen = pg.mkPen(color='#FFD700', width=3)
        self.hover_pen = pg.mkPen(color='w', width=4)
        self.active_pen = pg.mkPen(color='w', width=4)
        self.region.lines[0].setPen(self.normal_pen)
        self.region.lines[0].setHoverPen(self.hover_pen)
        self.region.lines[1].setPen(self.normal_pen)
        self.region.lines[1].setHoverPen(self.hover_pen)
        self.region.setZValue(10)
        self.overview_plot.addItem(self.region, ignoreBounds=True)

        # --- 信号连接 ---
        self.region.sigDragStarted.connect(self.on_region_drag_start)
        self.region.sigDragFinished.connect(self.on_region_drag_finish)
        self.region.sigRegionChanged.connect(self.on_region_changed)
        self.plot_widget.getViewBox().sigRangeChangedManually.connect(self.on_manual_pan_zoom)
        self.plot_widget.sigXRangeChanged.connect(self.on_main_plot_changed)
        self.plot_widget.scene().sigMouseClicked.connect(self.on_plot_double_clicked)

        # 定时器
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.timer.start(33)
        # 用于避免范围同步时的递归/回环
        self._suppress_sync = False
        # 当在过滤图上手动缩放/平移时，同步到主图
        try:
            self.filtered_plot.getViewBox().sigRangeChangedManually.connect(self.on_filtered_plot_changed)
        except Exception:
            # 某些 pyqtgraph 版本可能没有该信号；同时连接 sigXRangeChanged 作为后备
            self.filtered_plot.sigXRangeChanged.connect(self.on_filtered_plot_changed)

    def update_status_label(self):
        """更新底部状态栏的文本"""
        if state.is_collecting:
            if self.recollect_target_index is not None:
                status_text = f"正在重采数据{self.recollect_target_index + 1}..."
            else:
                status_text = f"正在采集数据{len(state.collected_data) + 1}..."
        else:
            if self.current_view_index == -1:
                status_text = "无采集数据。"
            else:
                status_text = f"正在查看数据{self.current_view_index + 1}。"
        # 在状态文本后追加滤波启用状态与参数（更清晰的格式）
        try:
            if getattr(self, 'threshold_enabled', False):
                low = float(getattr(self, 'threshold_low', 0.0))
                high = float(getattr(self, 'threshold_high', 0.0))
                status_text = f"{status_text}  |  滤波: 已启用 (幅值 {low:.2f} ~ {high:.2f})"
            else:
                status_text = f"{status_text}  |  滤波: 已禁用"
        except Exception:
            pass

        self.status_label.setText(status_text)

    def start_collection(self):
        if len(state.collected_data) >= state.MAX_COLLECTIONS and self.recollect_target_index is None:
            QtWidgets.QMessageBox.warning(self, "提示", f"最多只能采集 {state.MAX_COLLECTIONS} 个数据。")
            return

        with state.history_lock:
            state.live_history = [np.array([], dtype=np.float32) for _ in range(8)]
        
        self.collection_start_time = datetime.now() # 记录开始时间
        state.is_collecting = True
        self.current_view_index = -1 # 切换到实时视图
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.reset_zoom() # 开始采集时自动跟随
        self.update_status_label()

    def stop_collection(self):
        if not state.is_collecting:
            return
        
        collection_end_time = datetime.now()
        state.is_collecting = False
        with state.history_lock:
            saved_history = [arr.copy() for arr in state.live_history]
        
        # 判断是重采还是新采集
        if self.recollect_target_index is not None:
            # --- 重采逻辑 ---
            index_to_overwrite = self.recollect_target_index
            state.collected_data[index_to_overwrite]['data'] = saved_history
            state.collected_data[index_to_overwrite]['start_time'] = self.collection_start_time
            state.collected_data[index_to_overwrite]['end_time'] = collection_end_time
            # 更新名称为采集开始时间
            new_name = self.collection_start_time.strftime('%H:%M:%S')
            state.collected_data[index_to_overwrite]['name'] = new_name

            # 关键修复：将当前视图指向刚刚重采的数据
            self.current_view_index = index_to_overwrite

            # 如果左侧存在对应的控制面板，更新其显示名称和时间
            try:
                for i in range(self.scroll_layout.count()):
                    w = self.scroll_layout.itemAt(i).widget()
                    if w and getattr(w, 'index', None) == index_to_overwrite:
                        # 重采只更新右侧时间，不改变左侧的“数据N”标签
                        if hasattr(w, 'time_label'):
                            w.time_label.setText(self.collection_start_time.strftime('%H:%M:%S'))
                        break
            except Exception:
                pass
            
            # 重置重采标记
            self.recollect_target_index = None
        else:
            # --- 新采集逻辑 ---
            new_index = len(state.collected_data)
            # 使用采集开始时间作为记录的时间字段，但左侧显示采用“数据N”格式
            time_name = self.collection_start_time.strftime('%H:%M:%S')
            display_name = f"数据{new_index+1}"
            state.collected_data.append({
                'name': display_name,
                'data': saved_history,
                'start_time': self.collection_start_time,
                'end_time': collection_end_time,
                'time_str': time_name
            })
            # 左侧 name 显示为 数据N，右侧时间显示为采集开始时间
            self.add_data_control_panel(display_name, new_index, self.collection_start_time)
            
            # 关键修复：将当前视图指向刚刚采集的新数据
            self.current_view_index = new_index

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.update_status_label()

    def add_data_control_panel(self, name, index, start_time):
        panel = DataControlPanel(name, index, start_time, self.view_data, self.show_details, self.export_record)
        self.scroll_layout.insertWidget(0, panel)

    def export_record(self, index):
        """在每条记录处触发的导出，对话框允许选择通道并保存。"""
        if index < 0 or index >= len(state.collected_data):
            QtWidgets.QMessageBox.warning(self, "提示", "无效的记录索引。")
            return
        record = state.collected_data[index]
        dlg = ExportDialog(record, self)
        # 传递默认保存设置
        if self.save_dir:
            dlg.default_dir = self.save_dir
        if self.default_filename:
            dlg.default_filename = self.default_filename
        dlg.append_date = self.append_date
        dlg.append_time = self.append_time
        # 传递阈值参数供导出对话框使用（导出滤波结果由导出对话框的按钮控制）
        dlg.threshold_enabled = getattr(self, 'threshold_enabled', False)
        dlg.threshold_low = getattr(self, 'threshold_low', 0.0)
        dlg.threshold_high = getattr(self, 'threshold_high', 0.0)
        # 根据阈值启用状态设置导出对话框的按钮可用性（如果对话框有该按钮）
        try:
            if hasattr(dlg, 'btn_export_filtered'):
                dlg.btn_export_filtered.setEnabled(dlg.threshold_enabled)
        except Exception:
            pass
        dlg.exec()

    def view_data(self, index):
        if state.is_collecting:
            QtWidgets.QMessageBox.warning(self, "操作提示", "请先结束当前的采集任务。")
            return
        
        self.current_view_index = index
        self.auto_pan_enabled = True
        self.update_plot()
        self.update_status_label()

    def show_details(self, index):
        """显示详细信息弹窗"""
        if index < len(state.collected_data):
            # 传入 data_record, record_index, parent
            dialog = DetailsDialog(state.collected_data[index], index, self)
            # 传递全局默认目录和默认文件名（如果有）
            if self.save_dir:
                dialog.default_dir = self.save_dir
            if self.default_filename:
                dialog.default_filename = self.default_filename
            # 传递是否在保存时追加日期/时间的标志
            dialog.append_date = self.append_date
            dialog.append_time = self.append_time
            dialog.exec()

    def set_default_save_dir(self):
        """设置全局默认保存目录"""
        dir_path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择默认保存文件夹", "")
        if dir_path:
            self.save_dir = dir_path
            # 在 header 按钮上显示当前设置作为 tooltip，便于确认
            if hasattr(self, 'defaults_btn'):
                self.defaults_btn.setToolTip(f"默认保存目录: {dir_path}")

    def set_default_filename(self):
        """设置全局默认导出文件名（模板）"""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("设置默认文件名")
        layout = QtWidgets.QVBoxLayout(dlg)
        layout.addWidget(QtWidgets.QLabel("请输入默认文件名："))
        line = QtWidgets.QLineEdit()
        if self.default_filename:
            line.setText(self.default_filename)
        layout.addWidget(line)

        cb_layout = QtWidgets.QHBoxLayout()
        chk_date = QtWidgets.QCheckBox("追加采集日期")
        chk_time = QtWidgets.QCheckBox("追加采集时间")
        chk_date.setChecked(self.append_date)
        chk_time.setChecked(self.append_time)
        cb_layout.addWidget(chk_date)
        cb_layout.addWidget(chk_time)
        layout.addLayout(cb_layout)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        text = line.text().strip()
        if not text:
            return

        # 保存基础文件名（用户输入的完整文件名或带扩展名）
        self.default_filename = text
        # 保存复选框状态到全局标志
        self.append_date = chk_date.isChecked()
        self.append_time = chk_time.isChecked()

        if hasattr(self, 'defaults_btn'):
            self.defaults_btn.setToolTip(f"默认文件名: {self.default_filename} \n追加日期: {self.append_date} 追加时间: {self.append_time}")

    def open_defaults_dialog(self):
        """合并的默认设置对话框：上半部分为默认路径选择，下半部分为默认文件名与追加选项。

        该对话框仅修改 UI，最终效果与原先的两个方法一致（不会改变其他逻辑）。
        """
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("默认设置")
        dlg.setMinimumWidth(420)
        vlayout = QtWidgets.QVBoxLayout(dlg)

        # --- 上半：默认路径 ---
        vlayout.addWidget(QtWidgets.QLabel("默认保存路径:"))
        path_layout = QtWidgets.QHBoxLayout()
        path_edit = QtWidgets.QLineEdit()
        if self.save_dir:
            path_edit.setText(self.save_dir)
        browse_btn = QtWidgets.QPushButton("浏览")

        def on_browse():
            selected = QtWidgets.QFileDialog.getExistingDirectory(self, "选择默认保存文件夹", self.save_dir or "")
            if selected:
                path_edit.setText(selected)

        browse_btn.clicked.connect(on_browse)
        path_layout.addWidget(path_edit)
        path_layout.addWidget(browse_btn)
        vlayout.addLayout(path_layout)

        # --- 下半：默认文件名与选项 ---
        vlayout.addWidget(QtWidgets.QLabel("默认文件名:"))
        name_edit = QtWidgets.QLineEdit()
        if self.default_filename:
            name_edit.setText(self.default_filename)
        vlayout.addWidget(name_edit)

        opts_layout = QtWidgets.QHBoxLayout()
        chk_date = QtWidgets.QCheckBox("追加采集日期")
        chk_time = QtWidgets.QCheckBox("追加采集时间")
        chk_date.setChecked(self.append_date)
        chk_time.setChecked(self.append_time)
        opts_layout.addWidget(chk_date)
        opts_layout.addWidget(chk_time)
        opts_layout.addStretch()
        vlayout.addLayout(opts_layout)


        # buttons
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        vlayout.addWidget(buttons)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        # 将选择保存回主窗口状态（保持原逻辑变量名）
        new_dir = path_edit.text().strip()
        if new_dir:
            self.save_dir = new_dir
            if hasattr(self, 'defaults_btn'):
                self.defaults_btn.setToolTip(f"默认保存目录: {self.save_dir}")

        new_name = name_edit.text().strip()
        if new_name:
            self.default_filename = new_name
            if hasattr(self, 'defaults_btn'):
                self.defaults_btn.setToolTip(f"默认文件名: {self.default_filename} \n追加日期: {chk_date.isChecked()} 追加时间: {chk_time.isChecked()}")

        # 保存复选框状态
        self.append_date = chk_date.isChecked()
        self.append_time = chk_time.isChecked()

    def open_filter_dialog(self):
        """打开阈值滤波设置对话框：启用开关 + 下限/上限（浮点）。

        启用时：仅保留在 [low, high] 范围内的值，其他值置 0；并显示第二个滤波窗口。
        未启用时：隐藏第二窗口并不对数据做修改。
        """
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("阈值滤波设置")
        dlg.setMinimumWidth(380)
        v = QtWidgets.QVBoxLayout(dlg)

        # 启用开关
        chk = QtWidgets.QCheckBox("启用阈值滤波")
        chk.setChecked(self.threshold_enabled)
        v.addWidget(chk)

        # 阈值输入
        t_layout = QtWidgets.QHBoxLayout()
        low_label = QtWidgets.QLabel("下限:")
        low_spin = QtWidgets.QDoubleSpinBox()
        # 振幅必须为正数（含 0）
        low_spin.setRange(0.0, 1e9)
        low_spin.setDecimals(6)
        low_spin.setSingleStep(0.1)
        low_spin.setValue(float(self.threshold_low))
        t_layout.addWidget(low_label)
        t_layout.addWidget(low_spin)

        high_label = QtWidgets.QLabel("上限:")
        high_spin = QtWidgets.QDoubleSpinBox()
        # 振幅必须为正数（含 0）
        high_spin.setRange(0.0, 1e9)
        high_spin.setDecimals(6)
        high_spin.setSingleStep(0.1)
        high_spin.setValue(float(self.threshold_high))
        t_layout.addWidget(high_label)
        t_layout.addWidget(high_spin)

        v.addLayout(t_layout)

        # 按钮
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        v.addWidget(buttons)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        # 保存设置
        self.threshold_enabled = chk.isChecked()
        self.threshold_low = float(low_spin.value())
        self.threshold_high = float(high_spin.value())

        # 根据启用状态切换第二窗口可见性
        self.filtered_plot.setVisible(self.threshold_enabled)

        # 更新 defaults 按钮的 tooltip 以展示当前阈值状态（简短）
        if self.threshold_enabled and hasattr(self, 'defaults_btn'):
            self.defaults_btn.setToolTip(f"阈值: {self.threshold_low} .. {self.threshold_high}")
        elif hasattr(self, 'defaults_btn'):
            # 若未启用，移除阈值相关 tooltip（保留其他 tooltip 不变）
            self.defaults_btn.setToolTip("")

    def recollect_data(self, index, confirm=True):
        """实现重采功能

        参数:
        - index: 要重采的记录索引
        - confirm: 是否在此方法内部弹出确认对话框（DetailsDialog 已经会弹出一次）
        """
        if state.is_collecting:
            QtWidgets.QMessageBox.warning(self, "操作提示", "请先结束当前的采集任务。")
            return

        name = state.collected_data[index]['name']
        if confirm:
            reply = QtWidgets.QMessageBox.question(self, "确认操作", 
                                                   f"重新采集将覆盖 <b>{name}</b> 的现有数据，\n是否继续？",
                                                   QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                                                   QtWidgets.QMessageBox.StandardButton.No)
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return

        # 设置重采目标并开始采集
        self.recollect_target_index = index
        self.start_collection()

    def update_visibility(self):
        for i, cb in enumerate(self.checkboxes):
            self.curves[i].setVisible(cb.isChecked())
            self.overview_curves[i].setVisible(cb.isChecked())

    def update_plot(self):
        # 根据当前视图索引决定使用哪个数据源
        if self.current_view_index == -1:
            history_source = state.live_history
        else:
            if self.current_view_index < len(state.collected_data):
                history_source = state.collected_data[self.current_view_index]['data']
            else:
                return # 索引无效，不绘图

        with state.history_lock:
            cur_len = len(history_source[0]) if history_source and len(history_source) > 0 else 0
            if cur_len == 0: 
                # 清空画布
                for ch in range(8):
                    self.curves[ch].clear()
                    self.overview_curves[ch].clear()
                return

            downsample_rate = max(1, int(cur_len / 2000))

            # 为减少处理开销：仅对可见通道计算滤波，并对滤波结果使用下采样（与 overview 相同的采样率）
            xs_full = np.arange(cur_len)
            xs_ds = np.arange(0, cur_len, downsample_rate)
            thr_on = getattr(self, 'threshold_enabled', False)
            for ch in range(8):
                data_ch = history_source[ch]
                # 主图使用原始采样（保持用户期望精度）
                try:
                    self.curves[ch].setData(xs_full, data_ch)
                except Exception:
                    # 回退：逐点设置（极少见）
                    self.curves[ch].setData(xs_full, np.asarray(data_ch))

                # overview 使用下采样显示缩略
                self.overview_curves[ch].setData(xs_ds, data_ch[::downsample_rate])

                # 只有当阈值滤波开启并且该通道可见时，才计算并绘制过滤结果
                if thr_on and self.checkboxes[ch].isChecked():
                    # 对下采样后的数据进行阈值计算，显著降低计算量
                    try:
                        sampled = data_ch[::downsample_rate]
                        filtered_ds = self.apply_filters(sampled)
                        # 绘制下采样后的过滤结果（x 轴对应 xs_ds）
                        self.filtered_curves[ch].setData(xs_ds, filtered_ds)
                    except Exception:
                        # 在异常情况下清空该曲线，避免卡顿
                        self.filtered_curves[ch].clear()
                else:
                    # 未开启或不可见时确保过滤曲线不显示数据
                    self.filtered_curves[ch].clear()
            
            if not self.is_overview_hovered:
                self.overview_plot.setXRange(0, cur_len, padding=0)
            
            if self.auto_pan_enabled:
                self.region.setRegion([0, cur_len])

    def apply_filters(self, data_array):
        """对单通道数据应用阈值滤波：在 [low, high] 范围之外的值置 0。

        仅当 `self.threshold_enabled` 为 True 时生效，否则返回原始数据（不改变）。
        """
        x = np.asarray(data_array, dtype=np.float64)
        if x.size == 0:
            return x
        if not getattr(self, 'threshold_enabled', False):
            return x
        low = float(getattr(self, 'threshold_low', 0.0))
        high = float(getattr(self, 'threshold_high', 0.0))
        # 振幅阈值应为非负值；将阈值解释为幅值范围 [low, high]
        low = abs(low)
        high = abs(high)
        if low > high:
            low, high = high, low
        # 使用绝对值进行比较：只有当 |x| 在 [low, high] 范围内才保留，其他置 0
        mask = (np.abs(x) >= low) & (np.abs(x) <= high)
        return x * mask

    def on_region_changed(self):
        # 当正在内部同步时，阻止再次触发以避免回环
        if getattr(self, '_suppress_sync', False):
            return
        minX, maxX = self.region.getRegion()
        # 在设置其他视图范围期间避免触发它们的回调
        self._suppress_sync = True
        try:
            self.plot_widget.setXRange(minX, maxX, padding=0)
            # 同步过滤图
            self.filtered_plot.setXRange(minX, maxX, padding=0)
        finally:
            self._suppress_sync = False

    def on_main_plot_changed(self):
        if getattr(self, '_suppress_sync', False):
            return
        view_range = self.plot_widget.getViewBox().viewRange()
        # 直接设置 region；on_region_changed 会负责将范围同步到其它视图并处理抑制
        self.region.setRegion(view_range[0])
        # 主图手动变化时也同步过滤图（region 变化会触发 on_region_changed）

    def on_filtered_plot_changed(self):
        """当用户在过滤图上缩放/平移时，同步回主图和 region。"""
        if getattr(self, '_suppress_sync', False):
            return
        try:
            view_range = self.filtered_plot.getViewBox().viewRange()
            minX, maxX = view_range[0]
        except Exception:
            return
        # 执行同步时抑制回调，防止回环
        self._suppress_sync = True
        try:
            self.plot_widget.setXRange(minX, maxX, padding=0)
            self.region.setRegion([minX, maxX])
        finally:
            self._suppress_sync = False

    def on_plot_double_clicked(self, event):
        if event.double():
            self.reset_zoom()

    def reset_zoom(self):
        """将当前视图的自动平移标志设为True，以在下一次更新时重置缩放。"""
        self.auto_pan_enabled = True
        self.update_plot()
        self.update_status_label()

    def clear_all_data(self):
        """清除所有已采集的数据和相关 UI 项，恢复到程序刚启动的状态。

        操作会弹出确认对话框；确认后清空 `state.collected_data`、`state.live_history`，
        移除左侧所有记录面板，清空所有绘图曲线，并强制垃圾回收。
        """
        if state.is_collecting:
            QtWidgets.QMessageBox.warning(self, "操作禁止", "正在采集中，无法清除数据，请先结束采集。")
            return

        reply = QtWidgets.QMessageBox.question(self, "确认清除",
                                               "此操作将清除所有已采集的数据并无法恢复，是否继续？",
                                               QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                                               QtWidgets.QMessageBox.StandardButton.No)
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        # 清理后端数据结构
        with state.history_lock:
            try:
                state.collected_data.clear()
            except Exception:
                state.collected_data = []
            state.live_history = [np.array([], dtype=np.float32) for _ in range(8)]

        # 清除左侧滚动区域的所有记录面板
        try:
            while self.scroll_layout.count():
                item = self.scroll_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
        except Exception:
            pass

        # 清空绘图
        try:
            for c in self.curves + self.overview_curves + self.filtered_curves:
                try:
                    c.clear()
                except Exception:
                    pass
        except Exception:
            pass

        # 重置视图索引与状态显示
        self.current_view_index = -1
        gc.collect()
        self.update_plot()
        self.update_status_label()

    def open_guide_dialog(self):
        """打开详细使用指南对话框，包含滤波原理、降采样说明以及缩放/平移交互说明（面向有一定背景的用户）。"""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("使用指南 — 滤波与绘图说明")
        dlg.setMinimumSize(640, 420)
        layout = QtWidgets.QVBoxLayout(dlg)

        text = QtWidgets.QTextEdit()
        text.setReadOnly(True)
        # 面向用户的使用提示（更易读、直接的操作指南）
        html = """
        <h2>使用指南（快速操作）</h2>
        <p>本界面用于实时/回放查看 8 通道采集数据，并能对波形做简单的幅值阈值滤波、导出与管理。</p>

        <h3>采集控制</h3>
        <ul>
            <li>点击 <strong>▶ 开始</strong> 开始实时采集，点击 <strong>■ 结束</strong> 停止并保存当前采集为一条记录。</li>
            <li>在记录列表点击 <em>查看</em> 可切换到回放模式，查看已保存数据。</li>
            <li>点击 <em>滤波设置</em>可以启用阈值滤波：保留满足 <code>low ≤ |x| ≤ high</code> 的样点，范围外的样点被置为 0。启用时会显示“滤波后波形”窗口。<li>

        </ul>

        <h3>波形图说明</h3>
        <ul>
            <li>为保证界面流畅，程序会对原始数据进行下采样后显示（不改变原始数据）。</li>
            <li>使用鼠标左键滑动波形图/滤波图，可以放大（缩小）显示区域。</li>
            <li>底部 overview：拖动紫色区域或调整黄色边框可快速设置主图显示区间（主图与过滤图双向同步）。</li>
            <li>左侧的通道复选框控制通道显示；颜色按钮可修改对应曲线颜色，仅影响显示。</li>
        </ul>

        <h3>导出与清理</h3>
        <ul>
            <li>导出时可选择 <strong>导出原始</strong> 或 <strong>导出滤波结果</strong>（需先启用滤波）。</li>
            <li>原始数据和滤波结果的导出文件使用文件名加以区分。</li>
            <li>“清除”将删除所有已采集记录并释放内存，请在停止采集后谨慎使用（操作需确认）。</li>
            <li>“默认设置”可设置全局默认保存路径与文件名模板，方便后续导出使用。</li>
            <li>在导出或详情对话框中也可单独设置保存路径与文件名，优先级高于全局默认设置。</li>
        </ul>

        <h3>性能提示</h3>
        <ul>
            <li>采集时启用滤波会影响性能，建议<em>查看</em>时启用滤波，并定期<em>清除</em> 。</li>
            <li>若界面卡顿：减少同时显示的通道数、缩短查看时间窗口或暂时禁用阈值滤波。</li>
            <li>若界面卡顿严重：点击 <em>清除</em> 按钮可清除程序全部缓存并释放内存（注意，会删除全部数据！）。</li>
        </ul>
        """
        text.setHtml(html)
        layout.addWidget(text)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)

        dlg.exec()

    def on_manual_pan_zoom(self, _):
        self.auto_pan_enabled = False

    def on_overview_enter(self, event):
        self.is_overview_hovered = True

    def on_overview_leave(self, event):
        self.is_overview_hovered = False

    def on_region_drag_start(self):
        self.auto_pan_enabled = False
        self.region.lines[0].setPen(self.active_pen)
        self.region.lines[1].setPen(self.active_pen)

    def on_region_drag_finish(self):
        self.region.lines[0].setPen(self.normal_pen)
        self.region.lines[0].setHoverPen(self.hover_pen)
        self.region.lines[1].setPen(self.normal_pen)
        self.region.lines[1].setHoverPen(self.hover_pen)

    def change_curve_color(self, idx):
        color = QtWidgets.QColorDialog.getColor()
        if color.isValid():
            pen = pg.mkPen(color=color, width=1)
            self.curves[idx].setPen(pen)
            self.overview_curves[idx].setPen(pen)
            self.color_buttons[idx].setStyleSheet(f"background-color:{color.name()}; border:1px solid gray;")

    def change_background_color(self):
        color = QtWidgets.QColorDialog.getColor()
        if color.isValid():
            self.plot_widget.setBackground(color)
            self.overview_plot.setBackground(color)
