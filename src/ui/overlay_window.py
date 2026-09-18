from typing import List, Optional, Tuple
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget
from src.config import SETTINGS_TOPMOST_HOTKEY
from src.core.shortcut import GlobalHotkey


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
            | Qt.WindowTransparentForInput
        )

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # Style variables - Google Lens dark pill styling
        self.font_family = "Arial"
        self.font_size = 18
        self.font_color = "#FFFFFF"
        self.bg_color = "#1F1F1F"
        self.bg_opacity = 240
        self._is_scanning = False

        # Active translated pills: list of (QRect, translated_text)
        self.pills: List[Tuple[QRect, str]] = []
        self.target_rect: Optional[QRect] = None

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

    def set_target_rect(self, rect: Optional[QRect]):
        """Sets the active screen area geometry for the overlay canvas."""
        if rect and rect.width() > 10 and rect.height() > 10:
            self.target_rect = QRect(rect)
            self.setGeometry(rect)

    def set_pills(self, pills: List[Tuple[QRect, str]]):
        """
        Updates the active Google Lens translation pills and re-renders them in-place.
        Tolerates empty list to clear the overlay.
        """
        self.pills = [(QRect(r), str(txt)) for r, txt in pills if txt and txt.strip()]
        self.update()
        if self.pills:
            self.show()
            self.raise_()
        else:
            self.hide()

    def update_lens_translation(self, text: str, rect: Optional[QRect] = None):
        """Single-block translation helper for backward compatibility."""
        clean = (text or "").strip()
        if not clean:
            self.set_pills([])
            return

        box = rect or self.target_rect or self.geometry()
        self.set_pills([(box, clean)])

    @Slot(str)
    def update_text(self, text: str):
        self.update_lens_translation(text, self.target_rect)

    def paintEvent(self, event):
        if not self.pills:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        r = int(self.bg_color[1:3], 16)
        g = int(self.bg_color[3:5], 16)
        b = int(self.bg_color[5:7], 16)
        brush = QColor(r, g, b, self.bg_opacity)
        border_pen = QPen(QColor(255, 255, 255, 40), 1)
        text_color = QColor(self.font_color)
        font = QFont(self.font_family, self.font_size, QFont.Bold)
        painter.setFont(font)

        # Coordinate offset if overlay is positioned at a specific sub-rect
        offset_x = self.x()
        offset_y = self.y()

        for rect, text in self.pills:
            if not text:
                continue

            # Convert global screen coords to local widget coords
            local_x = rect.x() - offset_x
            local_y = rect.y() - offset_y
            local_rect = QRect(local_x, local_y, rect.width(), rect.height())

            # Background pill covering the original foreign text completely
            pill_rect = local_rect.adjusted(-8, -4, 8, 4)
            painter.setBrush(brush)
            painter.setPen(border_pen)
            painter.drawRoundedRect(pill_rect, 8, 8)

            # Translated text on top
            painter.setPen(text_color)
            painter.drawText(local_rect, Qt.AlignCenter | Qt.TextWordWrap, text)

    @Slot(str)
    def set_font_family(self, family):
        self.font_family = family
        self.update()

    @Slot(int)
    def set_font_size(self, size):
        self.font_size = size
        self.update()

    @Slot(str)
    def set_font_color(self, color):
        self.font_color = color
        self.update()

    @Slot(str)
    def set_bg_color(self, color):
        self.bg_color = color
        self.update()

    @Slot(int)
    def set_bg_opacity(self, opacity):
        self.bg_opacity = opacity
        self.update()

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
        if not scan:
            self.set_pills([])
            self.hide()
