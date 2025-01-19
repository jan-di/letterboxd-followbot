import os
import sys
import asyncio
import math
import logging
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from telegram import (
    Update,
    User as TelegramUser,
    Chat as TelegramChat,
    ForceReply,
    ReplyKeyboardMarkup,
)
from telegram.helpers import escape_markdown
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
import dotenv

from letterboxd_followbot.database.model import (
    Base,
    User,
    Chat,
    FollowMember,
    FollowMemberType,
)
from letterboxd_followbot.letterboxd.api import LetterboxdClient

engine = create_engine("sqlite:///local.db")

dotenv.load_dotenv()

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
app = ApplicationBuilder().token(TG_TOKEN).build()

LETTERBOXD_CLIENT_ID = os.environ.get("LETTERBOXD_CLIENT_ID")
LETTERBOXD_CLIENT_SECRET = os.environ.get("LETTERBOXD_CLIENT_SECRET")
letterboxd_client = LetterboxdClient(LETTERBOXD_CLIENT_ID, LETTERBOXD_CLIENT_SECRET)


class Util:
    @staticmethod
    def film_title_and_year_line(film: dict) -> str:
        letterboxd_link = ""
        for link in film["links"]:
            if link["type"] == "letterboxd":
                letterboxd_link = link["url"]
                break
        return "[{}]({}) \\({}\\)\n".format(
            Util.escape(film["name"]),
            letterboxd_link,
            film["releaseYear"],
        )

    @staticmethod
    def directors_line(film: dict) -> str:
        line = Util.escape(f"{film['directors'][0]['name']}")
        if len(film["directors"]) > 1:
            line += Util.escape(f" + {len(film['directors']) - 1}")
        return f"{line}\n"

    @staticmethod
    def average_rating_line(film: dict, film_stats: dict) -> str:
        result = Util.escape(
            Util.get_rating_histogram_string(film_stats["ratingsHistogram"])
        )
        if "rating" in film:
            result += Util.escape(f" {round(film['rating'], 1)}")
        result += "\n"

        return result

    @staticmethod
    def log_details_line(log_entry: dict) -> str:
        line = ""
        if "rating" in log_entry:
            line += Util.escape(f"{Util.get_star_string(log_entry['rating'])}")
        if "like" in log_entry and log_entry["like"]:
            line += Util.escape(" ❤️")
        if "diaryDetails" in log_entry and log_entry["diaryDetails"]["rewatch"]:
            line += Util.escape(" 🔄")
        if "review" in log_entry:
            line += Util.escape(" 📝")
        return f"{line.strip()}\n"

    @staticmethod
    def log_tags_line(log_entry: dict) -> str:
        result = ""
        if len(log_entry["tags2"]) > 0:
            first = True
            for tag in log_entry["tags2"]:
                result += Util.escape(f"{" " if not first else ""}#{tag['displayTag']}")
                first = False
            result += "\n"
        return result

    @staticmethod
    def film_stats_line(film_stats: dict) -> str:
        return Util.escape(
            "👁️ {} ❤️ {} 🗒️ {}\n".format(
                Util.round_number_with_suffix(film_stats["counts"]["watches"]),
                Util.round_number_with_suffix(film_stats["counts"]["likes"]),
                Util.round_number_with_suffix(film_stats["counts"]["reviews"]),
            )
        )

    @staticmethod
    def get_star_string(rating: float) -> str:
        full_stars = math.floor(rating)
        half_star = math.ceil(rating - full_stars)

        return "★" * full_stars + "½" * half_star

    @staticmethod
    def get_rating_histogram_string(ratings_histogram: list) -> str:
        result = ""
        biggest_count = max(map(lambda r: r["count"], ratings_histogram))

        chars = "　▁▂▃▄▅▆▇█"

        if biggest_count == 0:
            result = "　　　　　　　　　　"
        else:
            for rating in ratings_histogram:
                count = rating["count"]
                result += f"{chars[math.ceil(count/biggest_count*8)]}"

        return "[" + result + "]"

    @staticmethod
    def round_number_with_suffix(number: int) -> str:
        suffixes = ["", "K", "M", "B"]
        suffix_index = 0

        while number >= 1000:
            number /= 1000
            suffix_index += 1

        return f"{round(number, 1)}{suffixes[suffix_index]}"

    @staticmethod
    def escape(text: str) -> str:
        return escape_markdown(text, version=2)

    @staticmethod
    def sanitize_html(text: str) -> str:
        text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
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
    def get_largest_compatible_poster(film: dict) -> dict:
        largest_poster = film["poster"]["sizes"][-1]
        # TODO check for max width, height and ratio
        return largest_poster

    @staticmethod
    async def send_film_poster_with_caption(
        chat_id: int, film: dict, caption: str
    ) -> None:
        poster = Util.get_largest_compatible_poster(film)
        await app.bot.send_photo(
            chat_id, poster["url"], caption, parse_mode="MarkdownV2"
        )

    @staticmethod
    async def send_review_message(chat_id: int, review: dict) -> None:
        title = "📝 Review:"
        text = review["text"]
        if review["containsSpoilers"]:
            title += " 🚨 Spoiler Alert 🚨"
            text = f"<tg-spoiler>{text}</tg-spoiler>"
        await app.bot.send_message(
            chat_id,
            f"{title}\n{Util.sanitize_html(text)}",
            parse_mode="HTML",
        )


