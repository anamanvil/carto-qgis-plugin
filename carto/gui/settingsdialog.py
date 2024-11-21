import os

from carto.core.utils import setting, setSetting, TOKEN
from qgis.gui import QgsMessageBar

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QSizePolicy, QFileDialog

WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "settingsdialog.ui")
)


class SettingsDialog(BASE, WIDGET):
    def __init__(self, parent=None):
        super(QDialog, self).__init__(parent)
        self.setupUi(self)

        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout().addWidget(self.bar)

        self.buttonBox.accepted.connect(self.okClicked)
        self.buttonBox.rejected.connect(self.reject)

        self.setValues()

    def setValues(self):
        self.txtToken.setText(setting(TOKEN))

    def okClicked(self):
        setSetting(TOKEN, self.txtToken.text())
        self.accept()
