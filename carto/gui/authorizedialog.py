import os

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices, QPixmap


WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "authorizedialog.ui")
)

SIGNUP_URL = "https://carto.com/signup"

pluginPath = os.path.dirname(__file__)


def img(f):
    return QPixmap(os.path.join(pluginPath, "img", f))


class AuthorizeDialog(BASE, WIDGET):
    def __init__(self, parent=None):
        super(QDialog, self).__init__(parent)
        self.setupUi(self)

        self.btnLogin.clicked.connect(self.accept)
        self.btnSignup.clicked.connect(self.signup)

        pixmap = img("cartobanner.png")
        self.labelLogo.setPixmap(pixmap)
        self.labelLogo.setScaledContents(True)
        self.resize(pixmap.width(), pixmap.height())

    def signup(self):
        QDesktopServices.openUrl(QUrl(SIGNUP_URL))
