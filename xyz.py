"""x"""

import logging
from urllib import parse as urlparse
from pprint import pprint
from zoneinfo import ZoneInfo
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from bs4.element import PageElement

from letterboxd_followbot.config import Config
from letterboxd_followbot.letterboxd.api import LetterboxdClient


# class Film:
#     def __init__(self, imdb_id: str, letterboxd_id: str, name: str):
#         self.imdb_id = imdb_id
#         self.letterboxd_id = letterboxd_id
#         self.playtimes = []
#         self.name = name

#     def __repr__(self):
#         return f"Film(Imdb:{self.imdb_id};Name:{self.name};Playtimes:{len(self.playtimes)})"


# class FilmPlaytime:
#     def __init__(self, city: str, cinema: str):
#         self.city = city
#         self.cinema = cinema

#     pass


class KinoDeCinema:
    def __init__(
        self,
        name: str,
        city: str,
        display_name: str,
    ):
        self.name = name
        self.city = city
        self.display_name = display_name

    def __repr__(self):
        return f"KinoDeCinema(name='{self.name}', city='{self.city}', display_name='{self.display_name}')"


class KinoDeFilmPlaytime:
    def __init__(
        self,
        cinema: KinoDeCinema,
        shop_url: str,
        imdb_id: str,
        showtime: datetime,
    ):
        self.cinema = cinema
        self.shop_url = shop_url
        self.imdb_id = imdb_id
        self.showtime = showtime

    def __repr__(self):
        return f"KinoDeFilmPlaytime(showtime={self.showtime}, cinema={self.cinema.display_name})"


class KinoDeFilm:
    def __init__(
        self,
        title: str,
        page_url: str,
        poster_url: str,
        imdb_id: str,
        playtimes: list[KinoDeFilmPlaytime],
    ):
        self.title = title
        self.page_url = page_url
        self.poster_url = poster_url
        self.playtimes = playtimes
        self.imdb_id = imdb_id

    def __repr__(self):
        return f"KinoDeFilm(title='{self.title}'; imdb_id='{self.imdb_id}'; playtimes={len(self.playtimes)})"


class KinoDeScaper:
    def __init__(self, timezone: str = "Europe/Berlin"):
        self.base_url = "https://www.kino.de"
        parsed_url = urlparse.urlparse(self.base_url)
        self.default_scheme = parsed_url.scheme
        self.films = {}
        self.zoneinfo = ZoneInfo(timezone)

    def scrape_films(self, city_name: str, cinema_name: str):
        soup = self._fetch_cinema_program(city_name, cinema_name)
        cinema_movies = soup.select("ul.cinema-movies li.cinema-movie")
        films = self._parse_cinema_movies(cinema_movies, city_name, cinema_name)

        return films

    def flatten_films(self, films: list[KinoDeFilm]) -> list[KinoDeFilm]:
        flattened_films = {}

        for film in films:
            if film.imdb_id not in flattened_films:
                flattened_films[film.imdb_id] = film
            else:
                flattened_films[film.imdb_id].playtimes.extend(film.playtimes)

        return list(flattened_films.values())

    def _fetch_cinema_program(self, city: str, cinema_name: str) -> BeautifulSoup:
        response = httpx.get(
            f"{self.base_url}/kinoprogramm/stadt/{city}/kino/{cinema_name}/"
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        return soup

    def _parse_cinema_movies(
        self, cinema_movies: list[PageElement], city_name: str, cinema_name: str
    ) -> list[KinoDeFilm]:
        films = []
        for cinema_movie in cinema_movies:
            # film title and link to kino.de page
            title_link_element = cinema_movie.select_one(
                ".alice-teaser-title a.alice-teaser-link"
            )
            title = title_link_element.get_text()
            link = self.__fix_url(title_link_element.get("href"))

            # film poster
            image_element = cinema_movie.select_one(".alice-teaser-image img")
            poster = self.__fix_url(image_element.get("data-src"))

            schedules_container = cinema_movie.select_one("ol.schedules-container")
            cinema_display_name = schedules_container.get("data-cinema-name")
            cinema = KinoDeCinema(city_name, cinema_name, cinema_display_name)

            schedule_playtimes = cinema_movie.select(
                "ol.schedules-container li.schedule-playtime"
            )
            playtimes = self._parse_playtimes(schedule_playtimes, cinema)
            imdb_id = playtimes[0].imdb_id

            film = KinoDeFilm(
                title=title,
                page_url=link,
                poster_url=poster,
                playtimes=playtimes,
                imdb_id=imdb_id,
            )
            films.append(film)
        return films

    def _parse_playtimes(
        self, playtimes: list[PageElement], cinema: KinoDeCinema
    ) -> list[str]:
        film_playtimes = []
        for playtime in playtimes:
            link = playtime.select_one("a")
            shop_url = urlparse.urlparse(link.get("href"))

            query_params = urlparse.parse_qs(shop_url.query)
            imdb_id = query_params.get("imdb")[0]
            showtime_ts = int(query_params.get("showtime_date")[0])
            showtime = datetime.fromtimestamp(showtime_ts, tz=self.zoneinfo)

            film_playtime = KinoDeFilmPlaytime(
                cinema=cinema,
                shop_url=shop_url,
                imdb_id=imdb_id,
                showtime=showtime,
            )
            film_playtimes.append(film_playtime)

        return film_playtimes

    def __fix_url(self, url: str) -> str:
        if url.startswith("//"):
            return f"{self.default_scheme}:{url}"
        return

    # def scrape_playtimes(self, city: str, cinema: str):
    #     response = httpx.get(
    #         f"{self.base_url}/kinoprogramm/stadt/{city}/kino/{cinema}/"
    #     )
    #     response.raise_for_status()

    #     soup = BeautifulSoup(response.text, "html.parser")
    #     playtimes = soup.select("li.schedule-playtime")

    #     for playtime in playtimes:
    #         link = playtime.select_one("a")
    #         link_href = urlparse.urlparse(link.get("href"))

    #         query_params = urlparse.parse_qs(link_href.query)

    #         imdb_id = query_params.get("imdb")[0]

    #         if imdb_id not in self.films:
    #             try:
    #                 letterboxd_film = self.letterboxd_client.search_film_via_imdb_id(
    #                     imdb_id
    #                 )
    #             except Exception as e:
    #                 letterboxd_film = {}
    #             # print(letterboxd_film)
    #             self.films[imdb_id] = Film(
    #                 imdb_id, letterboxd_film.get("id"), letterboxd_film.get("name")
    #             )
    #         self.films[imdb_id].playtimes.append(FilmPlaytime(city, cinema))

    #     # return movies

    # def get_films(self):
    #     return self.films


def main():
    Config.load()
    logging.basicConfig(level=logging.INFO)

    letterboxd_client = LetterboxdClient.from_config()
    scraper = KinoDeScaper()

    cinema_ids = [
        ("koblenz", "apollo-koblenz"),
        ("koblenz", "kinopolis-koblenz"),
        ("montabaur", "capitol-montabaur"),
        ("lahnstein", "kino-lahnstein"),
    ]

    films = []
    for city_name, cinema_name in cinema_ids:
        films.extend(scraper.scrape_films(city_name, cinema_name))

    films = scraper.flatten_films(films)

    for film in films:
        print(f"{film.title} (IMDB: {film.imdb_id}, #{len(film.playtimes)})")
        for playtime in sorted(film.playtimes, key=lambda x: x.showtime):

            print(f"\t{playtime.showtime.strftime("%d.%m.%Y %a %H:%M")} - {playtime.cinema.display_name}")


if __name__ == "__main__":
    main()
