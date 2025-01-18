from datetime import datetime, timedelta
import httpx


class LetterboxdClient:
    def __init__(
        self, client_id: str, client_secret: str, base_url: str = None
    ) -> None:
        if base_url is None:
            base_url = "https://api.letterboxd.com/api/v0"

        self.base_url = base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token_expiry = None
        self.client = httpx.Client()

        self.__acquire_access_token()

    def __acquire_access_token(self) -> None:
        url = f"{self.base_url}/auth/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }

        response = httpx.post(url, data=data)
        response.raise_for_status()
        restponse_json = response.json()

        self.access_token_expiry = datetime.now() + timedelta(
            seconds=restponse_json["expires_in"]
        )

        self.client.headers["Authorization"] = (
            f"Bearer {restponse_json["access_token"]}"
        )

    def __refresh_access_token(self) -> None:
        now = datetime.now() - timedelta(seconds=300)
        if self.access_token_expiry < now:
            self.__acquire_access_token()

    def search(self, input: str, include: list[str] = []) -> dict:
        self.__refresh_access_token()

        params = [("input", input)]
        for include_value in include:
            params.append(("include", include_value))

        response = httpx.get(f"{self.base_url}/search", params=params)

        response.raise_for_status()
        return response.json()
