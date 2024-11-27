import os

from qgis.PyQt.QtWidgets import QApplication
from qgis.PyQt.QtCore import Qt

from typing import Optional, Union

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import (
    QIcon,
    QFont,
    QFontMetrics,
    QImage,
    QPixmap,
    QFontDatabase,
    QColor,
    QPainter,
)
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.PyQt.QtWidgets import QMenu
from qgis.core import Qgis


def waitcursor(method):
    def func(*args, **kw):
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            return method(*args, **kw)
        except Exception as ex:
            raise ex
        finally:
            QApplication.restoreOverrideCursor()

    return func


def get_icon_svg(icon: str) -> str:
    """
    Returns a plugin icon's SVG file path
    :param icon: icon name (svg file name)
    :return: icon svg path
    """
    path = os.path.join(os.path.dirname(__file__), "img", icon)
    if not os.path.exists(path):
        return ""

    return path


def get_svg_as_image(
    icon: str,
    width: int,
    height: int,
    background_color: Optional[QColor] = None,
    device_pixel_ratio: float = 1,
) -> QImage:
    """
    Returns an SVG returned as an image
    """
    path = get_icon_svg(icon)
    if not os.path.exists(path):
        return QImage()

    renderer = QSvgRenderer(path)
    image = QImage(
        int(width * device_pixel_ratio),
        int(height * device_pixel_ratio),
        QImage.Format_ARGB32,
    )
    image.setDevicePixelRatio(device_pixel_ratio)
    if not background_color:
        image.fill(Qt.transparent)
    else:
        image.fill(background_color)

    painter = QPainter(image)
    painter.scale(1 / device_pixel_ratio, 1 / device_pixel_ratio)
    renderer.render(painter)
    painter.end()

    return image
