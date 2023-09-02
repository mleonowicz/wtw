import requests
from bs4 import BeautifulSoup
import urllib.parse
import configparser
from http import HTTPStatus
import logging
from collections import Counter
from tqdm import tqdm

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

config = configparser.ConfigParser()
config.read("config.toml")
API_KEY = config["TMDB"]["key"]


class Scrapper:
    """
    Simple scrapper class that holds information about url and headers
    that are used in requests.

    Parameters
    ----------
    url : str
        Base url that will be used in requests
    use_sessions : bool, optional
        If True, requests will be made using sessions, by default True
    """

    def __init__(self, url: str, use_sessions=True):
        self.url = url
        self.headers = {
            "User-Agent": "Mozilla/5.0",
        }
        self.requests = requests.Session() if use_sessions else requests

    def get(self, suffix: str) -> requests.Response:
        """
        Send GET request to url + suffix

        Parameters
        ----------
        suffix : str
            Suffix that will be added to base url

        Returns
        -------
        requests.Response
            Response object from requests library
        """
        return self.requests.get(f"{self.url}/{suffix}", headers=self.headers)


class Movie:
    def __init__(self, title: str, platforms: list[str] = []):
        """
        Movie class that holds information about movie title and streaming
        platforms that it is available on.

        Parameters
        ----------
        title : str
            Title of the movie
        platforms : list[str], optional
            List of streaming platforms that the movie is available on, by default []
        """
        self.title = title
        self.platforms = platforms

    @property
    def available(self) -> bool:
        """
        Check if movie is available on any streaming platform.

        Returns
        -------
        bool
            True if movie is available on any streaming platform, False otherwise
        """
        return len(self.platforms) > 0

    def __str__(self):
        if self.available:
            return (
                f"Movie: {self.title}\n\n"
                + "Platforms \n---------- \n"
                + "\n".join(sorted(self.platforms))
            )
        return f"Movie: {self.title}\nNot available on any streaming platform"


class TMDB:
    def __init__(self, country: str):
        """
        Parameters
        ----------
        country : str
            _description_
        """
        self.country = country
        self.api_key = API_KEY
        self.url = "https://api.themoviedb.org/3/"

        self.headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def get_streaming_platforms(self, movie_id: int) -> list[str]:
        """
        Get streaming platforms for movie from TMDB API.

        Parameters
        ----------
        movie_id : int
            Movie id, used to query TMDB API

        Returns
        -------
        list[str]
            List of streaming platforms
        """
        suffix = f"movie/{movie_id}/watch/providers"
        endpoint = f"{self.url}/{suffix}"
        response = requests.get(endpoint, headers=self.headers)

        if response.status_code != HTTPStatus.OK:
            logger.error(
                f"Error from endpoint {endpoint}, status code: {response.status_code}"
            )
            return []

        try:
            streaming_platforms = response.json()["results"][self.country]["flatrate"]
            return [platform["provider_name"] for platform in streaming_platforms]
        except KeyError:
            return []

    def get_movie_id(self, title: str) -> int | None:
        """
        Get movie id from TMDB API.

        Parameters
        ----------
        title : str
            Title of the movie, used to query TMDB API

        Returns
        -------
        int
            Movie id
        """
        parsed_query = urllib.parse.quote_plus(title)

        suffix = f"search/movie?query={parsed_query}&include_adult=true"
        endpoint = f"{self.url}/{suffix}"
        response = requests.get(endpoint, headers=self.headers)

        if response.status_code != HTTPStatus.OK:
            logger.error(
                f"Error from endpoint {endpoint}, status code: {response.status_code}"
            )
            return None

        # NOTE: For now only return first result, but in the future we can
        # do some fuzzy matching and return multiple results
        movie_id = response.json()["results"][0]["id"]
        return movie_id

    def get_movie(self, title: str) -> Movie:
        """
        Get movie information from TMDB API and return Movie object.

        Parameters
        ----------
        title : str
            Title of the movie, used to query TMDB API

        Returns
        -------
        Movie
            Movie object
        """
        movie_id = self.get_movie_id(title)
        if movie_id is None:
            return Movie(title, [])

        streaming_platforms = self.get_streaming_platforms(movie_id)
        movie = Movie(title, streaming_platforms)

        return movie


class Letterboxd:
    def __init__(self, username: str, country: str):
        """
        Letterboxd class that holds information about user and scrapper

        Parameters
        ----------
        username : str
            Letterboxd username
        country : str
            Country from which the user wants to watch movies
        """
        self.username = username
        self.scrapper = Scrapper("https://letterboxd.com")
        self.tmdb = TMDB(country)

    def get_page(self, page: int) -> str | None:
        """
        Get watchlist page from Letterboxd and return it as a string.

        Parameters
        ----------
        page : int
            Page number of watchlist

        Returns
        -------
        str | None
            Watchlist page as a string or None if there was an error
        """
        response = self.scrapper.get(f"{self.username}/watchlist/page/{page}")

        if response.status_code != HTTPStatus.OK:
            logger.error(
                f"Error while getting watchlist page {page}, status code: {response.status_code}"
            )
            return None

        return response.text

    @property
    def watchlist(self) -> list[Movie]:
        """
        Get watchlist from Letterboxd and return list of Movie objects.

        Returns
        -------
        list[Movie]
            List of Movie objects that are on user's watchlist
        """
        if _watchlist := getattr(self, "_watchlist", None):
            return _watchlist

        self._watchlist = []
        current_page = 1

        watchlist_html = self.get_page(current_page)
        if watchlist_html is None:
            return []

        soup = BeautifulSoup(watchlist_html, "html.parser")

        # Returns: 'self.username' WANTS TO SEE 'movies_count' FILMS
        movies_count = soup.find("h1", {"class": "section-heading"}).text
        movies_count = int(movies_count.split()[-2])
        num_of_pages = movies_count // (7 * 4) + 1

        with tqdm(total=(num_of_pages - 1)) as pbar:
            while current_page <= num_of_pages:
                for movie_el in soup.find_all("li", {"class": "poster-container"}):
                    # The html is not fully rendered, so we need to get the title
                    # from the img alt attribute
                    img = movie_el.find("img")
                    title = img["alt"]

                    movie = self.tmdb.get_movie(title)
                    self._watchlist.append(movie)

                current_page += 1
                pbar.update(1)
                watchlist_html = self.get_page(current_page)
                soup = BeautifulSoup(watchlist_html, "html.parser")
        return self._watchlist

    @property
    def summary(self):
        if _summary := getattr(self, "_summary", None):
            return _summary

        watchlist = self.watchlist
        self._summary = ""

        for movie in watchlist:
            self._summary += str(movie) + "\n"
            self._summary += "*" * 50 + "\n"

        platforms = [platform for movie in watchlist for platform in movie.platforms]
        counter = Counter(platforms)

        self._summary += "Platforms summary \n----------\n"
        for platform, count in counter.items():
            self._summary += f"{platform}: {count}\n"

        return self._summary


if __name__ == "__main__":
    letterboxd = Letterboxd("wombatbat", "PL")
    print(letterboxd.summary)