async def notify():
    logging.basicConfig(level=logging.INFO)

    with Session(engine) as session:
        # iterate over all follow members
        for follow_member in session.query(FollowMember).all():
            # get the chat
            chat = session.get(Chat, follow_member.chat_id)
            member_id = follow_member.member_id
            last_checked_at = follow_member.last_checked_at.replace(tzinfo=timezone.utc)

            new_activities = []
            logging.info("Search activities for {}/{}. Last checked {}".format(chat.title, member_id, last_checked_at))

            done = False
            cursor = None
            while not done:

                activities = letterboxd_client.get_member_own_activity(
                    member_id,
                    include=[
                        "DiaryEntryActivity",
                        "ReviewActivity",
                        "WatchlistActivity",
                        "FilmLikeActivity",
                        "FilmRatingActivity",
                        "FilmWatchActivity",
                    ],
                    cursor=cursor,
                )

                for activity in activities["items"]:
                    when_created = datetime.fromisoformat(activity["whenCreated"])

                    if when_created <= last_checked_at:
                        done = True
                        break
                    new_activities.append(activity)
                if "next" not in activities:
                    done = True
                else:
                    cursor = activities["next"]

            logging.info("Found {} new activities for {}/{}".format(len(new_activities), chat.title, member_id))

            for activity in new_activities:
                logging.info("Processing activity of type {}".format(activity["type"]))

                match activity["type"]:
                    case "DiaryEntryActivity":
                        diary_entry = activity["diaryEntry"]
                        member = activity["member"]
                        film = diary_entry["film"]
                        film_stats = letterboxd_client.get_film_statistics(film["id"])

                        caption = "📖 {} added to {} diary:\n".format(
                            Util.escape(member["displayName"]),
                            Util.escape(member["pronoun"]["possessiveAdjective"]),
                        )

                        caption += Util.log_details_line(diary_entry)
                        caption += Util.log_tags_line(diary_entry)
                        caption += "\n"
                        caption += Util.film_title_and_year_line(film)
                        caption += Util.directors_line(film)
                        caption += Util.average_rating_line(film, film_stats)
                        caption += Util.film_stats_line(film_stats)

                        await Util.send_film_poster_with_caption(chat.id, film, caption)
                        if "review" in diary_entry:
                            await Util.send_review_message(
                                chat.id, diary_entry["review"]
                            )

                    case "WatchlistActivity":
                        film = activity["film"]
                        member = activity["member"]
                        film_stats = letterboxd_client.get_film_statistics(film["id"])

                        caption = "⌛ {} added to {} watchlist:\n".format(
                            Util.escape(member["displayName"]),
                            Util.escape(member["pronoun"]["possessiveAdjective"]),
                        )

                        caption += "\n"
                        caption += Util.film_title_and_year_line(film)
                        caption += Util.directors_line(film)
                        caption += Util.average_rating_line(film, film_stats)
                        caption += Util.film_stats_line(film_stats)

                        await Util.send_film_poster_with_caption(chat.id, film, caption)

                    case "FilmLikeActivity":
                        film = activity["film"]
                        member = activity["member"]
                        film_stats = letterboxd_client.get_film_statistics(film["id"])

                        caption = "❤️ {} liked:\n".format(
                            Util.escape(member["displayName"]),
                        )

                        caption += "\n"
                        caption += Util.film_title_and_year_line(film)
                        caption += Util.directors_line(film)
                        caption += Util.average_rating_line(film, film_stats)
                        caption += Util.film_stats_line(film_stats)

                        await Util.send_film_poster_with_caption(chat.id, film, caption)

                    case "FilmRatingActivity":
                        film = activity["film"]
                        member = activity["member"]
                        film_stats = letterboxd_client.get_film_statistics(film["id"])

                        caption = "⭐ {} rated:\n".format(
                            Util.escape(member["displayName"]),
                        )

                        caption += Util.escape(
                            f"{Util.get_star_string(activity['rating'])}\n"
                        )

                        caption += "\n"
                        caption += Util.directors_line(film)
                        caption += Util.film_title_and_year_line(film)
                        caption += Util.average_rating_line(film, film_stats)
                        caption += Util.film_stats_line(film_stats)

                        await Util.send_film_poster_with_caption(chat.id, film, caption)

                    case "ReviewActivity":
                        review_entry = activity["review"]
                        film = review_entry["film"]
                        member = activity["member"]
                        film_stats = letterboxd_client.get_film_statistics(film["id"])

                        caption = "📝 {} reviewed:\n".format(
                            Util.escape(member["displayName"]),
                        )

                        caption += Util.log_details_line(review_entry)
                        caption += Util.log_tags_line(review_entry)
                        caption += "\n"
                        caption += Util.film_title_and_year_line(film)
                        caption += Util.directors_line(film)
                        caption += Util.average_rating_line(film, film_stats)
                        caption += Util.film_stats_line(film_stats)

                        await Util.send_film_poster_with_caption(chat.id, film, caption)
                        await Util.send_review_message(chat.id, review_entry["review"])

                await asyncio.sleep(4)

                print(activity["type"])

            follow_member.last_checked_at = datetime.now(timezone.utc)
            session.commit()

    logging.info("Done. Sleeping for 5 minutes")
    await asyncio.sleep(300)

def main():
    asyncio.run(notify())

if __name__ == "__main__":
    main()
