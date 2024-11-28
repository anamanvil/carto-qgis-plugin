import os

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices, QPixmap


WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "authorizationsuccessdialog.ui")
)

SIGNUP_URL = "https://carto.com/signup"

pluginPath = os.path.dirname(__file__)


def img(f):
    return QPixmap(os.path.join(pluginPath, "img", f))


class AuthorizationSuccessDialog(BASE, WIDGET):
    def __init__(self, parent=None):
        super(QDialog, self).__init__(parent)
        self.setupUi(self)
        self.labelMain.linkActivated.connect(self._link_activated)
        self.btnLogout.clicked.connect(self.logout_requested)
        self.btnClose.clicked.connect(self.accept)
        self.logout = False

        pixmap = img("cartobanner.png")
        self.labelLogo.setPixmap(pixmap)
        self.labelLogo.setScaledContents(True)
        self.resize(pixmap.width(), pixmap.height())

    def _link_activated(self, link: str):
        if link == "documentation":
            url = QUrl("https://docs.carto.com")
            QDesktopServices.openUrl(url)

    def logout_requested(self):
        self.logout = True
        self.accept()
