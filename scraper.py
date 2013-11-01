"""
This file is part of foitorrent.
Copyright (c) 2013  Brendan Molloy

foitorrent is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

foitorrent is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with foitorrent.  If not, see <http://www.gnu.org/licenses/>.
"""

import requests
import pymongo
import datetime
import os
import os.path
import lxml.html
import hashlib
import re
import logging
import tornado.log
import string
import urllib.parse
import subprocess

logger = logging.getLogger()
ch = logging.StreamHandler()
ch.setFormatter(tornado.log.LogFormatter())
logger.addHandler(ch)
logger.setLevel(logging.INFO)


class Scraper:
    def __init__(self):
        self.db = pymongo.Connection().foitorrent
        self.session = requests.Session()
        self.config = {
            'path': 'requests',
            'torrent_path': 'torrents',
            'torrent_cmd': ['./mktorrent',
                '-a', 'udp://tracker.publicbt.com:80/announce',
                '-a', 'udp://tracker.openbittorrent.com:80/announce']
        }

    def download_page(self, url):
        return lxml.html.fromstring(re.sub('Â?\u00a0', ' ', self.session.get(url).text))

    def generate_torrent(self, directory, fn):
        fn = self.sanitise_torrent_name(fn)
        torrent_fn = os.path.join(self.config['torrent_path'], fn)
        cmd = self.config['torrent_cmd'] + [
                '-o', torrent_fn,
                '-c', "Torrent retrieved from foitorrent: http://foitorrent.brendan.so",
                directory
        ]
        ret = subprocess.call(cmd)
        if ret == 0:
            return torrent_fn
        return None

    def seed_torrent(self, torrent_path, files_path):
        # TODO: put torrents in saner places, flat is not sustainable
        subprocess.call(['transmission-remote', '-w', os.path.split(files_path)[0], '-a', torrent_path])

    def generate_request_path(self, o):
        return os.path.join(
                self.config['path'],
                o['organisation'],
                o['date_released'].strftime("%Y"),
                o['date_released'].strftime("%m"),
                re.sub("[" + string.punctuation + r"\s’‘]", '_', o['title'])
            )

    def download_documents(self, path, documents):
        if len(documents) == 0:
            return

        for meta in documents:
            fname = meta['filename']
            os.makedirs(path, exist_ok=True)

            logger.info("Downloading '%s'..." % meta['original_url'])
            document = requests.get(meta['original_url']).content
            meta['size'] = len(document)

            m = hashlib.sha256()
            m.update(document)
            meta['sha256'] = m.hexdigest()

            with open(os.path.join(path, fname), 'wb') as f:
                f.write(document)

            logger.info("Downloaded: '%s' :: SHA256: %s" % (
                        os.path.join(path, fname), meta['sha256']))


    def sanitise_torrent_name(self, fn):
        return re.sub(r'[/@:\\]', '_', fn)

    def get_start_page(self):
        raise NotImplementedError

    def find_new_documents(self, page):
        raise NotImplementedError

    def scrape_request(self, url, node=None):
        if node is None:
            node = self.download_page(url)
        o = self.generate_metadata(url, node)

        if o is None:
            logger.error("Skipping request due to errors!")
            return

        fpath = self.generate_request_path(o)
        self.download_documents(fpath, o['documents'])

        if len(o['documents']) == 0:
            logger.error('No documents found for this request! Skipping.')
            return

        tname = o['title'] + '.torrent'
        torrent_path = self.generate_torrent(fpath, tname)
        if torrent_path is None:
            logger.error("Torrent path is null! Skipping.")
            return
        o['torrent'] = tname
        logger.info("Generated torrent: '%s'" % torrent_path)

        try:
            self.seed_torrent(torrent_path, fpath)
        except FileNotFoundError as e:
            logger.warn(e)

        self.db.requests.insert(o)


    def scrape(self):
        logging.info("Getting start page...")
        page = self.get_start_page()

        logging.info("Finding new documents...")
        new_docs = self.find_new_documents(page)

        logging.debug("New docs: %r" % new_docs)

        total = len(new_docs)
        for n, o in enumerate(new_docs):
            logging.info("[%s/%s] Scraping: %s" % (n+1, total, o['title']))
            self.scrape_request(o.get('url'), o.get('node'))


