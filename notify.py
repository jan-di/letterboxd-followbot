import os
import sys
import asyncio
import math
import logging
from datetime import datetime, timezone
from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from telegram.ext import (
    ExtBot,
    ApplicationBuilder,
)
import dotenv

from letterboxd_followbot.database.model import (
    Chat,
    FollowMember,
    PopularTodo,
)
from letterboxd_followbot.letterboxd.api import LetterboxdClient
from letterboxd_followbot.telegram.util import Util as TelegramUtil
from letterboxd_followbot.config import Config
from letterboxd_followbot.letterboxd.ext import LetterboxdExt

engine = create_engine("sqlite:///data/local.db")

dotenv.load_dotenv()

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
app = ApplicationBuilder().token(TG_TOKEN).build()


@dataclass
class MemberEvent:
    def __init__(self, photo_url: str, caption: str, review: str = None):
        self.photo_url = photo_url
        self.caption = caption
        self.review = review
        self.when_created = None


class ActivityHandler:
    ACTIVITY_TYPES = {
        "DiaryEntryActivity": "_process_diary_entry_activity",
        "ReviewActivity": "_process_review_activity",
        "WatchlistActivity": "_process_watchlist_activity",
        "FilmLikeActivity": "_process_film_like_activity",
        "FilmRatingActivity": "_process_film_rating_activity",
        # "FilmWatchActivity": "_process_film_watch_activity",
    }

    def __init__(
        self,
        telegram_bot: ExtBot,
        letterboxd_client: LetterboxdClient,
    ) -> None:
        self.telegram_bot: ExtBot = telegram_bot
        self.letterboxd_client: LetterboxdClient = letterboxd_client
        self.logger: logging.Logger = logging.getLogger(__name__)

    def fetch_activities(self, member_id: str, after: datetime) -> list[dict]:
        done = False
        cursor = None
        result = []
        while not done:
            activities = self.letterboxd_client.get_member_own_activity(
                member_id,
                include=self.ACTIVITY_TYPES.keys(),
                cursor=cursor,
            )

            for activity in activities["items"]:
                when_created = datetime.fromisoformat(activity["whenCreated"])

                if when_created <= after:
                    done = True
                    break
                result.append(activity)
            if "next" not in activities:
                done = True
            else:
                cursor = activities["next"]

        result.reverse()
        return result

    def process_activity(self, activity: dict) -> MemberEvent:
        activity_type = activity["type"]
        when_created = activity["whenCreated"]
        when_created_dt = datetime.fromisoformat(when_created)
        member = activity["member"]

        logging.info(
            f"Processing {activity_type} created at {when_created} by {member['username']}"
        )

        if activity_type not in self.ACTIVITY_TYPES:
            raise ValueError(f"Unknown activity type {activity_type}")

        event = getattr(self, self.ACTIVITY_TYPES[activity_type])(activity)
        event.when_created = when_created_dt

        return event

    def _process_diary_entry_activity(self, activity: dict) -> MemberEvent:
        diary_entry = activity["diaryEntry"]
        member = activity["member"]
        film = diary_entry["film"]
        film_stats = self.letterboxd_client.get_film_statistics(film["id"])

        caption = "📖 {} added to {} diary:\n".format(
            TelegramUtil.escape_md(member["displayName"]),
            TelegramUtil.escape_md(member["pronoun"]["possessiveAdjective"]),
        )
        caption += self.__log_lines(diary_entry)
        caption += "\n"
        caption += self.__film_lines(film, film_stats)
        photo_url = self.__get_largest_compatible_poster_url(film)
        review = self.__create_review_message(diary_entry.get("review", None))

        return MemberEvent(photo_url, caption, review)

    def _process_review_activity(self, activity: dict) -> MemberEvent:
        review_entry = activity["review"]
        film = review_entry["film"]
        member = activity["member"]
        film_stats = self.letterboxd_client.get_film_statistics(film["id"])

        caption = "📝 {} reviewed:\n".format(
            TelegramUtil.escape_md(member["displayName"]),
        )
        caption += self.__log_lines(review_entry)
        caption += "\n"
        caption += self.__film_lines(film, film_stats)
        photo_url = self.__get_largest_compatible_poster_url(film)
        review = self.__create_review_message(review_entry.get("review", None))

        return MemberEvent(photo_url, caption, review)

    def _process_watchlist_activity(self, activity: dict) -> MemberEvent:
        film = activity["film"]
        member = activity["member"]
        film_stats = self.letterboxd_client.get_film_statistics(film["id"])

        caption = "⌛ {} added to {} watchlist:\n".format(
            TelegramUtil.escape_md(member["displayName"]),
            TelegramUtil.escape_md(member["pronoun"]["possessiveAdjective"]),
        )
        caption += "\n"
        caption += self.__film_lines(film, film_stats)
        photo_url = self.__get_largest_compatible_poster_url(film)

        return MemberEvent(photo_url, caption)

    def _process_film_like_activity(self, activity: dict) -> MemberEvent:
        film = activity["film"]
        member = activity["member"]
        film_stats = self.letterboxd_client.get_film_statistics(film["id"])

        caption = "❤️ {} liked:\n".format(
            TelegramUtil.escape_md(member["displayName"]),
        )
        caption += "\n"
        caption += self.__film_lines(film, film_stats)
        photo_url = self.__get_largest_compatible_poster_url(film)

        return MemberEvent(photo_url, caption)

    def _process_film_rating_activity(self, activity: dict) -> MemberEvent:
        film = activity["film"]
        member = activity["member"]
        film_stats = self.letterboxd_client.get_film_statistics(film["id"])

        caption = "⭐ {} rated:\n".format(
            TelegramUtil.escape_md(member["displayName"]),
        )
        caption += self.__rating_star_line(activity["rating"])
        caption += "\n"
        caption += self.__film_lines(film, film_stats)
        photo_url = self.__get_largest_compatible_poster_url(film)

        return MemberEvent(photo_url, caption)

    # def _process_film_watch_activity(self, activity: dict) -> MemberEvent:
    #     pass

    def __get_largest_compatible_poster_url(self, film: dict) -> dict:
        largest_poster = film["poster"]["sizes"][-1]
        # TODO check for max width, height and ratio
        return largest_poster["url"]

    def __create_review_message(chat_id: int, review: dict | None) -> str | None:
        if review is None:
            return None

        title = "📝 Review:"
        text = review["text"]
        if review["containsSpoilers"]:
            title += " 🚨 Spoiler Alert 🚨"
            text = f"<tg-spoiler>{text}</tg-spoiler>"

        return f"{title}\n{TelegramUtil.sanitize_html(text)}"

    def __film_lines(self, film: dict, film_stats: dict) -> str:
        result = ""
        result += self.__film_title_line(film)
        result += self.__film_directors_line(film)
        result += self.__film_rating_line(film, film_stats)
        result += self.__film_stats_line(film_stats)
        return result

    def __log_lines(self, log_entry: dict) -> str:
        result = ""
        result += self.__log_details_line(log_entry)
        result += self.__log_tags_line(log_entry)
        return result

    def __film_title_line(self, film: dict) -> str:
        letterboxd_link = ""
        for link in film["links"]:
            if link["type"] == "letterboxd":
                letterboxd_link = link["url"]
                break

        line = "[{}]({})".format(TelegramUtil.escape_md(film["name"]), letterboxd_link)
        if "releaseYear" in film:
            line += " \\({}\\)".format(film["releaseYear"])
        line += "\n"

        return line

    def __film_directors_line(self, film: dict) -> str:
        if "directors" not in film or len(film["directors"]) == 0:
            return ""
        line = TelegramUtil.escape_md(f"{film['directors'][0]['name']}")
        if len(film["directors"]) > 1:
            line += TelegramUtil.escape_md(f" + {len(film['directors']) - 1}")
        return f"{line}\n"

    def __film_rating_line(self, film: dict, film_stats: dict) -> str:
        result = TelegramUtil.escape_md(
            self.__get_rating_histogram_string(film_stats["ratingsHistogram"])
        )
        if "rating" in film:
            result += TelegramUtil.escape_md(f" {round(film['rating'], 1)}")
        result += "\n"

        return result

    def __film_stats_line(self, film_stats: dict) -> str:
        return TelegramUtil.escape_md(
            "👁️ {} ❤️ {} 🗒️ {}\n".format(
                self.__round_number_with_suffix(film_stats["counts"]["watches"]),
                self.__round_number_with_suffix(film_stats["counts"]["likes"]),
                self.__round_number_with_suffix(film_stats["counts"]["reviews"]),
            )
        )

    def __log_details_line(self, log_entry: dict) -> str:
        line = ""
        if "rating" in log_entry:
            line += TelegramUtil.escape_md(
                f"{self.__get_star_string(log_entry['rating'])}"
            )
        if "like" in log_entry and log_entry["like"]:
            line += TelegramUtil.escape_md(" ❤️")
        if "diaryDetails" in log_entry and log_entry["diaryDetails"]["rewatch"]:
            line += TelegramUtil.escape_md(" 🔄")
        if "review" in log_entry:
            line += TelegramUtil.escape_md(" 📝")
        return f"{line.strip()}\n"

    def __log_tags_line(self, log_entry: dict) -> str:
        result = ""
        if len(log_entry["tags2"]) > 0:
            first = True
            for tag in log_entry["tags2"]:
                result += TelegramUtil.escape_md(
                    f"{" " if not first else ""}#{tag['displayTag']}"
                )
                first = False
            result += "\n"
        return result

    def __rating_star_line(self, rating: float) -> str:
        return TelegramUtil.escape_md(f"{self.__get_star_string(rating)}\n")

    def __get_rating_histogram_string(self, ratings_histogram: list) -> str:
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

    def __get_star_string(self, rating: float) -> str:
        full_stars = math.floor(rating)
        half_star = math.ceil(rating - full_stars)

        return "★" * full_stars + "½" * half_star

    def __round_number_with_suffix(self, number: int) -> str:
        suffixes = ["", "K", "M", "B"]
        suffix_index = 0

        while number >= 1000:
            number /= 1000
            suffix_index += 1

        return f"{round(number, 1)}{suffixes[suffix_index]}"


