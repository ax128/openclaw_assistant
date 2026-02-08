"""
聊天气泡组件 - 漫画风格白底黑边 + 左下尖角指向助手，默认 15 秒关闭；支持多屏跟随
"""
from PyQt5.QtCore import Qt, QTimer, QPoint, QPointF, QRect, QRectF, pyqtSignal
from PyQt5.QtGui import QFont, QPainter, QPainterPath, QColor, QPen, QFontMetrics
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout, QApplication, QScrollArea, QPushButton, QHBoxLayout

from utils.platform_adapter import ui_bubble_font_family, ui_bubble_font_size


def _bubble_cfg():
    """从 config/ui_settings.json 读取气泡参数，缺失时用默认。"""
    try:
        from ui.ui_settings_loader import get_ui_setting
        sb = get_ui_setting("speech_bubble") or {}
        tail = sb.get("tail") or {}
        return {
            "default_duration_ms": int(sb.get("default_duration_ms", 15000)),
            "gap_above_pet_px": int(sb.get("gap_above_pet_px", 2)),
            "tail_w": int(tail.get("width_px", 14)),
            "tail_h": int(tail.get("height_px", 12)),
            "border_px": int(sb.get("border_px", 2)),
            "radius_px": int(sb.get("radius_px", 8)),
            "chars_per_line": int(sb.get("chars_per_line", 22)),
            "lines_height": int(sb.get("lines_height", 10)),
            "close_button_size_px": int(sb.get("close_button_size_px", 20)),
            "max_width_px": int(sb.get("max_width_px", 400)),
        }
    except Exception:
        return {
            "default_duration_ms": 15000,
            "gap_above_pet_px": 2,
            "tail_w": 14,
            "tail_h": 12,
            "border_px": 2,
            "radius_px": 8,
            "chars_per_line": 22,
            "lines_height": 10,
            "close_button_size_px": 20,
            "max_width_px": 400,
        }


def _filter_bubble_text(text):
    """过滤气泡框文字：去掉 Markdown 粗体标记「 **」「** 」及成对 **，避免在气泡中显示。"""
    if not text or not isinstance(text, str):
        return text or ""
    s = text.replace(" **", "").replace("** ", "")
    # 去掉首尾或句中成对的 **（粗体包裹）
    while "**" in s:
        s = s.replace("**", "", 1)
    return s.strip()


