from bs4 import BeautifulSoup
from telegram.helpers import escape_markdown


class Util:
    @staticmethod
    def sanitize_html(text: str) -> str:
        # Replace <br> with new line characters
        text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")

        # Remove all tags except for the ones that are allowed by Telegram
        soup = BeautifulSoup(text, "html.parser")
        for e in soup.find_all():
            if e.name not in [
                "b",
                "strong",
                "i",
                "em",
                "u",
                "ins",
                "s",
                "strike",
                "span",
                "tg-spoiler",
                "tg-emoji",
                "a",
                "code",
                "pre",
                "blockquote",
            ]:
                e.unwrap()
        return str(soup)

    @staticmethod
    def escape_md(text: str) -> str:
        return escape_markdown(text, version=2)