async def send_member_event(chat_id: int, event: MemberEvent):
    photo_url = event.photo_url
    caption = event.caption
    review = event.review

    if photo_url:
        await app.bot.send_photo(
            chat_id, photo_url, caption=caption, parse_mode="MarkdownV2"
        )
    else:
        await app.bot.send_message(chat_id, caption, parse_mode="MarkdownV2")

    if review:
        await app.bot.send_message(chat_id, review, parse_mode="HTML")


async def notify():
    logging.basicConfig(level=logging.INFO)

    letterboxd_client = LetterboxdClient.from_config()

    while True:
        with Session(engine) as session:
            # iterate over all follow members
            for follow_member in session.query(FollowMember).all():
                # get the chat
                chat = session.get(Chat, follow_member.chat_id)
                member_id = follow_member.member_id
                last_checked_at = follow_member.last_checked_at.replace(
                    tzinfo=timezone.utc
                )

                logging.info(
                    "Search activities for {}/{}. Last checked {}".format(
                        chat.title, member_id, last_checked_at
                    )
                )

                ah = ActivityHandler(app.bot, letterboxd_client)
                activities = ah.fetch_activities(member_id, last_checked_at)

                logging.info(
                    "Found {} new activities for {}/{}".format(
                        len(activities), chat.title, member_id
                    )
                )

                events = []
                for activity in activities:
                    event = ah.process_activity(activity)
                    events.append(event)

                if len(events) == 0:
                    continue

                for event in events:
                    await send_member_event(chat.id, event)
                    await asyncio.sleep(4)

                follow_member.last_checked_at = events[-1].when_created
                session.commit()

        logging.info("Done. Sleeping for 2 minutes")
        await asyncio.sleep(2 * 60)


