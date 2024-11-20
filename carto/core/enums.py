"""
Code taken from the Felt QGIS Plugin
Original code at https://github.com/felt/qgis-plugin
"""

from enum import Enum, auto


class ObjectType(Enum):
    """
    Object types
    """

    User = auto()
    Map = auto()

    @staticmethod
    def from_string(string: str) -> "ObjectType":
        """
        Converts string value to an object type
        """
        return {"user": ObjectType.User, "map": ObjectType.Map}[string]


class AuthState(Enum):
    """
    Authentication states
    """

    NotAuthorized = auto()
    Authorizing = auto()
    Authorized = auto()
