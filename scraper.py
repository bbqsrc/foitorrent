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

def download_page(url):
    return lxml.html.fromstring(requests.get(url).text)

class Scraper:
    def __init__(self):
        self.db = pymongo.Connection().foitorrent
        self.config = {
            'path': 'requests',
            'torrent_path': 'torrents',
            'torrent_cmd': ['./mktorrent',
                '-a', 'udp://tracker.publicbt.com:80/announce',
                '-a', 'udp://tracker.openbittorrent.com:80/announce']

        }

    def generate_torrent(self, directory, fn):
        torrent_fn = os.path.join(self.config['torrent_path'], fn)
        cmd = self.config['torrent_cmd'] + ['-o', torrent_fn, directory]
        ret = subprocess.call(cmd)
        if ret == 0:
            return torrent_fn
        return None

    def get_start_page(self):
        pass

    def find_new_documents(self, page):
        pass

    def scrape_new_documents(self, url):
        pass

    def scrape(self):
        logging.info("Getting start page...")
        page = self.get_start_page()
        logging.info("Finding new documents...")
        new_docs = self.find_new_documents(page)
        logging.debug("New docs: %r" % new_docs)

        total = len(new_docs)
        for n, url in enumerate(new_docs):
            logging.info("[%s/%s] Scraping: %s" % (n+1, total, url))
            self.scrape_document(url)


class AGDScraper(Scraper):
    BASE_URL = "http://www.ag.gov.au"

    def get_start_page(self):
        url = "http://www.ag.gov.au/RightsAndProtections/FOI/Pages/Freedomofinformationdisclosurelog.aspx"
        if self.find_missing:
            url += "?lsf=date&lso=0"
        return download_page(url)

    def is_anchor_new(self, a):
        x = self.db.requests.find_one({
            "organisation": "AGD",
            "title": a.attrib['title'].strip()})
        
        #logging.debug("'%s' not in DB? %s" % (a.attrib['href'], x is None))

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
                    urls.append(a.attrib['href'])
                elif self.find_missing:
                    pass # stops the immediate ending
                else:
                    return urls

            next_page = page.cssselect(next_page_selector)
            if len(next_page) == 0:
                logging.debug("No next page. Done.")
                return urls

            page = download_page(next_page[0].attrib['href'])
            logging.debug("Next page downloaded.")

    def parse_date_string(self, ds):
        return datetime.datetime.strptime(ds, "%A, %d %B %Y")

    def parse_agd_doc_url(self, url):
        x = urllib.parse.urlparse(url)
        if x.path.endswith("WordViewer.aspx"):
            new_path = urllib.parse.parse_qs(x.query)['id']
            if new_path.startswith('/'):
                return self.BASE_URL + new_path
            else:
                return new_path

        return url

    def scrape_document(self, url):
        page = download_page(url)
        sel_title = ".wc-title h1"
        sel_release_date = ".dl-date .dl-value"
        sel_description = ".dl-abstract .dl-value"
        sel_document_urls = ".dl-downloads a"

        o = {
            "organisation": "AGD",
            "title": page.cssselect(sel_title)[0].text_content().strip(),
            "description": page.cssselect(sel_description)[0].text_content().strip(),
            "date_released": self.parse_date_string(
                page.cssselect(sel_release_date)[0].text_content().strip()),
            "date_retrieved": datetime.datetime.utcnow(),
            "original_url": url,
            "documents": []
        }

        for a in page.cssselect(sel_document_urls):
            if a.attrib.get('href') is None:
                logger.error("Invalid anchor: '%s'" % lxml.html.tostring(a).decode())
                logger.error("Skipping request due to errors!")
                return

            if a.attrib['href'].startswith("mailto"):
                continue

            parsed_url = self.parse_agd_doc_url(self.BASE_URL + a.attrib['href'])

            meta = {
                "original_url": parsed_url,
                "title": a.text_content().strip()
            }

            logger.info("Downloading '%s'..." % meta['original_url'])
            document = requests.get(meta['original_url']).content
            meta['size'] = len(document)

            m = hashlib.sha256()
            m.update(document)
            meta['sha256'] = m.hexdigest()
            
            o['documents'].append(meta)
        
        fpath = os.path.join(
                self.config['path'],
                o['organisation'],
                o['date_released'].strftime("%Y"),
                o['date_released'].strftime("%m"),
                re.sub("[" + string.punctuation + r"\s’‘]", '_', o['title'])
        )
        
        for meta in o['documents']:
            fname = urllib.parse.unquote(meta['original_url'].rsplit('/', 1)[-1])
            meta['filename'] = fname

            os.makedirs(fpath, exist_ok=True)

            with open(os.path.join(fpath, fname), 'wb') as f:
                f.write(document)
            logger.info("Downloaded: '%s' :: SHA256: %s" % (os.path.join(fpath, fname), meta['sha256']))
        
        if len(o['documents']) == 0:
            logger.warn('No documents found for this request!')
        
        torrent_path = self.generate_torrent(fpath, o['title'] + ".torrent")
        if torrent_path is None:
            logger.error("Torrent path is null! Skipping.")
            return

        logger.info("Generated torrent: '%s'" % torrent_path)
        
        o['torrent'] = torrent_path
        self.db.requests.insert(o)

    def scrape(self, find_missing=False):
        self.find_missing = find_missing
        super().scrape()

if __name__ == "__main__":
    #TODO add argparse
    x = AGDScraper()
    x.scrape(True)
