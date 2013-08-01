#!/usr/bin/env python

import os
import pycurl
import cStringIO
import threading
import datetime
from execcmd import ExecCmd


class MirrorGetSpeed(threading.Thread):
    def __init__(self, mirrors, queue, log=None):
        threading.Thread.__init__(self)
        self.log = log
        self.mirrors = mirrors
        self.queue = queue

    def run(self):
        choices = []
        try:
            for mirrorData in self.mirrors:
                mirror = str(unicode(mirrorData[3], 'ascii', 'ignore'))
                if ("http" in mirror or "ftp" in mirror):
                    if mirror.endswith('/'):
                        mirror = mirror[:-1]
                    c = pycurl.Curl()
                    buff = cStringIO.StringIO()
                    if mirrorData[2].lower() == 'solydxk':
                        c.setopt(pycurl.URL, "%s/.speedtest" % mirror)
                    else:
                        c.setopt(pycurl.URL, "%s/README.mirrors.html" % mirror)
                    c.setopt(pycurl.CONNECTTIMEOUT, 10)
                    c.setopt(pycurl.TIMEOUT, 10)
                    c.setopt(pycurl.FOLLOWLOCATION, 1)
                    c.setopt(pycurl.WRITEFUNCTION, buff.write)
                    try:
                        c.perform()
                    except pycurl.error,error:
                        errno, errstr = error
                        msg = "++ MirrorGetSpeed Error: %s" % errstr
                        self.log.writelines("%s\n" % msg)
                        self.log.flush()
                        print msg
                        continue
                    return_code = c.getinfo(pycurl.HTTP_CODE)
                    download_speed = c.getinfo(pycurl.SPEED_DOWNLOAD)
                    if (return_code == 200):
                        download_speed = int(round(download_speed/1000))
                        choices.append([mirror,download_speed])
                        msg = "++ MirrorGetSpeed: Server %s - %dKbps" % (mirror, download_speed)
                        self.log.writelines("%s\n" % msg)
                        self.log.flush()
                        print msg
                    else:
                        msg = "++ MirrorGetSpeed: Warning %s returns HTTP code %d" % (mirror, return_code)
                        self.log.writelines("%s\n" % msg)
                        self.log.flush()
                        print msg

            self.queue.put(choices)
            self.queue.task_done()

        except Exception, detail:
            # This is a best-effort attempt, fail graciously
            msg = "MirrorGetSpeed exception: %s" % detail
            self.log.writelines("%s\n" % msg)
            self.log.flush()
            print msg


class Mirror():
    def __init__(self, log=None):
        self.log = log
        self.ec = ExecCmd()

    def save(self, replaceRepos):
        try:
            src = '/etc/apt/sources.list'
            if os.path.exists(src):
                dt = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                msg = "Backup %s to %s.%s" % (src, src, dt)
                self.log.writelines("%s\n" % msg)
                self.log.flush()
                print msg
                os.system("cp -f %s %s.%s" % (src, src, dt))

                new_repos = []
                cmd = "cat %s" % src
                lstOut = self.ec.run(cmd, False)
                for line in lstOut:
                    line = str(unicode(line.strip(), 'ascii', 'ignore'))
                    if not line.startswith('#'):
                        for repo in replaceRepos:
                            if repo[0] in line:
                                line = line.replace(repo[0], repo[1])
                    new_repos.append(line)

                if new_repos:
                    f = open(src, 'w')
                    for repo in new_repos:
                        f.write("%s\n" % repo)
                        #print "%s\n" % repo
                    f.close()

        except Exception, detail:
            # This is a best-effort attempt, fail graciously
            msg = "Mirror exception: %s" % detail
            self.log.writelines("%s\n" % msg)
            self.log.flush()
            print msg
