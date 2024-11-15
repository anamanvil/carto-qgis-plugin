try:
    from urllib.parse import urljoin
except ImportError:
    from urlparse import urljoin
import requests
import json
from carto.gui.utils import waitcursor
import uuid

BASE_URL = "https://workspace-gcp-us-east1.app.carto.com"
SQL_API_URL = "https://gcp-us-east1.api.carto.com"


class CartoApi(object):
    __instance = None
    token = None

    @staticmethod
    def instance():
        if CartoApi.__instance is None:
            CartoApi()
        return CartoApi.__instance

    def __init__(self):
        if CartoApi.__instance is not None:
            raise Exception("Singleton class")

        CartoApi.__instance = self

    def login(self, token):
        self.token = token
        self.get("https://accounts.app.carto.com/users/me")

    def logout(self):
        self.token = None

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
