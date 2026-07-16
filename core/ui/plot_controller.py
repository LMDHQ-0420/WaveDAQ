import time
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore

from core.acquisition.data_manager import DataManager
from core.signal.filters import threshold_filter

MAX_MAIN_PTS = 2000
MAX_OV_PTS   = 2000

INERTIA_FRICTION = 0.85   # velocity multiplier per tick (< 1 = decelerate)
INERTIA_INTERVAL = 16     # ms per inertia tick (~60 fps)
INERTIA_STOP_VEL = 0.5    # stop when |velocity| < this (in data units)


class PlotController:
    """Owns all rendering and view-sync logic. No QWidget inheritance."""

    def __init__(
        self,
        plot_widget: pg.PlotWidget,
        overview_plot: pg.PlotWidget,
        filtered_plot: pg.PlotWidget,
        region,
        curves: list,
        overview_curves: list,
        filtered_curves: list,
        checkboxes: list,
        data_manager: DataManager,
    ):
        self.plot_widget = plot_widget
        self.overview_plot = overview_plot
        self.filtered_plot = filtered_plot
        self.region = region
        self.curves = curves
        self.overview_curves = overview_curves
        self.filtered_curves = filtered_curves
        self.checkboxes = checkboxes
        self.data_manager = data_manager

        self.auto_pan_enabled = True
        self.is_overview_hovered = False
        self.current_view_index = -1

        self._suppress_sync = False
        self._cur_data_len = 0
        self._last_render_len = -1
        self._last_view_range = (0.0, 0.0)
        self._snapshots: list[np.ndarray] = []

        self.threshold_enabled = False
        self.threshold_low = 0.0
        self.threshold_high = 0.0

        # Solo channel plots (set by WavePlotter._rebuild_solo_plots)
        self.solo_plot_widgets: dict = {}   # ch_idx -> PlotWidget
        self.solo_curves: dict = {}         # ch_idx -> PlotCurveItem

        # Inertia state
        self._inertia_velocity = 0.0
        self._inertia_timer = QtCore.QTimer()
        self._inertia_timer.setInterval(INERTIA_INTERVAL)
        self._inertia_timer.timeout.connect(self._inertia_tick)
        self._drag_last_x: float | None = None
        self._drag_last_t: float | None = None
        self._drag_active = False

        self._install_pan_handler()

    # ------------------------------------------------------------------ #
    # Inertia pan                                                           #
    # ------------------------------------------------------------------ #

    def _install_pan_handler(self):
        """Hook into ViewBox mouse events on both plots to track drag velocity."""
        self._hook_viewbox(self.plot_widget.getViewBox())
        self._hook_viewbox(self.filtered_plot.getViewBox())

    def _hook_viewbox(self, vb):
        ctrl = self
        orig_press   = vb.mousePressEvent
        orig_release = vb.mouseReleaseEvent

        def on_press(ev):
            if ev.button() == QtCore.Qt.MouseButton.LeftButton:
                ctrl._inertia_timer.stop()
                ctrl._inertia_velocity = 0.0
                ctrl._drag_last_x = vb.mapSceneToView(ev.scenePos()).x()
                ctrl._drag_last_t = time.perf_counter()
                ctrl._drag_active = True
            orig_press(ev)

        def on_release(ev):
            if ev.button() == QtCore.Qt.MouseButton.LeftButton and ctrl._drag_active:
                ctrl._drag_active = False
                if abs(ctrl._inertia_velocity) > INERTIA_STOP_VEL:
                    ctrl._inertia_timer.start()
            orig_release(ev)

        vb.mousePressEvent = on_press
        vb.mouseReleaseEvent = on_release

    def _inertia_tick(self):
        """Called by inertia timer. Apply velocity then decelerate."""
        if abs(self._inertia_velocity) < INERTIA_STOP_VEL:
            self._inertia_timer.stop()
            return
        minX, maxX = self._last_view_range
        dt = INERTIA_INTERVAL / 1000.0
        delta = self._inertia_velocity * dt
        self._pan_to(minX + delta, maxX + delta)
        self._inertia_velocity *= INERTIA_FRICTION

    def _pan_to(self, minX: float, maxX: float):
        """Pan to [minX, maxX], clamped to data bounds."""
        total = float(self._cur_data_len)
        if total <= 0:
            return
        span = maxX - minX
        # clamp: keep span fixed, shift window
        if minX < 0:
            minX, maxX = 0.0, span
        if maxX > total:
            maxX, minX = total, total - span
        minX = max(0.0, minX)
        maxX = min(total, maxX)
        self._set_view(minX, maxX)

    # ------------------------------------------------------------------ #
    # Main timer update                                                     #
    # ------------------------------------------------------------------ #

    def update(self):
        dm = self.data_manager

        if self.current_view_index == -1:
            with dm.history_lock:
                cur_len = dm.flush_buf()
                if cur_len == 0:
                    self._clear_curves()
                    self._last_render_len = 0
                    return
                snapshots = [dm._live_buf[ch][:cur_len] for ch in range(8)]
        else:
            if self.current_view_index >= len(dm.collected_data):
                return
            rec_data = dm.collected_data[self.current_view_index]['data']
            cur_len = len(rec_data[0]) if rec_data else 0
            if cur_len == 0:
                self._clear_curves()
                return
            snapshots = rec_data

        self._snapshots = snapshots
        self._cur_data_len = cur_len

        if cur_len != self._last_render_len:
            self._last_render_len = cur_len
            self._redraw_overview(snapshots, cur_len)

            if self.auto_pan_enabled:
                self._set_view(0.0, float(cur_len))
                self._redraw_main(snapshots, 0.0, float(cur_len))

            if not self.is_overview_hovered:
                self.overview_plot.setXRange(0, cur_len, padding=0)

    # ------------------------------------------------------------------ #
    # Core view setter (single place that calls setXRange)                  #
    # ------------------------------------------------------------------ #

    def _set_view(self, minX: float, maxX: float):
        """Set x range on all plots and region, suppressing callbacks."""
        self._last_view_range = (minX, maxX)
        self._suppress_sync = True
        try:
            self.plot_widget.setXRange(minX, maxX, padding=0)
            self.filtered_plot.setXRange(minX, maxX, padding=0)
            self.region.setRegion([minX, maxX])
            for pw in self.solo_plot_widgets.values():
                pw.setXRange(minX, maxX, padding=0)
        finally:
            self._suppress_sync = False
        self._redraw_main(self._snapshots, minX, maxX)

    # ------------------------------------------------------------------ #
    # Redraw helpers                                                        #
    # ------------------------------------------------------------------ #

    def _redraw_main(self, snapshots: list, minX: float, maxX: float):
        if not snapshots or maxX <= minX:
            return
        n = len(snapshots[0])
        i0 = max(0, int(minX))
        i1 = min(n, int(maxX) + 1)
        window = i1 - i0
        if window <= 0:
            return
        rate = max(1, window // MAX_MAIN_PTS)
        xs = np.arange(i0, i1, rate)
        thr_on = self.threshold_enabled
        for ch in range(8):
            seg = snapshots[ch][i0:i1:rate]
            self.curves[ch].setData(xs, seg)
            if thr_on and self.checkboxes[ch].isChecked():
                self.filtered_curves[ch].setData(
                    xs, threshold_filter(seg, self.threshold_low, self.threshold_high))
            else:
                self.filtered_curves[ch].clear()

        for ch, curve in self.solo_curves.items():
            if self.checkboxes[ch].isChecked():
                seg = snapshots[ch][i0:i1:rate]
                curve.setData(xs, seg)
            else:
                curve.clear()

    def _redraw_overview(self, snapshots: list, cur_len: int):
        rate = max(1, cur_len // MAX_OV_PTS)
        x_ds = np.arange(0, cur_len, rate)
        for ch in range(8):
            self.overview_curves[ch].setData(x_ds, snapshots[ch][::rate])

    def _clear_curves(self):
        for ch in range(8):
            self.curves[ch].clear()
            self.overview_curves[ch].clear()
            self.filtered_curves[ch].clear()
        for curve in self.solo_curves.values():
            curve.clear()

    # ------------------------------------------------------------------ #
    # View change callbacks                                                 #
    # ------------------------------------------------------------------ #

    def on_region_changed(self):
        if self._suppress_sync:
            return
        minX, maxX = self.region.getRegion()
        total = self._cur_data_len
        if total > 0:
            minX = max(0.0, minX)
            maxX = min(float(total), maxX)
        self._set_view(minX, maxX)

    def on_main_plot_changed(self):
        if self._suppress_sync:
            return
        view_range = self.plot_widget.getViewBox().viewRange()
        minX, maxX = view_range[0]
        total = self._cur_data_len

        # Track drag velocity for inertia
        if self._drag_active:
            cur_t = time.perf_counter()
            cur_mid = (minX + maxX) / 2.0
            if self._drag_last_x is not None and self._drag_last_t is not None:
                dt = cur_t - self._drag_last_t
                if dt > 0:
                    self._inertia_velocity = (self._drag_last_x - cur_mid) / dt
            self._drag_last_x = cur_mid
            self._drag_last_t = cur_t

        if total > 0:
            span = maxX - minX
            minX = max(0.0, minX)
            maxX = min(float(total), maxX)
            if maxX - minX < span * 0.99:
                if minX == 0.0:
                    maxX = min(float(total), span)
                else:
                    minX = max(0.0, float(total) - span)
        self._set_view(minX, maxX)

    def on_filtered_plot_changed(self):
        if self._suppress_sync:
            return
        try:
            minX, maxX = self.filtered_plot.getViewBox().viewRange()[0]
        except Exception:
            return

        # Track drag velocity for inertia (same logic as on_main_plot_changed)
        if self._drag_active:
            cur_t = time.perf_counter()
            cur_mid = (minX + maxX) / 2.0
            if self._drag_last_x is not None and self._drag_last_t is not None:
                dt = cur_t - self._drag_last_t
                if dt > 0:
                    self._inertia_velocity = (self._drag_last_x - cur_mid) / dt
            self._drag_last_x = cur_mid
            self._drag_last_t = cur_t

        total = self._cur_data_len
        if total > 0:
            span = maxX - minX
            minX = max(0.0, minX)
            maxX = min(float(total), maxX)
            if maxX - minX < span * 0.99:
                if minX == 0.0:
                    maxX = min(float(total), span)
                else:
                    minX = max(0.0, float(total) - span)
        self._set_view(minX, maxX)

    def on_solo_plot_changed(self, pw=None, _range=None):
        if self._suppress_sync:
            return
        # find the first solo plot that has a valid view range
        try:
            if pw is not None and hasattr(pw, 'getViewBox'):
                minX, maxX = pw.getViewBox().viewRange()[0]
            else:
                for p in self.solo_plot_widgets.values():
                    minX, maxX = p.getViewBox().viewRange()[0]
                    break
                else:
                    return
        except Exception:
            return

        if self._drag_active:
            cur_t = time.perf_counter()
            cur_mid = (minX + maxX) / 2.0
            if self._drag_last_x is not None and self._drag_last_t is not None:
                dt = cur_t - self._drag_last_t
                if dt > 0:
                    self._inertia_velocity = (self._drag_last_x - cur_mid) / dt
            self._drag_last_x = cur_mid
            self._drag_last_t = cur_t

        total = self._cur_data_len
        if total > 0:
            span = maxX - minX
            minX = max(0.0, minX)
            maxX = min(float(total), maxX)
            if maxX - minX < span * 0.99:
                if minX == 0.0:
                    maxX = min(float(total), span)
                else:
                    minX = max(0.0, float(total) - span)
        self._set_view(minX, maxX)
        if (minX, maxX) == self._last_view_range:
            return
        self._set_view(minX, maxX)

    # ------------------------------------------------------------------ #
    # Controls                                                              #
    # ------------------------------------------------------------------ #

    def reset_zoom(self):
        self.auto_pan_enabled = True
        self._inertia_timer.stop()
        self._inertia_velocity = 0.0
        self._last_render_len = -1
        self.update()

    def switch_view(self, index: int):
        self.current_view_index = index
        self.auto_pan_enabled = True
        self._inertia_timer.stop()
        self._inertia_velocity = 0.0
        self._last_render_len = -1
        self._snapshots = []
        self.update()

    def on_manual_pan_zoom(self, _=None):
        self.auto_pan_enabled = False

    def on_overview_enter(self, event):
        self.is_overview_hovered = True

    def on_overview_leave(self, event):
        self.is_overview_hovered = False
