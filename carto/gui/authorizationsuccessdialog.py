import os

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices


WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "authorizationsuccessdialog.ui")
)


class AuthorizationSuccessDialog(BASE, WIDGET):
    def __init__(self, parent=None):
        super(QDialog, self).__init__(parent)
        self.setupUi(self)
        self.labelMain.linkActivated.connect(self._link_activated)
        self.btnOk.clicked.connect(self.accept)
        self.logout = False

    def _link_activated(self, link: str):

        if link == "documentation":
            url = QUrl("https://docs.carto.com")
            QDesktopServices.openUrl(url)
        elif link == "logout":
            self.logout = True
            self.accept()
