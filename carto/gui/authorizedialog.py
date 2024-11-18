import os

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices

WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "authorizedialog.ui")
)

SIGNUP_URL = "https://carto.com/signup"


class AuthorizeDialog(BASE, WIDGET):
    def __init__(self, parent=None):
        super(QDialog, self).__init__(parent)
        self.setupUi(self)

        self.btnLogin.clicked.connect(self.accept)
        self.btnSignup.clicked.connect(self.signup)

    def signup(self):
        QDesktopServices.openUrl(QUrl(SIGNUP_URL))
