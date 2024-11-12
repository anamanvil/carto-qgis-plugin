import os

from carto.utils import setting, setSetting, MAXROWS, TOKEN
from qgis.utils import iface
from qgis.gui import QgsMessageBar

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QSizePolicy, QFileDialog

WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "settingsdialog.ui")
)


class SettingsDialog(BASE, WIDGET):
    def __init__(self):
        super(QDialog, self).__init__(iface.mainWindow())
        self.setupUi(self)

        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout().addWidget(self.bar)

        self.buttonBox.accepted.connect(self.okClicked)
        self.buttonBox.rejected.connect(self.reject)

        self.setValues()

    def setValues(self):
        self.txtToken.setText(setting(TOKEN))
        self.txtMaxRows.setText(setting(MAXROWS) or "100")

    def okClicked(self):
        setSetting(TOKEN, self.txtToken.text())
        setSetting(MAXROWS, self.txtMaxRows.text())
        self.accept()
