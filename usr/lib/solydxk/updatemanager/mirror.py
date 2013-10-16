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
                        # http://ftp.nluug.nl/os/Linux/distr/solydxk/packages/production/dists/solydxk/kdenext/binary-amd64/Packages.gz
                        c.setopt(pycurl.URL, "%s/production/dists/solydxk/kdenext/binary-amd64/Packages.gz" % mirror)
                    else:
                        c.setopt(pycurl.URL, "%s/production/README.mirrors.html" % mirror)

                    c.setopt(pycurl.CONNECTTIMEOUT, 10)
                    c.setopt(pycurl.TIMEOUT, 10)
                    c.setopt(pycurl.FOLLOWLOCATION, 1)
                    c.setopt(pycurl.WRITEFUNCTION, buff.write)
                    # Workaround for bug: http://sourceforge.net/p/pycurl/bugs/23/
                    c.setopt(pycurl.NOSIGNAL, 1)

                    curlErr = False
                    try:
                        c.perform()
                    except pycurl.error,error:
                        curlErr = True
                        errno, errstr = error
                        choices.append([mirror,errstr])
                        self.log.write(errstr, "MirrorGetSpeed.run", "error")
                        continue

                    if not curlErr:
                        return_code = c.getinfo(pycurl.HTTP_CODE)
                        download_speed = c.getinfo(pycurl.SPEED_DOWNLOAD)
                        if (return_code == 200):
                            download_speed = int(round(download_speed/1000))
                            choices.append([mirror,download_speed])
                            msg = "Server %(mirror)s - %(speed)dKbps" % { "mirror": mirror, "speed": download_speed }
                            self.log.write(msg, "MirrorGetSpeed.run", "debug")
                        else:
                            choices.append([mirror,"Error: %d" % return_code])
                            msg = _("Server %(mirror)s returns HTTP code %(return_code)d") % { "mirror": mirror, "return_code": return_code }
                            self.log.write(msg, "MirrorGetSpeed.run", "warning")

            self.queue.put(choices)
            self.queue.task_done()

        except Exception, detail:
            # This is a best-effort attempt, fail graciously
            self.log.write(str(detail), "MirrorGetSpeed.run", "exception")
            self.queue.put(choices)
            self.queue.task_done()


class Mirror():
    def __init__(self, log=None):
        self.log = log
        self.ec = ExecCmd()

    def save(self, replaceRepos, excludeStrings=[]):
        try:
            src = '/etc/apt/sources.list'
            if os.path.exists(src):
                dt = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                msg = "Backup %(src)s to %(src)s.%(date)s" % { "src": src, "src": src, "date": dt }
                self.log.write(msg, "Mirror.save", "debug")
                os.system("cp -f %s %s.%s" % (src, src, dt))

                new_repos = []
                cmd = "cat %s" % src
                lstOut = self.ec.run(cmd, False)
                for line in lstOut:
                    line = str(unicode(line.strip(), 'ascii', 'ignore'))
                    if not line.startswith('#'):
                        for repo in replaceRepos:
                            if repo[0] in line:
                                skip = False
                                for excl in excludeStrings:
                                    if excl in line:
                                        skip = True
                                        break
                                if not skip:
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
            self.log.write(str(detail), "Mirror.save", "exception")