class AGDScraper(Scraper):
    BASE_URL = "http://www.ag.gov.au"

    def get_start_page(self):
        url = "http://www.ag.gov.au/RightsAndProtections/FOI/Pages/Freedomofinformationdisclosurelog.aspx"
        if self.find_missing:
            url += "?lsf=date&lso=0"
        return self.download_page(url)

    def is_anchor_new(self, a):
        x = self.db.requests.find_one({
            "organisation": "agd",
            "title": a.attrib['title'].strip()})
        return x is None

    def find_new_documents(self, page):
        selector = ".disclosure-log-list .dl-item-title a"
        next_page_selector = ".paging-next a"
        
        urls = []
        while True:
            anchors = page.cssselect(selector)

            for a in anchors:
                if self.is_anchor_new(a):
                    logging.debug("Adding URL: %s" % a.attrib['href'])
                    urls.append({"url": a.attrib['href'], "title": a.text_content()})
                elif self.find_missing:
                    pass # stops the immediate ending
                else:
                    return urls

            next_page = page.cssselect(next_page_selector)
            if len(next_page) == 0:
                logging.debug("No next page. Done.")
                return urls

            page = self.download_page(next_page[0].attrib['href'])
            logging.debug("Next page downloaded.")

    def parse_date_string(self, ds):
        return datetime.datetime.strptime(ds, "%A, %d %B %Y")

    def parse_agd_doc_url(self, url):
        x = urllib.parse.urlparse(url)
        if x.path.endswith("WordViewer.aspx"):
            new_path = urllib.parse.parse_qs(x.query)['id'][0]
            if new_path.startswith('/'):
                return self.BASE_URL + new_path
            else:
                return new_path

        return url

    def generate_metadata(self, url, node):
        sel_title = ".wc-title h1"
        sel_release_date = ".dl-date .dl-value"
        sel_description = ".dl-abstract .dl-value"
        sel_document_urls = ".dl-downloads a"

        o = {
            "organisation": "agd",
            "title": node.cssselect(sel_title)[0].text_content().strip(),
            "description": node.cssselect(sel_description)[0].text_content().strip(),
            "date_released": self.parse_date_string(
                node.cssselect(sel_release_date)[0].text_content().strip()),
            "date_retrieved": datetime.datetime.utcnow(),
            "original_url": url,
            "documents": []
        }

        for a in node.cssselect(sel_document_urls):
            if a.attrib.get('href') is None:
                logger.error("Invalid anchor: '%s'" % lxml.html.tostring(a).decode())
                return

            if a.attrib['href'].startswith("mailto"):
                logger.error("Invalid anchor: '%s'" % lxml.html.tostring(a).decode())
                return

            parsed_url = self.parse_agd_doc_url(self.BASE_URL + a.attrib['href'])

            meta = {
                "original_url": parsed_url,
                "title": a.text_content().strip()
            }

            fname = urllib.parse.unquote(meta['original_url'].rsplit('/', 1)[-1])
            meta['filename'] = fname

            o['documents'].append(meta)

        return o

    def scrape(self, find_missing=True):
        self.find_missing = find_missing
        super().scrape()


