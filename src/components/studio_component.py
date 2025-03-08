import json
import websockets
import aiofiles
import base64
import cv2
import os
from typing import Dict, List, Optional, Any

studio_api = {
    "version": "1.0",
    "name": "VTubeStudioPublicAPI",
    "host": "localhost",
    "port": 8001,
}

studio_default = {
    "developer": "Hye",
    "plugin_name": "...",
    "plugin_icon": None,
    "authentication_token_path": "./studio_token.txt",
}

class StudioConnectionError(Exception):
    pass

class StudioAuthenticationError(Exception):
    pass

class StudioUnexpectedResponseError(Exception):
    pass

class StudioApiError(Exception):
    pass

class StudioComponent:
    def __init__(
            self,
            studio_plugin_info: Dict[str, Any] = studio_default,
            studio_api_info: Dict[str, Any] = studio_api,
            **args: Any
    ) -> None:
        self.host: str = studio_api_info.get("host", "localhost")
        self.port: int = studio_api_info.get("port", 8001)
        self.socket = None
        self.authentication_token: Optional[str] = None
        self.__connection_status: int = 0
        self.__authentication_status: int = 0
        self.api_name: str = studio_api_info["name"]
        self.api_version: str = studio_api_info["version"]
        self.plugin_name: str = studio_plugin_info["name"]
        self.plugin_icon: str = studio_plugin_info["plugin_icon"]
        self.plugin_developer: str = studio_plugin_info["developer"]
        self.token_path: str = studio_plugin_info["authentication_token_path"]
        self.recv_history: List[Dict[str, Any]] = []

        for key, value in args.items():
            setattr(self, key, value)

    # Connection Stuff
    async def connect(self) -> None:
        try:
            self.socket = await websockets.connect(f"ws://{self.host}:{self.port}")
            self.__connection_status = 1

        except Exception as e:
            raise StudioConnectionError(f"Failed to connect to studio api: {e}")

    async def close(self) -> None:
        if self.socket:
            await self.socket.close(code=1000, reason="Connection closed")
            self.__connection_status = 0

    async def request(self, request_msg: Dict[str, Any]) -> Dict[str, Any]:
        if self.__connection_status != 1:
            raise StudioConnectionError("Not connected to studio")

        await self.socket.send(json.dumps(request_msg))
        response_msg = await self.socket.recv()
        response_dict = json.loads(response_msg)
        self.recv_history.append(response_dict)

        if "errorID" in response_dict:
            raise StudioApiError(f"Studio Api Error {response_dict['errorID']}: {response_dict.get('message', 'No message')}")
        return response_dict

    # Authentication Stuff
    async def request_authentication_token(self, force: bool = False) -> None:
        response = await self.read_token()
        if response is None or response == "" or force:
            request_msg = self._request_authentication_token()
            response_dict = await self.request(request_msg)
            if "authenticationToken" in response_dict.get("data", {}):
                self.authentication_token = response_dict["data"]["authenticationToken"]
                await self.write_token()
                self.__authentication_status = 1
            else:
                raise StudioAuthenticationError(f"Studio Authentication Error: Failed to get authentication token: {response_dict}")

    async def request_authentication(self) -> bool:
        if not self.authentication_token:
            raise StudioAuthenticationError("Studio Authentication Error: Failed to get authentication token")

        request_msg = self._request_authentication(self.authentication_token)
        response_dict = await self.request(request_msg)

        if response_dict.get("data", {}).get("authenticated", False):
            self.__authentication_status = 2
            return True

        self.__authentication_status = -1
        raise StudioAuthenticationError(f"Studio Authentication Error: Failed to authenticate: {response_dict}")

    async def read_token(self) -> Optional[str]:
        if not os.path.exists(self.token_path):
            return None
        async with aiofiles.open(self.token_path, mode="r") as f:
            self.authentication_token = await f.read()

        return self.authentication_token

    async def write_token(self) -> None:
        if not self.authentication_token:
            raise StudioAuthenticationError("Studio Authentication Error: Failed to get authentication token")

        try:
            async with aiofiles.open(self.token_path, mode="w") as f:
                await f.write(self.authentication_token)

        except OSError as e:
            raise StudioUnexpectedResponseError(f"Failed to write token: {e}")

    async def get_connection_status(self) -> int:
        return  self.__connection_status

    async def get_authentication_status(self) -> int:
        return self.__authentication_status

    # Request Generation Stuff
    def _base_request(
            self,
            message_type: str,
            data: Optional[Dict[str, Any]] = None,
            request_id: str = "Id"
    ) -> Dict[str, Any]:
        if not message_type or not isinstance(message_type, str):
            raise StudioUnexpectedResponseError(f"Invalid message type: {message_type}")

        request = {
            "apiName": self.api_name,
            "apiVersion": self.api_version,
            "requestID": request_id,
            "messageType": message_type,
            "data": data if data is not None else {}
        }

        return  request

    def _request_authentication_token(self) -> Dict[str, Any]:
        data = {
            "pluginName": self.plugin_name,
            "pluginDeveloper": self.plugin_developer,
        }

        if self.plugin_icon:
            data["pluginIcon"] = self.plugin_icon

        return  self._base_request("AuthenticationTokenRequest", data)

    def _request_authentication(self, token: str)  -> Dict[str, Any]:
        if not token or not isinstance(token, str):
            raise StudioUnexpectedResponseError(f"Invalid token: {token}")

        data = {
            "pluginName": self.plugin_name,
            "pluginDeveloper": self.plugin_developer,
            "authenticationToken": token,
        }

        return  self._base_request("AuthenticationRequest", data)

