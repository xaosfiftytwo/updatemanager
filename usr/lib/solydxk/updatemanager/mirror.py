#! /usr/bin/env python3

# Depends: curl

import os
import threading
import datetime
import re
from execcmd import ExecCmd


class MirrorGetSpeed(threading.Thread):
    def __init__(self, mirrors, queue, umglobal):
        threading.Thread.__init__(self)
        self.ec = ExecCmd()
        self.umglobal = umglobal
        self.mirrors = mirrors
        self.queue = queue

    def run(self):
        httpCode = -1
        dlSpeed = 0
        for mirrorData in self.mirrors:
            try:
                mirror = mirrorData[3].strip()
                if mirror == "URL":
                    continue
                if mirror.endswith('/'):
                    mirror = mirror[:-1]

                # Only check Debian repository: SolydXK is on the same server
                httpCode = -1
                dlSpeed = 0
                dl_file = "umfiles/speedtest"
                if "debian" in mirrorData[2].lower():
                    dl_file = self.umglobal.settings["dl-test"]
                url = os.path.join(mirror, dl_file)
                http = "http://"
                if url[0:4] == "http":
                    http = ""
                cmd = "curl --connect-timeout 5 -m 5 -w '%%{http_code}\n%%{speed_download}\n' -o /dev/null -s --location %s%s" % (http, url)

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
                    dlSpeed = int(dlSpeed) / 1000

                    self.queue.put([mirror, "%d kb/s" % dlSpeed])
                    print(("Server {0} - {1} kb/s ({2})".format(mirror, dlSpeed, self.getHumanReadableHttpCode(httpCode))))

            except Exception as detail:
                # This is a best-effort attempt, fail graciously
                print(("Error: http code = {} / error = {}".format(self.getHumanReadableHttpCode(httpCode), detail)))

    def getHumanReadableHttpCode(self, httpCode):
        if httpCode == 200:
            return "OK"
        elif httpCode == 302:
            return "302: found (redirect)"
        elif httpCode == 403:
            return "403: forbidden"
        elif httpCode == 404:
            return "404: not found"
        elif httpCode >= 500:
            return "%d: server error" % httpCode
        else:
            return "Error: %d" % httpCode


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

                # Get the suite of the Debian repositories
                debian_suite = ''
                matchObj = re.search("debian\.org\/debian/?\s+(\S*)", ' '.join(srcList))
                if matchObj:
                    debian_suite = matchObj.group(1).replace('-backports', '').replace('-updates', '')
                if debian_suite == '':
                    distribution = self.umglobal.getDistribution()
                    if 'ee' in distribution:
                        debian_suite = 'testing'
                    else:
                        debian_suite = 'stable'

                for line in srcList:
                    line = line.strip()
                    if not line.startswith('#'):
                        for repo in replaceRepos:
                            if repo[0] != '' and repo[0] in line:
                                skip = False
                                for excl in excludeStrings:
                                    if excl in line:
                                        skip = True
                                        break
                                if not skip:
                                    # Change repository url
                                    line = line.replace(repo[0], repo[1])
                                    break
                    if line != '':
                        new_repos.append(line)

                for repo in replaceRepos:
                    if repo[0] == '':
                        # Check if repo is already present in new_repos (replacement)
                        if not any(repo[1] in x for x in new_repos):
                            line = ''
                            if 'solydxk' in repo[1]:
                                line = "deb http://%s solydxk main upstream import" % repo[1]
                            elif 'debian.org/debian' in repo[1] and debian_suite != '':
                                line = "deb http://%s %s main contrib non-free" % (repo[1], debian_suite)
                            if line != '':
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

            return ''

        except Exception as detail:
            # This is a best-effort attempt, fail graciously
            print(("Error: %s" % detail))
            return detail
