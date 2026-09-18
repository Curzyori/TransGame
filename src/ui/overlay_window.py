from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from src.config import SETTINGS_TOPMOST_HOTKEY
from src.core.shortcut import GlobalHotkey
from src.i18n import _

class CornerLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.corner_line_length = 24
        self.corner_line_thickness = 2
        self._show_corner_lines = False

    def set_corner_lines_visible(self, visible):
        if self._show_corner_lines == visible:
            return
        self._show_corner_lines = visible
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._show_corner_lines:
            return

        parent = self.parent()
        color = QColor(parent.font_color if parent is not None else "white")
        if not color.isValid():
            color = QColor("white")

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(color, self.corner_line_thickness, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

        offset = self.corner_line_thickness / 2
        left = offset
        top = offset
        right = self.width() - 1 - offset
        bottom = self.height() - 1 - offset
        length = self.corner_line_length
        radius = min(8, length / 3)

        paths = []

        top_left = QPainterPath()
        top_left.moveTo(left + length, top)
        top_left.lineTo(left + radius, top)
        top_left.quadTo(left, top, left, top + radius)
        top_left.lineTo(left, top + length)
        paths.append(top_left)

        top_right = QPainterPath()
        top_right.moveTo(right - length, top)
        top_right.lineTo(right - radius, top)
        top_right.quadTo(right, top, right, top + radius)
        top_right.lineTo(right, top + length)
        paths.append(top_right)

        bottom_left = QPainterPath()
        bottom_left.moveTo(left, bottom - length)
        bottom_left.lineTo(left, bottom - radius)
        bottom_left.quadTo(left, bottom, left + radius, bottom)
        bottom_left.lineTo(left + length, bottom)
        paths.append(bottom_left)

        bottom_right = QPainterPath()
        bottom_right.moveTo(right - length, bottom)
        bottom_right.lineTo(right - radius, bottom)
        bottom_right.quadTo(right, bottom, right, bottom - radius)
        bottom_right.lineTo(right, bottom - length)
        paths.append(bottom_right)

        for path in paths:
            painter.drawPath(path)


class TransparentOverlay(QWidget):
    main_window_topmost_requested = Signal(bool)
    settings_topmost_hotkey_pressed = Signal()

    def __init__(self, title="USTA_TRANSLATION_OVERLAY", enable_hotkey=True):
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint
            | Qt.FramelessWindowHint
            | Qt.WindowDoesNotAcceptFocus
            | Qt.Tool
            | Qt.X11BypassWindowManagerHint
        )

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.resize(600, 100)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # Style variables - Google Lens default styling
        self.font_family = "Arial"
        self.font_size = 19
        self.font_color = "#FFFFFF"
        self.bg_color = "#1F1F1F"
        self.bg_opacity = 235
        self._is_scanning = False

        self.label = QLabel(self)
        self.label.setText("")
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignCenter)
        self.update_style()
        self.layout.addWidget(self.label)

        self._main_window_topmost_requested = False
        self._settings_topmost_hotkey_armed = True
        self.settings_topmost_hotkey = SETTINGS_TOPMOST_HOTKEY
        self._settings_topmost_hotkey = None
        if enable_hotkey:
            self._settings_topmost_hotkey = GlobalHotkey(
                self.settings_topmost_hotkey,
                self._emit_settings_topmost_hotkey_pressed,
            )
            self.settings_topmost_hotkey_pressed.connect(
                self._handle_settings_topmost_hotkey_pressed
            )
            self._settings_topmost_hotkey.start()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.raise_)
        self.timer.start(2000)

    def _emit_settings_topmost_hotkey_pressed(self):
        self.settings_topmost_hotkey_pressed.emit()

    @Slot()
    def _handle_settings_topmost_hotkey_pressed(self):
        if not self._settings_topmost_hotkey_armed:
            return

        self._settings_topmost_hotkey_armed = False
        self._toggle_main_window_topmost()
        QTimer.singleShot(200, self._rearm_settings_topmost_hotkey)

    def _rearm_settings_topmost_hotkey(self):
        self._settings_topmost_hotkey_armed = True

    def update_style(self):
        r = int(self.bg_color[1:3], 16)
        g = int(self.bg_color[3:5], 16)
        b = int(self.bg_color[5:7], 16)
        has_text = bool(self.label.text().strip())
        current_opacity = self.bg_opacity if has_text else 0
        style = (
            f"color: {self.font_color}; "
            f"font-family: '{self.font_family}'; "
            f"font-size: {self.font_size}px; "
            f"font-weight: bold; "
            f"background: rgba({r},{g},{b},{current_opacity}); "
            f"border: 1px solid rgba(255,255,255,{30 if has_text else 0}); "
            f"border-radius: 8px; padding: 6px 12px;"
        )
        self.label.setStyleSheet(style)
        self.label.update()

    def set_target_rect(self, rect):
        """Aligns the overlay window geometry directly over the detected dialogue box."""
        if rect and rect.width() > 10 and rect.height() > 10:
            self.setGeometry(rect.adjusted(-6, -4, 6, 4))
            self.update_style()

    @Slot(str)
    def set_font_family(self, family):
        self.font_family = family
        self.update_style()

    @Slot(int)
    def set_font_size(self, size):
        self.font_size = size
        self.update_style()

    @Slot(str)
    def set_font_color(self, color):
        self.font_color = color
        self.update_style()

    @Slot(str)
    def set_bg_color(self, color):
        self.bg_color = color
        self.update_style()

    @Slot(int)
    def set_bg_opacity(self, opacity):
        self.bg_opacity = opacity
        self.update_style()

    @Slot(str)
    def update_text(self, text: str):
        clean = (text or "").strip()
        self.label.setText(clean)
        self.update_style()
        if clean:
            self.show()
            self.raise_()
        else:
            self.hide()

    def update_lens_translation(self, text: str, rect=None):
        """Updates text and optionally repositions the overlay directly on top of the text."""
        if rect:
            self.set_target_rect(rect)
        self.update_text(text)

    def _toggle_main_window_topmost(self):
        self._main_window_topmost_requested = not self._main_window_topmost_requested
        self.main_window_topmost_requested.emit(self._main_window_topmost_requested)

    def set_settings_topmost_hotkey(self, hotkey):
        if not self._settings_topmost_hotkey:
            return False
        if hotkey == self.settings_topmost_hotkey:
            return True

        candidate = GlobalHotkey(hotkey, self._emit_settings_topmost_hotkey_pressed)
        if not candidate.start():
            return False

        self._settings_topmost_hotkey.stop()
        self._settings_topmost_hotkey = candidate
        self.settings_topmost_hotkey = hotkey
        return True

    def closeEvent(self, event):
        if self._settings_topmost_hotkey:
            self._settings_topmost_hotkey.stop()
        super().closeEvent(event)

    def set_mode(self, scan):
        self._is_scanning = scan
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        if scan:
            self.label.setText("")
            self.update_style()
        else:
            self.label.setText("")
            self.update_style()
            self.hide()