class SpeechBubble(QWidget):
    """聊天气泡 - 白底粗黑边、左下尖角指向助手，用 mapToGlobal 做多屏坐标"""
    close_requested = pyqtSignal()  # 关闭请求信号

    def __init__(self, parent_widget, text="", duration_ms=None, max_width=None, on_hide=None):
        super().__init__(None)  # 无父窗口，独立顶层窗口便于跨屏
        cfg = _bubble_cfg()
        self.parent_widget = parent_widget
        self.duration_ms = duration_ms if duration_ms is not None else cfg["default_duration_ms"]
        self.is_showing = False
        self._hide_timer = None
        self.on_hide = on_hide  # 气泡关闭时回调（完事后可用来触发 20 秒切回 walk）
        self._voice_process = None  # 存储语音播放进程，用于停止
        self._tail_w = cfg["tail_w"]
        self._tail_h = cfg["tail_h"]
        self._border_px = cfg["border_px"]
        self._close_btn = cfg["close_button_size_px"]
        self._radius_px = cfg["radius_px"]
        self._gap_above_pet = cfg["gap_above_pet_px"]
        _chars = cfg["chars_per_line"]
        self._lines_height = cfg["lines_height"]  # 最大显示行数，供 _adjust_height 使用
        _lines = self._lines_height
        _max_w = (max_width if max_width is not None else cfg["max_width_px"])

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # 计算宽度和高度（基于字体大小）
        font = QFont(ui_bubble_font_family(), ui_bubble_font_size())
        fm = QFontMetrics(font)
        char_width = fm.width("中")  # 使用中文字符宽度
        line_height = fm.height()
        self.char_width = char_width
        self.line_height = line_height
        # 宽度：N个字 + 左右padding + 边框 + 关闭按钮空间
        self.bubble_width = min(_max_w, char_width * _chars + 24 + 2 * self._border_px + self._close_btn + 8)
        # 最大高度：N行 + 上下padding + 边框 + 尖角 + 关闭按钮空间
        self.max_bubble_height = line_height * _lines + 20 + 2 * self._border_px + self._tail_h + self._close_btn + 4
        self.min_bubble_height = line_height * 2 + 20 + 2 * self._border_px + self._tail_h + self._close_btn + 4  # 最少2行

        # 主布局（包含内边距，用于绘制边框）
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(self._border_px, self._border_px, self._border_px, self._border_px + self._tail_h)
        main_layout.setSpacing(0)

        # 顶部布局：关闭按钮（绝对定位在右上角）
        self.close_button = QPushButton("×", self)
        self.close_button.setFixedSize(self._close_btn, self._close_btn)
        self.close_button.setFont(QFont(ui_bubble_font_family(), ui_bubble_font_size() - 2))
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(200, 200, 200, 200);
                border: 1px solid rgba(100, 100, 100, 200);
                border-radius: 10px;
                color: black;
            }
            QPushButton:hover {
                background-color: rgba(255, 100, 100, 255);
                border: 1px solid rgba(200, 50, 50, 255);
            }
        """)
        self.close_button.clicked.connect(self._on_close_clicked)
        self.close_button.raise_()  # 确保按钮在最上层

        # 滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setFont(font)
        self.label.setStyleSheet("background: transparent; color: black; border: none; padding: 8px;")
        self.label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll_area.setWidget(self.label)
        main_layout.addWidget(self.scroll_area)
        
        # 初始设置最小高度，实际高度会根据内容动态调整
        self.setMinimumSize(self.bubble_width, self.min_bubble_height)
        self.setMaximumSize(self.bubble_width, self.max_bubble_height)

    def show_bubble(self, text=None):
        if text is not None:
            self.label.setText(_filter_bubble_text(text))
            # 根据内容动态调整高度
            self._adjust_height()
        if self._hide_timer:
            self._hide_timer.stop()
        self._reposition()
        self.show()
        self.raise_()
        self.is_showing = True
        if self._hide_timer is None:
            self._hide_timer = QTimer(self)
            self._hide_timer.timeout.connect(self._do_hide)
        self._hide_timer.start(self.duration_ms)
    
    def _adjust_height(self):
        """根据文本内容动态调整气泡高度（PyQt5 无 lineCount，用 boundingRect 算换行行数）"""
        text = self.label.text()
        if not text:
            return
        fm = QFontMetrics(self.label.font())
        available_width = self.bubble_width - 2 * self._border_px - self._close_btn - 8 - 16  # 减去padding
        if available_width <= 0:
            available_width = 100
        rect = fm.boundingRect(QRect(0, 0, available_width, 9999), Qt.TextWordWrap, text)
        text_lines = max(1, rect.height() // fm.height())
        # 限制在最小2行和最大 _lines_height 行之间
        actual_lines = max(2, min(text_lines, self._lines_height))
        # 计算实际高度
        actual_height = self.line_height * actual_lines + 20 + 2 * self._border_px + self._tail_h + self._close_btn + 4
        actual_height = max(self.min_bubble_height, min(actual_height, self.max_bubble_height))
        # 设置固定高度
        self.setFixedHeight(actual_height)
        # 更新滚动区域大小
        self.scroll_area.setFixedSize(
            self.bubble_width - 2 * self._border_px - self._close_btn - 8,
            actual_height - 2 * self._border_px - self._tail_h - self._close_btn - 4
        )

    def set_duration_ms(self, ms: int):
        """动态设置关闭时长（毫秒），若气泡正在显示则重启关闭定时器。"""
        self.duration_ms = max(1000, int(ms))
        if self.is_showing and self._hide_timer:
            self._hide_timer.stop()
            self._hide_timer.start(self.duration_ms)

    def _reposition(self):
        if not self.parent_widget or not self.parent_widget.isVisible():
            return
        # 使用全局坐标，保证多屏下气泡与助手同屏
        try:
            pt = self.parent_widget.mapToGlobal(QPoint(0, 0))
        except Exception:
            pt = QPoint(self.parent_widget.x(), self.parent_widget.y())
        px, py = pt.x(), pt.y()
        pw = self.parent_widget.width()
        ph = self.parent_widget.height()
        bw, bh = self.width(), self.height()
        # 气泡在助手正上方，紧贴（_gap_above_pet 像素）
        bx = px + (pw - bw) // 2
        by = py - bh - self._gap_above_pet
        # 限制在虚拟桌面内，避免被裁到屏幕外
        try:
            screen = QApplication.screenAt(QPoint(px + pw // 2, py))
            if screen:
                geo = screen.availableGeometry()
                bx = max(geo.x(), min(bx, geo.x() + geo.width() - bw))
                by = max(geo.y(), min(by, geo.y() + geo.height() - bh))
        except Exception:
            bx = max(0, bx)
            by = max(0, by)
        self.move(bx, by)
        # 更新关闭按钮位置（右上角）
        self.close_button.move(bw - self._close_btn - self._border_px - 4, self._border_px + 2)

    def _on_close_clicked(self):
        """关闭按钮点击事件：先立即停止语音，再隐藏气泡，使用户点击 X 后声音马上停"""
        self._stop_voice()
        self.is_showing = False
        if self._hide_timer:
            self._hide_timer.stop()
            self._hide_timer = None
        if callable(getattr(self, "on_hide", None)):
            self.on_hide()
        self.hide()
        self.close_requested.emit()

    def _stop_voice(self):
        """停止语音播放"""
        try:
            from utils.voice_tts import stop_speech
            stop_speech()
        except Exception as e:
            from utils.logger import logger
            logger.debug(f"停止语音失败: {e}")

    def set_voice_process(self, process):
        """设置语音播放进程，用于停止"""
        self._voice_process = process

    def _do_hide(self):
        self.is_showing = False
        self._stop_voice()
        if callable(getattr(self, "on_hide", None)):
            self.on_hide()
        self.hide()

    def update_position(self):
        if self.is_showing and self.isVisible():
            self._reposition()

    def paintEvent(self, event):
        """自绘：白底、粗黑边、正下方尖角（从助手正上方映出的说话效果）"""
        w, h = self.width(), self.height()
        # 主体圆角矩形（不含尖角区域）
        body = QRectF(self._border_px, self._border_px, w - 2 * self._border_px, h - 2 * self._border_px - self._tail_h)
        tail_top = body.bottom()
        cx = body.left() + body.width() / 2
        # 尖角：底部正中小三角，垂直指向下方（助手头顶）
        tail_poly = [
            QPointF(cx - self._tail_w / 2, tail_top),
            QPointF(cx, tail_top + self._tail_h),
            QPointF(cx + self._tail_w / 2, tail_top),
        ]

        path = QPainterPath()
        path.addRoundedRect(body, self._radius_px, self._radius_px)
        tail_path = QPainterPath()
        tail_path.moveTo(tail_poly[0])
        tail_path.lineTo(tail_poly[1])
        tail_path.lineTo(tail_poly[2])
        tail_path.closeSubpath()
        path = path.united(tail_path)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        # 粗黑边
        p.setPen(QPen(QColor(0, 0, 0), self._border_px, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(QColor(255, 255, 255))
        p.drawPath(path)
        p.end()