class DFATScraper(Scraper):
    def get_start_page(self):
        return self.download_page("http://www.dfat.gov.au/foi/disclosure-log.html")

    def parse_date_string(self, ds):
        return datetime.datetime.strptime(ds, "%d %B %Y")

    def find_new_documents(self, page):
        selector = "#requests tbody tr"

        rows = page.cssselect(selector)
        new_rows = []

        for row in rows:
            if len(row.cssselect('td')) != 5:
                continue

            foi_ref = row[0].text_content().strip()
            if self.db.requests.find_one({"title": foi_ref}) is not None:
                continue

            new_rows.append({
                "url": "http://www.dfat.gov.au/foi/disclosure-log.html",
                "node": row,
                "title": foi_ref
            })

        return new_rows

    def generate_metadata(self, url, node):
        foi_ref = node[0].text_content().strip()

        o = {
            "organisation": "dfat",
            "title": foi_ref,
            "reference": foi_ref,
            "description": lxml.html.tostring(node[2]).decode().strip(),
            "date_released": self.parse_date_string(node[1].text_content().strip()),
            "date_retrieved": datetime.datetime.utcnow(),
            "original_url": url,
            "documents": []
        }

        anchors = node[3].cssselect('a')

        for a in anchors:
            if a.attrib.get('href') is None:
                logger.error("Invalid anchor: '%s'" % lxml.html.tostring(a).decode())
                return

            if a.attrib['href'].startswith("mailto"):
                logger.error("Invalid anchor: '%s'" % lxml.html.tostring(a).decode())
                return

            parsed_url = "http://www.dfat.gov.au" + a.attrib['href']

            meta = {
                "original_url": parsed_url,
                "title": a.text_content().strip()
            }

            fname = urllib.parse.unquote(meta['original_url'].rsplit('/', 1)[-1])
            meta['filename'] = fname

            o['documents'].append(meta)

        return o


class DefenceScraper(Scraper):
    DIR = "/foi"
    HOST = "http://www.defence.gov.au"

    def get_start_page(self):
        return self.download_page("http://www.defence.gov.au/foi/disclosure_log.htm")

    def find_new_documents(self, page):
        selector = ".homeBtn a"
        table = "#table tbody tr"

        new_docs = []
        for a in page.cssselect(selector):
            url = self.parse_document_url(a.attrib['href'])
            subpage = self.download_page(url)

            for tr in subpage.cssselect(table):
                foi_ref = tr[1].text_content().strip()

                if self.db.requests.find_one({"reference": foi_ref}) is not None:
                    continue

                new_docs.append({"url": url, "node": tr, "title": tr.cssselect(".foiTitle")[0].text_content()})

        return new_docs

    def parse_date_string(self, ds):
        last_ex = None
        for df in ["%d-%b-%y", "%d-%B-%y", "%d-%b-%Y", "%d-%B-%Y"]:
            try:
                return datetime.datetime.strptime(ds, df)
            except Exception as e:
                last_ex = e
        raise last_ex

    def parse_document_url(self, url):
        if url.startswith("http"):
            return url
        elif url.startswith('/'):
            return self.HOST + url
        return self.HOST + self.DIR + "/" + url

    def generate_metadata(self, url, node):
        foi_ref = node[1].text_content().strip()

        o = {
            "organisation": "defence",
            "title": node.cssselect(".foiTitle")[0].text_content().strip(),
            "reference": foi_ref,
            "access": node[3].text_content().strip(),
            "exemptions": node[4].text_content().strip(),
            "date_released": self.parse_date_string(node[0].text_content().split(' ')[0].strip()),
            "date_retrieved": datetime.datetime.utcnow(),
            "original_url": url,
            "documents": []
        }

        anchors = node[2].cssselect('a')

        for a in anchors:
            if a.attrib.get('href') is None:
                logger.error("Invalid anchor: '%s'" % lxml.html.tostring(a).decode())
                return

            if a.attrib['href'].startswith("mailto"):
                logger.error("Invalid anchor: '%s'" % lxml.html.tostring(a).decode())
                return

            parsed_url = self.parse_document_url(a.attrib['href'])

            meta = {
                "original_url": parsed_url,
                "title": a.text_content().strip()
            }

            fname = urllib.parse.unquote(meta['original_url'].rsplit('/', 1)[-1])
            meta['filename'] = fname

            o['documents'].append(meta)

        return o




scrapers = {
    "agd": AGDScraper,
    "dfat": DFATScraper,
    "defence": DefenceScraper
}

if __name__ == "__main__":
    #TODO add argparse
    import sys
    x = scrapers[sys.argv[1]]()
    x.scrape()
