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

import tornado.web
import tornado.ioloop
import tornado.options
import pymongo
import bson.objectid
import bson.json_util

from tornado.web import RequestHandler, StaticFileHandler
from tornado.options import define, options

define('port', default=8888)


homepage = """<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>FOI Torrents</title>
<style>
@import url(http://fonts.googleapis.com/css?family=Open+Sans:400,700);
body {{
    font-family: 'Open Sans', sans-serif;
}}

#container {{
    margin: 0 auto;
    max-width: 800px;
}}

pre {{
    word-wrap: break-word;
}}
</style>
</head>
<body>
<div id='container'>

<h1>foitorrent</h1>

<p>Welcome to my little experiment in scraping FOI requests from government departments and providing them as .torrent files.</p>

<p style='color: red'>Don't bother seeding these example torrents, as they're proof-of-concept and will be regenerated slightly differently sometime this week.</p>

<p>Feel free of course to try downloading any of them to see if they work. (They do!)</p>

<h2>{heading}</h2>

{content}

</div>
<hr>
<div style='text-align: center'>
<a style='text-decoration: none; color: #0073ae' href="http://brendan.so/about">:)</a>
</div>
</body>
</html>"""

db = pymongo.Connection().foitorrent

class HomePageHandler(RequestHandler):
    def get(self):
        self.write(homepage.format(heading="Departments", content="""
<ul>
<li><a href="/d/agd">Attorney-General's Department</a></li>
<li><a href="/d/dfat">Department of Foreign Affairs and Trade</a></li>
<li><a href="/d/defence">Department of Defence</a></li>
</ul>"""))

class DeptHandler(RequestHandler):
    def get(self, org):
        reqs = db.requests.find({"organisation": org})
        urls = []
        for req in reqs:
            urls.append("<li><a href='/r/%s'>%s</a></li>" % (str(req['_id']), req['title']))
        self.write(homepage.format(heading=org, content="<ul>%s</ul>" % "\n".join(urls)))

class ReqHandler(RequestHandler):
    def get(self, req):
        req = db.requests.find_one({"_id": bson.objectid.ObjectId(req)})
        if req is None:
            self.write("No req found.")
            return

        self.write(homepage.format(heading=req['title'], content="""
        <p><a href="/t/{torrent}">Download Torrent</a></p>

        <pre>{json_data}</pre>
        """.format(torrent=req['torrent'], json_data=bson.json_util.dumps(req, indent=2))))


if __name__ == "__main__":
    tornado.options.parse_command_line()
    application = tornado.web.Application([
        (r'/', HomePageHandler),
        (r'/d/(.*)', DeptHandler),
        (r'/r/(.*)', ReqHandler),
        (r'/t/(.*)', StaticFileHandler, {"path": "torrents"})
    ])

    application.listen(options.port, xheaders=True)
    tornado.ioloop.IOLoop.instance().start()