async def todo_popular():
    logger = logging.getLogger("todo_popular")
    letterboxd_client = LetterboxdClient.from_config()
    letterboxd_ext = LetterboxdExt(letterboxd_client)

    logger.info("Starting todo_popular")

    with Session(engine) as session:
        for popular_todo in session.query(PopularTodo).all():
            chat = session.get(Chat, popular_todo.chat_id)
            next_film, next_film_rank = letterboxd_ext.get_next_popular_movie(
                popular_todo.member_id
            )

            if (
                next_film != popular_todo.next_film_id
                or next_film_rank != popular_todo.next_rank
            ):
                photo_url = next_film["poster"]["sizes"][-1]["url"]
                caption = "🎥 Next popular movie\: \#{} [{}]({})".format(
                    next_film_rank,
                    TelegramUtil.escape_md(next_film["name"]),
                    next_film["links"][0]["url"],
                )

                await app.bot.send_photo(
                    chat.id, photo_url, caption=caption, parse_mode="MarkdownV2"
                )

                popular_todo.next_film_id = next_film["id"]
                popular_todo.next_rank = next_film_rank
                session.commit()

        logger.info("Done. Sleeping for 60 minutes")
        await asyncio.sleep(60 * 60)


def main():
    Config.load()
    return asyncio.run(main_threads())


async def main_threads():
    await asyncio.gather(
        notify(),
        todo_popular(),
    )


if __name__ == "__main__":
    main()
