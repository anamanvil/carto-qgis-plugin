try:
    from urllib.parse import urljoin
except ImportError:
    from urlparse import urljoin
import requests
import uuid
from qgis.PyQt.QtCore import pyqtSignal, QObject
from qgis.PyQt.QtWidgets import QDialog, QAction
from qgis.PyQt.QtGui import QIcon
from qgis.utils import iface
from qgis.core import Qgis
from carto.gui.utils import waitcursor
from carto.gui.authorizedialog import AuthorizeDialog
from carto.core.utils import setting, TOKEN
import os

BASE_URL = "https://workspace-gcp-us-east1.app.carto.com"
SQL_API_URL = "https://gcp-us-east1.api.carto.com"


class CartoApi(QObject):

    __instance = None
    token = None

    logged_in = pyqtSignal()
    logged_out = pyqtSignal()

    @staticmethod
    def instance():
        if CartoApi.__instance is None:
            CartoApi.__instance = CartoApi()
        return CartoApi.__instance

    def __init__(self):
        super().__init__()
        if CartoApi.__instance is not None:
            raise Exception("Singleton class")

        self._login_action = QAction("Log in...")
        # self._login_action.setIcon(CARTO_ICON)
        self._login_action.triggered.connect(self.login)

    def login(self):
        dialog = AuthorizeDialog(iface.mainWindow())
        dialog.exec_()
        if dialog.result() == QDialog.Accepted:
            try:
                self.token = setting(TOKEN)
                self.get("https://accounts.app.carto.com/users/me")
                self._login_action.setText("Log out")
                self._login_action.triggered.disconnect(self.login)
                self._login_action.triggered.connect(self.logout)
                self.logged_in.emit()
            except Exception:
                iface.messageBar().pushMessage(
                    "Login failed",
                    "Please check your token and try again",
                    level=Qgis.Warning,
                    duration=10,
                )
            else:
                iface.messageBar().pushMessage(
                    "Login successful",
                    "You are now logged in",
                    level=Qgis.Success,
                    duration=10,
                )

    def logout(self):
        self.token = None
        self._login_action.setText("Log in...")
        self._login_action.triggered.disconnect(self.logout)
        self._login_action.triggered.connect(self.login)
        self.logged_out.emit()

    def login_action(self):
        return self._login_action

    def is_logged_in(self):
        return self.token is not None

    @waitcursor
    def get(self, endpoint, params=None):
        url = urljoin(BASE_URL, endpoint)
        response = requests.get(
            url, headers={"Authorization": f"Bearer {self.token}"}, params=params
        )
        response.raise_for_status()
        return response.json()

    def post(self, endpoint, data):
        pass

    @waitcursor
    def execute_query(self, connectionname, query):
        print(query)
        url = urljoin(SQL_API_URL, f"v3/sql/{connectionname}/query")
        query = f"""
        -- {uuid.uuid4()}
        {query}
        """
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {self.token}"},
            params={"q": query},
        )
        response.raise_for_status()
        _json = response.json()
        return _json

    def connections(self):
        connections = self.get("connections")
        return [
            {
                "id": connection["id"],
                "name": connection["name"],
                "provider_type": connection["provider_id"],
            }
            for connection in connections
        ]

    def databases(self, connectionid):
        databases = self.get(f"connections/{connectionid}/resources")["children"]
        return [
            {"id": database["id"].split(".")[-1], "name": database["name"]}
            for database in databases
        ]

    def schemas(self, connectionid, databaseid):
        schemas = self.get(f"connections/{connectionid}/resources/{databaseid}")[
            "children"
        ]
        return [
            {"id": schema["id"].split(".")[-1], "name": schema["name"]}
            for schema in schemas
        ]

    def tables(self, connectionid, databaseid, schemaid):
        tables = self.get(
            f"connections/{connectionid}/resources/{databaseid}.{schemaid}"
        )["children"]
        return [
            {"id": table["id"].split(".")[-1], "name": table["name"], "size": 0}
            for table in tables
            if table["type"] == "table"
        ]

    def table_info(self, connectionid, databaseid, schemaid, tableid):
        return self.get(
            f"connections/{connectionid}/resources/{databaseid}.{schemaid}.{tableid}"
        )

    def import_table_from_file(self, connectionid, fqn, filepaths):
        pass
