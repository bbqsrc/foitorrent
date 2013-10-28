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
</style>
</head>
<body>
<h1>foitorrent</h1>

<p>Welcome to my little experiment in scraping FOI requests from government departments and providing them as .torrent files.</p>

<h2>{heading}</h2>

{content}

</body>
</html>"""

db = pymongo.Connection().foitorrent

class HomePageHandler(RequestHandler):
    def get(self):
        self.write(homepage.format(heading="Departments", content="""
<ul>
<li><a href="/d/agd">Attorney-General's Department</a></li>
</ul>"""))

class DeptHandler(RequestHandler):
    def get(self, org):
        reqs = db.requests.find({"organisation": org})
        urls = []
        for r in reqs:
            urls.append("<li><a href='/r/%s'>%s</a></li>" % (str(reqs['_id']), reqs['title']))
        self.write(homepage.format(heading=org, "<ul>%s</ul>" % "\n".join(urls)))

class ReqHandler(RequestHandler):
    def get(self, req):
        req = db.requests.find_one({"_id": bson.objectid.ObjectId(req)})
        if req is None:
            self.write("No req found.")
            return

        self.write(homepage.format(heading=req['title'], content="""
        <p><a href="/t/{torrent}">Download Torrent</a></p>

        <pre>{json_data}</pre>
        """.format(torrent=req['torrent'], json_data=bson.json_util.dumps(req, indent=2)))


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
