#! /usr/bin/env python3
#-*- coding: utf-8 -*-

import re
from config import Config
import os
from os.path import join, abspath, dirname, exists, basename
from urllib.request import urlopen
from datetime import date
from execcmd import ExecCmd


class UmGlobal(object):

    def __init__(self):
        # Get the settings
        self.scriptDir = abspath(dirname(__file__))
        self.filesDir = join(self.scriptDir, "files")
        self.ec = ExecCmd()
        self.cfg = Config(join(self.filesDir, 'updatemanager.conf'))
        self.settings = self.getSettings()

        # UP variables
        self.localUpVersion = None
        self.serverUpVersion = None
        self.newUp = False

        # Stable variables
        self.localStableVersion = None
        self.serverStableVersion = None
        self.localNewStableVersion = None
        self.serverNewStableVersion = None
        self.newStable = False
        self.newNewStable = False
        self.isStable = False

        # Emergency variables
        self.localEmergencyVersion = None
        self.serverEmergencyVersion = None
        self.newEmergency = False

        self.hasInternet = False
        self.repos = []

        # Set global variables
        self.umfilesUrl = self.getUmFilesUrl()
        self.collectData()

    def collectData(self):
        self.getLocalInfo()
        self.getServerInfo()

    def getServerInfo(self):
        if self.umfilesUrl is not None:
            url = "%s/%s" % (self.umfilesUrl, self.settings['repo-info'])
            #print((">>> url = %s" % url))
            try:
                cont = urlopen(url, timeout=self.settings["timeout-secs"])
                self.hasInternet = True
                for line in cont.readlines():
                    # urlopen returns bytes, need to convert to str
                    line = line.decode('utf-8').strip()
                    elements = line.split("=")
                    parameter = elements[0].strip()
                    value = elements[1].strip()
                    #print((">>> line = %s" % line))
                    #print((">>> parameter = %s" % parameter))
                    #print((">>> value = %s" % value))
                    if len(value) > 0:
                        if self.isStable:
                            # Write the parameter, and the value if no hist file exist: assume clean install
                            self.writeNonExistingHist(parameter, value)
                            if parameter == "newstable":
                                self.serverNewStableVersion = value
                                self.newNewStable = self.isNewServerVersion(self.serverNewStableVersion, self.localNewStableVersion)
                            elif parameter == "stable":
                                self.serverStableVersion = value
                                self.newStable = self.isNewServerVersion(self.serverStableVersion, self.localStableVersion)
                            elif parameter == "emergencystable":
                                self.serverEmergencyVersion = value
                                self.newEmergency = self.isNewServerVersion(self.serverEmergencyVersion, self.localEmergencyVersion)
                        else:
                            # Write the parameter, and the value if no hist file exist: assume clean install
                            self.writeNonExistingHist(parameter, value)
                            if parameter == "up":
                                self.serverUpVersion = value
                                self.newUp = self.isNewServerVersion(self.serverUpVersion, self.localUpVersion)
                            elif parameter == "emergency":
                                self.serverEmergencyVersion = value
                                self.newEmergency = self.isNewServerVersion(self.serverEmergencyVersion, self.localEmergencyVersion)
                cont.close()
            except Exception as detail:
                print(("There is no internet connection: %s" % detail))
                self.hasInternet = False

    def writeNonExistingHist(self, parameter, version):
        upHistFile = join(self.filesDir, self.settings['hist'])
        if not exists(upHistFile):
            self.saveHistVersion(parameter, version)
            self.getLocalInfo()

    def isNewServerVersion(self, serverVersion, localVersion):
        isNew = False
        serverVersion = str(serverVersion)
        localVersion = str(localVersion)
        if len(serverVersion) == len(localVersion):
            valArr = serverVersion.split('.')
            instUpArr = localVersion.split('.')
            instDate = date(int(instUpArr[0]), int(instUpArr[1]), int(instUpArr[2]))
            valDate = date(int(valArr[0]), int(valArr[1]), int(valArr[2]))
            if valDate > instDate:
                # Server version is newer
                isNew = True
        return isNew

    def getLocalInfo(self):
        # Get configured repos, and check whether they are pointing to stable (LTS) or not
        self.repos = []
        with open("/etc/apt/sources.list", 'r') as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            matchObj = re.search("^deb\s*(http[:\/a-zA-Z0-9\.\-]*)", line)
            if matchObj:
                repo = matchObj.group(1)
                if '/lts' in repo or '/business' in repo:
                    self.isStable = True
                self.repos.append(repo)

        # Cleanup hist file first
        self.cleanupHist()

        # Get the latest local history versions
        self.localEmergencyVersion = self.getHistVersion(parameter="emergency")
        if self.localEmergencyVersion is None:
            self.localEmergencyVersion = "2000.01.01"
        if self.isStable:
            self.localStableVersion = self.getHistVersion(parameter="stable")
            if self.localStableVersion is None:
                self.localStableVersion = "2000.01.01"

            self.localNewStableVersion = self.getHistVersion(parameter="newstable")
            if self.localNewStableVersion is None:
                self.localNewStableVersion = "2000.01.01"
        else:
            self.localUpVersion = self.getHistVersion(parameter="up")
            if self.localUpVersion is None:
                self.localUpVersion = "2000.01.01"

    def getHistVersion(self, parameter, version=None):
        ret = None
        upHistFile = join(self.filesDir, self.settings['hist'])
        if exists(upHistFile):
            with open(upHistFile, 'r') as f:
                lines = f.readlines()
            for line in lines[::-1]:
                line = line.split("=")
                if len(line) == 2:
                    p = line[0].strip()
                    v = line[1].strip()
                    if p == parameter and len(v) == 10:
                        if version is not None:
                            # Get latest with given version
                            if version == v:
                                ret = v
                                break
                        else:
                            # Get latest
                            ret = v
                            break
        return ret

    def cleanupHist(self):
        upHistFile = join(self.filesDir, self.settings['hist'])
        if exists(upHistFile):
            # Remove old or incorrect entries
            os.system("sed -r '/=.*[a-zA-Z]+/d' %s" % upHistFile)
            #os.chmod(upHistFile, 0o666)
            if self.isStable:
                # The old UM used up= for stable as well
                # This UM has its own parameter stable=
                stableHist = self.ec.run("grep 'stable=' %s" % upHistFile, False)
                if stableHist:
                    # Remove up history
                    os.system("sed -i '/up=/d' %s" % upHistFile)
                else:
                    # Rename up history
                    upHist = self.ec.run("grep 'up=' %s" % upHistFile, False)
                    if upHist:
                        os.system("sed -i 's/up=/stable=/' %s" % upHistFile)

    def saveHistVersion(self, parameter, value):
        # Check if parameter with value already exists
        if self.getHistVersion(parameter, value) is None:
            # Not found: save the file
            upHistFile = join(self.filesDir, self.settings['hist'])
            with open(upHistFile, 'a') as f:
                f.write("%s=%s\n" % (parameter, value))

    def getMirrorData(self, excludeMirrors=[]):
        mirrorData = []
        mirrorsList = join(self.filesDir, basename(self.settings["mirrors-list"]))
        if os.getuid() != 0 and not exists(mirrorsList):
            mirrorsList = join('/tmp', basename(self.settings["mirrors-list"]))

        try:
            # Download the mirrors list from the server
            txt = urlopen(self.settings["mirrors-list"]).read().decode('utf-8')
            if txt != '':
                # Save to a file
                with open(mirrorsList, 'w') as f:
                    f.write(txt)
        except:
            pass

        if exists(mirrorsList):
            with open(mirrorsList, 'r') as f:
                lines = f.readlines()
            for line in lines:
                data = line.strip().split(',')
                #print((">>> data = %s" % str(data)))
                if len(data) > 2:
                    if data[2] not in excludeMirrors:
                        #print((">>> append data"))
                        mirrorData.append(data)
        return mirrorData

    def getUmFilesUrl(self):
        if self.localUpVersion is None:
            self.getLocalInfo()

        xkUrl = self.settings['solydxk']
        url = "%s/%s" % (xkUrl, self.settings["umfilessubdir-prd"])
        mirrors = self.getMirrorData()
        #print(("> mirrors = %s" % str(mirrors)))
        for repo in self.repos:
            #print((">> repo = %s" % str(repo)))
            for mirror in mirrors:
                #print((">>> mirror = %s" % str(mirror)))
                if mirror[2] in repo:
                    #print((">>> testing-repo-matches = %s" % str(self.settings["testing-repo-matches"])))
                    for match in self.settings["testing-repo-matches"]:
                        #print((">>>> match = %s" % str(match)))
                        if match in repo:
                            url = "%s/%s" % (xkUrl, self.settings["umfilessubdir-tst"])
                            print(("Repo URL = %s" % str(url)))
                            return url
        print(("Repo URL = %s" % str(url)))
        return url

    def getSettings(self):
        settings = {}

        section = 'url'
        try:
            settings["solydxk"] = self.cfg.getValue(section, 'solydxk')
            settings["solydxk-debian"] = self.cfg.getValue(section, 'solydxk-debian')
            settings["debian"] = self.cfg.getValue(section, 'debian')
        except:
            settings["solydxk"] = 'http://home.solydxk.com'
            settings["solydxk-debian"] = 'http://debian.solydxk.com'
            settings["debian"] = 'http://ftp.debian.org'
            self.saveSettings(section, 'solydxk', settings["solydxk"])
            self.saveSettings(section, 'solydxk-debian', settings["solydxk-debian"])
            self.saveSettings(section, 'debian', settings["debian"])

        section = 'localfiles'
        try:
            settings["log"] = self.cfg.getValue(section, 'log')
            settings["not-found"] = self.cfg.getValue(section, 'not-found')
            settings["hist"] = self.cfg.getValue(section, 'hist')
        except:
            settings["log"] = 'updatemanager.log'
            settings["not-found"] = 'notfound.html'
            settings["hist"] = 'updatemanager.hist'
            self.saveSettings(section, 'log', settings["log"])
            self.saveSettings(section, 'not-found', settings["not-found"])
            self.saveSettings(section, 'hist', settings["hist"])

        section = 'serverfiles'
        try:
            settings["repo-info"] = self.cfg.getValue(section, 'repo-info')
            settings["up-info"] = self.cfg.getValue(section, 'up-info')
            settings["stable-info"] = self.cfg.getValue(section, 'stable-info')
            settings["emergency-info"] = self.cfg.getValue(section, 'emergency-info')
            settings["emergency-stable-info"] = self.cfg.getValue(section, 'emergency-stable-info')
            settings["new-stable-info"] = self.cfg.getValue(section, 'new-stable-info')
        except:
            settings["repo-info"] = 'repo.info'
            settings["up-info"] = 'update-pack.html'
            settings["stable-info"] = 'stable.html'
            settings["emergency-info"] = 'emergency.html'
            settings["emergency-stable-info"] = 'emergency-stable.html'
            settings["new-stable-info"] = 'new-stable.html'
            self.saveSettings(section, 'repo-info', settings["repo-info"])
            self.saveSettings(section, 'up-info', settings["up-info"])
            self.saveSettings(section, 'stable-info', settings["stable-info"])
            self.saveSettings(section, 'emergency-info', settings["emergency-info"])
            self.saveSettings(section, 'emergency-stable-info', settings["emergency-stable-info"])
            self.saveSettings(section, 'new-stable-info', settings["new-stable-info"])

        section = 'serverscripts'
        try:
            settings["emergency"] = self.cfg.getValue(section, 'emergency')
            settings["emergency-stable"] = self.cfg.getValue(section, 'emergency-stable')
            settings["pre-up"] = self.cfg.getValue(section, 'pre-up')
            settings["post-up"] = self.cfg.getValue(section, 'post-up')
            settings["pre-stable"] = self.cfg.getValue(section, 'pre-stable')
            settings["post-stable"] = self.cfg.getValue(section, 'post-stable')
        except:
            settings["emergency"] = 'emergency-[VERSION]'
            settings["emergency-stable"] = 'emergency-stable-[VERSION]'
            settings["pre-up"] = 'pre-up-[VERSION]'
            settings["post-up"] = 'post-up-[VERSION]'
            settings["pre-stable"] = 'pre-stable-[VERSION]'
            settings["post-stable"] = 'post-stable-[VERSION]'
            self.saveSettings(section, 'emergency', settings["emergency"])
            self.saveSettings(section, 'emergency-stable', settings["emergency-stable"])
            self.saveSettings(section, 'pre-up', settings["pre-up"])
            self.saveSettings(section, 'post-up', settings["post-up"])
            self.saveSettings(section, 'pre-stable', settings["pre-stable"])
            self.saveSettings(section, 'post-stable', settings["post-stable"])

        section = 'mirror'
        try:
            settings["mirrors-list"] = self.cfg.getValue(section, 'mirrors-list')
            settings["dl-test"] = self.cfg.getValue(section, 'dl-test')
            settings["dl-test-solydxk"] = self.cfg.getValue(section, 'dl-test-solydxk')
            settings["timeout-secs"] = int(self.cfg.getValue(section, 'timeout-secs'))
        except:
            settings["mirrors-list"] = 'http://home.solydxk.com/mirrors.list'
            settings["dl-test"] = 'production/README.mirrors.html'
            settings["dl-test-solydxk"] = 'production/dists/solydxk/kdenext/binary-amd64/Packages.gz'
            settings["timeout-secs"] = 10
            self.saveSettings(section, 'mirrors-list', settings["mirrors-list"])
            self.saveSettings(section, 'dl-test', settings["dl-test"])
            self.saveSettings(section, 'dl-test-solydxk', settings["dl-test-solydxk"])
            self.saveSettings(section, 'timeout-secs', settings["timeout-secs"])

        section = 'icons'
        try:
            settings["icon-apply"] = self.cfg.getValue(section, 'icon-apply')
            settings["icon-disconnected"] = self.cfg.getValue(section, 'icon-disconnected')
            settings["icon-emergency"] = self.cfg.getValue(section, 'icon-emergency')
            settings["icon-error"] = self.cfg.getValue(section, 'icon-error')
            settings["icon-exec"] = self.cfg.getValue(section, 'icon-exec')
            settings["icon-info"] = self.cfg.getValue(section, 'icon-info')
            settings["icon-unknown"] = self.cfg.getValue(section, 'icon-unknown')
            settings["icon-base"] = self.cfg.getValue(section, 'icon-base')
            settings["icon-warning"] = self.cfg.getValue(section, 'icon-warning')
        except:
            settings["icon-apply"] = '/usr/share/solydxk/updatemanager/icons/base-apply.png'
            settings["icon-disconnected"] = '/usr/share/solydxk/updatemanager/icons/base-disconnected.png'
            settings["icon-emergency"] = '/usr/share/solydxk/updatemanager/icons/base-emergency.png'
            settings["icon-error"] = '/usr/share/solydxk/updatemanager/icons/base-error.png'
            settings["icon-exec"] = '/usr/share/solydxk/updatemanager/icons/base-exec.png'
            settings["icon-info"] = '/usr/share/solydxk/updatemanager/icons/base-info.png'
            settings["icon-unknown"] = '/usr/share/solydxk/updatemanager/icons/base-unknown.png'
            settings["icon-base"] = '/usr/share/solydxk/updatemanager/icons/base.png'
            settings["icon-warning"] = '/usr/share/solydxk/updatemanager/icons/base-warning.png'
            self.saveSettings(section, 'icon-apply', settings["icon-apply"])
            self.saveSettings(section, 'icon-disconnected', settings["icon-disconnected"])
            self.saveSettings(section, 'icon-emergency', settings["icon-emergency"])
            self.saveSettings(section, 'icon-error', settings["icon-error"])
            self.saveSettings(section, 'icon-exec', settings["icon-exec"])
            self.saveSettings(section, 'icon-info', settings["icon-info"])
            self.saveSettings(section, 'icon-unknown', settings["icon-unknown"])
            self.saveSettings(section, 'icon-base', settings["icon-base"])
            self.saveSettings(section, 'icon-warning', settings["icon-warning"])

        section = 'misc'
        try:
            settings["secs-wait-user-input"] = int(self.cfg.getValue(section, 'secs-wait-user-input'))
            settings["hrs-check-status"] = int(self.cfg.getValue(section, 'hrs-check-status'))
            settings["umfilessubdir-prd"] = self.cfg.getValue(section, 'umfilessubdir-prd')
            settings["umfilessubdir-tst"] = self.cfg.getValue(section, 'umfilessubdir-tst')
            settings["testing-repo-matches"] = self.cfg.getValue(section, 'testing-repo-matches').split(",")
            settings["apt-packages"] = self.cfg.getValue(section, 'apt-packages').split(",")
        except:
            settings["secs-wait-user-input"] = 5
            settings["hrs-check-status"] = 1
            settings["umfilessubdir-prd"] = 'umfiles/prd'
            settings["umfilessubdir-tst"] = 'umfiles/tst'
            settings["testing-repo-matches"] = ["business-testing", "/testing"]
            settings["apt-packages"] = ["dpkg", "apt-get", "synaptic", "adept", "adept-notifier"]
            self.saveSettings(section, 'secs-wait-user-input', settings["secs-wait-user-input"])
            self.saveSettings(section, 'hrs-check-status', settings["hrs-check-status"])
            self.saveSettings(section, 'umfilessubdir-prd', settings["umfilessubdir-prd"])
            self.saveSettings(section, 'umfilessubdir-tst', settings["umfilessubdir-tst"])
            self.saveSettings(section, 'testing-repo-matches', ",".join(settings["testing-repo-matches"]))
            self.saveSettings(section, 'apt-packages', ",".join(settings["apt-packages"]))

        return settings

    def saveSettings(self, section, name, value):
        self.cfg.setValue(section, name, value)

    def isNumeric(self, n):
        try:
            n = complex(n)
            return True
        except:
            try:
                n = float(n, 0)
                return True
            except:
                try:
                    n = int(n, 0)
                    return True
                except:
                    return False

    def strToNumber(self, stringnr, toInt=False):
        nr = 0
        stringnr = stringnr.strip()
        try:
            if toInt:
                nr = int(stringnr)
            else:
                nr = float(stringnr)
        except ValueError:
            nr = 0
        return nr

    def getScriptPid(self, script, returnExistingPid=False):
        cnt = 0
        pid = 0
        try:
            procs = self.ec.run(cmd="ps -ef | grep %s" % script, realTime=False)
            for pline in procs:
                matchObj = re.search("([0-9]+).*:\d\d\s.*python", pline)
                if matchObj:
                    if returnExistingPid:
                        cnt += 1
                        if cnt > 1:
                            return pid
                    else:
                        return int(matchObj.group(1))
                    pid = int(matchObj.group(1))
            return 0
        except:
            return 0
