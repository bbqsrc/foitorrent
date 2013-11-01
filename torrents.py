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

from subprocess import call

class Torrent:
    def __init__(self, torrent):
        self.torrent = torrent

    @property
    def name(self):
        raise NotImplementedError

    @property
    def hash(self):
        raise NotImplementedError

    @property
    def status(self):
        raise NotImplementedError

    @property
    def seeders(self):
        raise NotImplementedError

    @property
    def leechers(self):
        raise NotImplementedError


class BitTorrentClient:
    def __init__(self):
        pass

    def create_torrent(self, outfile, path, trackers=[], comment=None, private=False):
        raise NotImplementedError

    def add_torrent(self, path):
        raise NotImplementedError

    def remove_torrent(self, torrent):
        raise NotImplementedError

    def get_torrent(self, id):
        raise NotImplementedError


class TransmissionTorrent(Torrent):
    def name(self):
        return self.torrent.name

    def hash(self):
        return self.torrent.hashString

    def status(self):
        return self.torrent.status

    def seeders(self):
        return self.torrent.seeders

    def leechers(self):
        return self.torrent.leechers

    def downloads(self):
        return self.torrent.timesCompleted


class TransmissionClient(BitTorrentClient):
    def __init__(self):
        import transmissionrpc
        self.client = transmissionrpc.Client()

    def _get_id(self, dct):
        for k, v in dct.items():
            return k

    def _get_torrent(self, dct):
        for k, v in dct.items():
            return v

    def create_torrent(self, outfile, path, trackers=[], comment=None, private=False):
        args = ['transmission-create', '-o', outfile]
        for tracker in trackers:
            args += ['-t', tracker]
        if comment is not None:
            args += ['-c', comment]
        if private is True:
            args.append('-p')
        args.append(path)
        call(args)
        return outfile

    def add_torrent(self, path):
        torrent = self._get_torrent(self.client.add_torrent(path))
        return TransmissionTorrent(torrent)

    def remove_torrent(self, torrent):
        self.client.remove_torrent(torrent.hash)

    def get_torrent(self, id):
        torrent = self._get_torrent(self.client.get_torrent(id))
        return TransmissionTorrent(torrent)
