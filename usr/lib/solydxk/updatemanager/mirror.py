#! /usr/bin/env python3
#-*- coding: utf-8 -*-

# Depends: curl

import os
import threading
import datetime
from execcmd import ExecCmd


class MirrorGetSpeed(threading.Thread):
    def __init__(self, mirrors, queue, umglobal):
        threading.Thread.__init__(self)
        self.ec = ExecCmd()
        self.umglobal = umglobal
        self.mirrors = mirrors
        self.queue = queue

    def run(self):
        try:
            for mirrorData in self.mirrors:
                mirror = mirrorData[3].strip()
                if ("http" in mirror or "ftp" in mirror):
                    if mirror.endswith('/'):
                        mirror = mirror[:-1]

                    if mirrorData[2].lower() == 'solydxk':
                        url = "%s/%s" % (mirror, self.umglobal.settings["dl-test-solydxk"])
                    else:
                        url = "%s/%s" % (mirror, self.umglobal.settings["dl-test"])

                    cmd = "curl --connect-timeout %d -m %d -w '%%{http_code}\n%%{speed_download}\n' -o /dev/null -s %s" % (int(self.umglobal.settings["timeout-secs"] / 2), self.umglobal.settings["timeout-secs"], url)

                    lst = self.ec.run(cmd, False)
                    if lst:
                        httpCode = int(lst[0])
                        dlSpeed = lst[1]
                        # Download speed returns as string with decimal separator
                        # On non-US systems converting to float throws an error
                        # Split on the separator, and use the left part only
                        if ',' in dlSpeed:
                            dlSpeed = dlSpeed.split(',')[0]
                        elif '.' in dlSpeed:
                            dlSpeed = dlSpeed.split('.')[0]
                        if (httpCode == 200):
                            dlSpeed = int(dlSpeed) / 1000
                            self.queue.put([mirror, "%d Kb/s" % dlSpeed])
                            self.queue.task_done()
                            print(("Server %(mirror)s - %(speed)d Kb/s" % { "mirror": mirror, "speed": dlSpeed }))
                        else:
                            self.queue.put([mirror,"Error: %d" % httpCode])
                            self.queue.task_done()
                            print(("Server %(mirror)s returns HTTP code %(return_code)d" % { "mirror": mirror, "return_code": httpCode }))

        except Exception as detail:
            # This is a best-effort attempt, fail graciously
            print(("Error: %s" % str(detail)))


class Mirror():
    def __init__(self):
        self.ec = ExecCmd()

    def save(self, replaceRepos, excludeStrings=[]):
        try:
            src = '/etc/apt/sources.list'
            if os.path.exists(src):
                new_repos = []
                srcList = []
                with open(src, 'r') as f:
                    srcList = f.readlines()
                for line in srcList:
                    line = line.strip()
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
                    # Backup the current sources.list
                    dt = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                    print(("Backup %(src)s to %(src)s.%(date)s" % { "src": src, "src": src, "date": dt }))
                    os.system("cp -f %s %s.%s" % (src, src, dt))
                    # Save the new sources.list
                    with open(src, 'w') as f:
                        for repo in new_repos:
                            f.write("%s\n" % repo)

            return True

        except Exception as detail:
            # This is a best-effort attempt, fail graciously
            print(("Error: %s" % str(detail)))
            return False
