try:
    from urllib.parse import urljoin
except ImportError:
    from urlparse import urljoin
import requests
import uuid
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtWidgets import QDialog
from qgis.utils import iface
from qgis.core import Qgis
from carto.gui.authorizedialog import AuthorizeDialog
from carto.core.utils import (
    setting,
    TOKEN,
)
import os


BASE_URL = "https://workspace-gcp-us-east1.app.carto.com"
SQL_API_URL = "https://gcp-us-east1.api.carto.com"
USER_URL = "https://accounts.app.carto.com/users/me"


class CartoApi(QObject):

    __instance = None
    token = None

    @staticmethod
    def instance():
        if CartoApi.__instance is None:
            CartoApi.__instance = CartoApi()
        return CartoApi.__instance

    def __init__(self):
        super().__init__()
        if CartoApi.__instance is not None:
            raise Exception("Singleton class")

    def set_token(self, token):
        self.token = token

    def user(self):
        return self.get(USER_URL)

    def is_logged_in(self):
        return self.token is not None

    def get(self, endpoint, params=None):
        url = urljoin(BASE_URL, endpoint)
        response = requests.get(
            url, headers={"Authorization": f"Bearer {self.token}"}, params=params
        )
        return response

    def get_json(self, endpoint, params=None):
        response = self.get(endpoint, params)
        response.raise_for_status()
        return response.json()

    def execute_query(self, connectionname, query):
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

    def execute_query_post(self, connectionname, query):
        url = urljoin(SQL_API_URL, f"v3/sql/{connectionname}/query")
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.token}"},
            data={"q": query},
        )
        response.raise_for_status()
        _json = response.json()
        return _json

    def connections(self):
        connections = self.get_json("connections")
        return [
            {
                "id": connection["id"],
                "name": connection["name"],
                "provider_type": connection["provider_id"],
            }
            for connection in connections
        ]

    def databases(self, connectionid):
        databases = self.get_json(f"connections/{connectionid}/resources")["children"]
        return [
            {"id": database["id"].split(".")[-1], "name": database["name"]}
            for database in databases
        ]

    def schemas(self, connectionid, databaseid):
        schemas = self.get_json(f"connections/{connectionid}/resources/{databaseid}")[
            "children"
        ]
        return [
            {"id": schema["id"].split(".")[-1], "name": schema["name"]}
            for schema in schemas
        ]

    def tables(self, connectionid, databaseid, schemaid):
        tables = self.get_json(
            f"connections/{connectionid}/resources/{databaseid}.{schemaid}"
        )["children"]
        return [
            {"id": table["id"].split(".")[-1], "name": table["name"], "size": 0}
            for table in tables
            if table["type"] == "table"
        ]

    def table_info(self, connectionid, databaseid, schemaid, tableid):
        return self.get_json(
            f"connections/{connectionid}/resources/{databaseid}.{schemaid}.{tableid}"
        )
