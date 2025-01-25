from letterboxd_followbot.letterboxd.api import LetterboxdClient


class LetterboxdExt:
    def __init__(self, letterboxd_client: LetterboxdClient) -> None:
        self.letterboxd_client = letterboxd_client

    def get_next_popular_movie(self, member_id: str):
        popular_films_cursor = None
        watched_films_cursor = None
        watched_film_ids = set()
        rank = 0
        done = False
        fetched_all_watched_films = False
        while not done:
            popular_films = self.letterboxd_client.get_films(
                sort="FilmPopularity", cursor=popular_films_cursor, per_page=100
            )

            for popular_film in popular_films["items"]:
                rank += 1

                if rank > len(watched_film_ids) and not fetched_all_watched_films:
                    watched_films = self.letterboxd_client.get_films(
                        sort="FilmPopularity",
                        member=member_id,
                        member_relationship="Watched",
                        cursor=watched_films_cursor,
                        per_page=100,
                    )
                    watched_film_ids = watched_film_ids.union(
                        [film["id"] for film in watched_films["items"]]
                    )

                    if "next" in watched_films:
                        watched_films_cursor = watched_films["next"]
                    else:
                        fetched_all_watched_films = True

                if not popular_film["id"] in watched_film_ids:
                    done = True
                    next_film = popular_film
                    break

            if "next" in popular_films:
                popular_films_cursor = popular_films["next"]

            if done:
                break

        return next_film, rank
