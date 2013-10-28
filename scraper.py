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

def download_page(url):
    return lxml.html.fromstring(re.sub('Â?\u00a0', ' ', requests.get(url).text))

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
        subprocess.call(['transmission-remote', '-w', os.path.split(files_path)[0], '-a', torrent_path])

    def sanitise_torrent_name(self, fn):
        return re.sub(r'[/@:\\]', '_', fn)

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

            # TODO: put torrents in saner places, flat is not sustainable
            with open(os.path.join(fpath, fname), 'wb') as f:
                f.write(document)
            logger.info("Downloaded: '%s' :: SHA256: %s" % (os.path.join(fpath, fname), meta['sha256']))
        
        if len(o['documents']) == 0:
            logger.warn('No documents found for this request!')
        
        tname = self.sanitise_torrent_name(o['title']) + ".torrent"
        torrent_path = self.generate_torrent(fpath, tname)
        if torrent_path is None:
            logger.error("Torrent path is null! Skipping.")
            return

        logger.info("Generated torrent: '%s'" % tname)
        self.seed_torrent(torrent_path, fpath)
        
        o['torrent'] = tname
        self.db.requests.insert(o)

    def scrape(self, find_missing=False):
        self.find_missing = find_missing
        super().scrape()


class DFATScraper(Scraper):
    def get_start_page(self):
        return download_page("http://www.dfat.gov.au/foi/disclosure-log.html")

    def parse_date_string(self, ds):
        return datetime.datetime.strptime(ds, "%d %B %Y")

    def find_new_documents(self, page):
        selector = "#requests tr"
        
        new_rows = []
        rows = page.cssselect(selector)
        new_rows = []
        for row in rows:
            cells = row.cssselect('td')
            if len(cells) != 5:
                continue
            foi_ref = cells[0].text_content().strip()
            if self.db.requests.find_one({"title": foi_ref}) is not None:
                continue
            new_rows.append(row)

        total = len(new_rows)
        for n, row in enumerate(new_rows):
            foi_ref = cells[0].text_content().strip()
            logging.info("[%s/%s] Scraping: %s" % (n+1, total, foi_ref))
            
            cells = row.cssselect('td')
            o = {
                "organisation": "DFAT",
                "title": foi_ref,
                "description": lxml.html.tostring(cells[2]).decode().strip(),
                "date_released": self.parse_date_string(cells[1].text_content().strip()),
                "date_retrieved": datetime.datetime.utcnow(),
                "original_url": "http://www.dfat.gov.au/foi/disclosure-log.html",
                "documents": []
            }

            anchors = cells[3].cssselect('a')

            for a in anchors:
                if a.attrib.get('href') is None:
                    logger.error("Invalid anchor: '%s'" % lxml.html.tostring(a).decode())
                    logger.error("Skipping request due to errors!")
                    return
    
                if a.attrib['href'].startswith("mailto"):
                    continue
                
                parsed_url = "http://www.dfat.gov.au" + a.attrib['href']
                
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
            
            tname = self.sanitise_torrent_name(o['title']) + ".torrent"
            torrent_path = self.generate_torrent(fpath, tname)
            if torrent_path is None:
                logger.error("Torrent path is null! Skipping.")
                continue
    
            logger.info("Generated torrent: '%s'" % tname)
            #self.seed_torrent(torrent_path, fpath)
            
            o['torrent'] = tname
            self.db.requests.insert(o)

    
    def scrape(self):
        logging.info("Getting start page...")
        page = self.get_start_page()
        logging.info("Finding new documents...")
        new_docs = self.find_new_documents(page)



scrapers = {
    "agd": AGDScraper,
    "dfat": DFATScraper
}

if __name__ == "__main__":
    #TODO add argparse
    import sys
    x = scrapers[sys.argv[1]]()
    x.scrape()
