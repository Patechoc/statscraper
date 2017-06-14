# encoding: utf-8
import requests
from bs4 import BeautifulSoup

from statscraper.base_scraper import (BaseScraper, Collection,
                                      Dataset, Dimension, InvalidData)

VERSION = "1.0"
LEVELS = ["api","parameter"]

class SMHIScraper(BaseScraper):
    base_url = "http://opendata.smhi.se/apidocs/"


    def _fetch_itemslist(self):
        """ Get a all available apis
        """
        if self.current_item.is_root:
            html = requests.get(self.base_url).text
            soup = BeautifulSoup(html, 'html.parser')
            for item_html in soup.select(".row .col-md-6"):
                try:
                    label = item_html.select_one("h2").text
                except:
                    continue
                yield API(label, html_blob=item_html)
        else:
            parameter = self._collection_path[0]

            data = requests.get(parameter.url)
            for resource in self.current_item.blob["resource"]:
                label = u"{}, {}".format(resource["title"], resource["summary"])
                yield Dataset(label, blob=resource)



    def _fetch_dimensions(self):
        parameter = self.current_item
        import pdb;pdb.set_trace()
        self._collection_path[0]
        import pdb;pdb.set_trace()
        self.url = "http://opendata-download-{}.smhi.se/api/version/{}/parameter/{}.json"\
            .format(parameter.key, VERSION, )
        yield("Timepoint")

class API(Collection):
    level = "api"

    def __init__(self, _id, html_blob=None):
        self.id = _id
        self.key = html_blob.select_one("a").get("href").replace("/index.html","")
        self.url = "http://opendata-download-{}.smhi.se/api/version/{}.json"\
            .format(self.key, VERSION)

    @property
    def blob(self):
        return self._get_json_blob()

    def _get_json_blob(self):
        # Update blob
        error_msg = "Scraper does not support parsing of '{}' yet.".format(self.id)
        try:
            r = requests.get(self.url)
        except:
            # Catch ie. "opendata-download-grid.smhi.se"
            raise NotImplementedError(error_msg)
        if r.status_code == 404:
            raise NotImplementedError(error_msg)

        return r.json()



class Parameter(Collection):
    level = "parameter"

