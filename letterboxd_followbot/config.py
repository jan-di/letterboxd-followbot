from os import environ
import logging

import dotenv


class Config:
    TELEGRAM_TOKEN = None
    LETTERBOXD_CLIENT_ID = None
    LETTERBOXD_CLIENT_SECRET = None

    @classmethod
    def load(cls):
        dotenv.load_dotenv()

        cls.TELEGRAM_TOKEN = environ.get("TELEGRAM_TOKEN")
        if cls.TELEGRAM_TOKEN is None:
            raise ValueError("TELEGRAM_TOKEN is not set")

        cls.LETTERBOXD_CLIENT_ID = environ.get("LETTERBOXD_CLIENT_ID")
        if cls.LETTERBOXD_CLIENT_ID is None:
            raise ValueError("LETTERBOXD_CLIENT_ID is not set")

        cls.LETTERBOXD_CLIENT_SECRET = environ.get("LETTERBOXD_CLIENT_SECRET")
        if cls.LETTERBOXD_CLIENT_SECRET is None:
            raise ValueError("LETTERBOXD_CLIENT_SECRET is not set")
