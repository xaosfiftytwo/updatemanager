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
        self.ec = ExecCmd()
        self.settings = self.getSettings()

        # UP variables
        self.localUpVersion = None
        self.serverUpVersion = None
        self.newUp = False

        # Stable variables
        self.localStableVersion = None
        self.serverStableVersion = None
        self.newStable = False
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
                    variable = elements[0].strip()
                    value = elements[1].strip()
                    #print((">>> line = %s" % line))
                    #print((">>> variable = %s" % variable))
                    #print((">>> value = %s" % value))
                    if len(value) > 0:
                        if self.isStable:
                            if variable == "stable":
                                self.serverStableVersion = value
                                self.newStable = self.isNewServerVersion(self.serverStableVersion, self.localStableVersion)
                            elif variable == "emergencystable":
                                self.serverEmergencyVersion = value
                                self.newEmergency = self.isNewServerVersion(self.serverEmergencyVersion, self.localEmergencyVersion)
                        else:
                            if variable == "up":
                                self.serverUpVersion = value
                                self.newUp = self.isNewServerVersion(self.serverUpVersion, self.localUpVersion)
                            elif variable == "emergency":
                                self.serverEmergencyVersion = value
                                self.newEmergency = self.isNewServerVersion(self.serverEmergencyVersion, self.localEmergencyVersion)
                cont.close()
            except Exception as detail:
                print(("There is no internet connection: %s" % detail))
                self.hasInternet = False

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

        # Get the latest local history versions
        self.localEmergencyVersion = self.getHistVersion(parameter="emergency")
        if self.localEmergencyVersion is None:
            self.localEmergencyVersion = "2000.01.01"
        if self.isStable:
            self.localStableVersion = self.getHistVersion(parameter="stable")
            if self.localStableVersion is None:
                self.localStableVersion = "2000.01.01"
        else:
            self.localUpVersion = self.getHistVersion(parameter="up")
            if self.localUpVersion is None:
                self.localUpVersion = "2000.01.01"

    def getHistVersion(self, parameter, version=None):
        ret = None
        upHistFile = join(self.scriptDir, self.settings['hist'])
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

    def saveHistVersion(self, parameter, value):
        # Check if parameter with value already exists
        if self.getHistVersion(parameter, value) is None:
            # Not found: save the file
            upHistFile = join(self.scriptDir, self.settings['hist'])
            with open(upHistFile, 'a') as f:
                f.write("%s=%s\n" % (parameter, value))

    def getMirrorData(self, excludeMirrors=[]):
        mirrorData = []
        mirrorsList = join(self.scriptDir, basename(self.settings["mirrors-list"]))
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
        cfg = Config('updatemanager.conf')
        settings = {}

        section = 'url'
        try:
            settings["solydxk"] = cfg.getValue(section, 'solydxk')
            settings["solydxk-debian"] = cfg.getValue(section, 'solydxk-debian')
            settings["debian"] = cfg.getValue(section, 'debian')
        except:
            settings["solydxk"] = 'http://packages.solydxk.com'
            settings["solydxk-debian"] = 'http://debian.solydxk.com'
            settings["debian"] = 'http://ftp.debian.org'
            cfg.setValue(section, 'solydxk', settings["solydxk"])
            cfg.setValue(section, 'solydxk-debian', settings["solydxk-debian"])
            cfg.setValue(section, 'debian', settings["debian"])

        section = 'localfiles'
        try:
            settings["log"] = cfg.getValue(section, 'log')
            settings["not-found"] = cfg.getValue(section, 'not-found')
            settings["stable-info"] = cfg.getValue(section, 'stable-info')
            settings["hist"] = cfg.getValue(section, 'hist')
        except:
            settings["log"] = 'updatemanager.log'
            settings["not-found"] = 'notfound.html'
            settings["stable-info"] = 'stable.html'
            settings["hist"] = 'updatemanager.hist'
            cfg.setValue(section, 'log', settings["log"])
            cfg.setValue(section, 'not-found', settings["not-found"])
            cfg.setValue(section, 'stable-info', settings["stable-info"])
            cfg.setValue(section, 'hist', settings["hist"])

        section = 'serverfiles'
        try:
            settings["repo-info"] = cfg.getValue(section, 'repo-info')
            settings["up-info"] = cfg.getValue(section, 'up-info')
            settings["emergency-info"] = cfg.getValue(section, 'emergency-info')
            settings["emergency-stable-info"] = cfg.getValue(section, 'emergency-stable-info')
            settings["new-stable-info"] = cfg.getValue(section, 'new-stable-info')
        except:
            settings["repo-info"] = 'repo.info'
            settings["up-info"] = 'update-pack.html'
            settings["emergency-info"] = 'emergency.html'
            settings["emergency-stable-info"] = 'emergency-stable.html'
            settings["new-stable-info"] = 'new-stable.html'
            cfg.setValue(section, 'repo-info', settings["repo-info"])
            cfg.setValue(section, 'up-info', settings["up-info"])
            cfg.setValue(section, 'emergency-info', settings["emergency-info"])
            cfg.setValue(section, 'emergency-stable-info', settings["emergency-stable-info"])
            cfg.setValue(section, 'new-stable-info', settings["new-stable-info"])

        section = 'serverscripts'
        try:
            settings["emergency"] = cfg.getValue(section, 'emergency')
            settings["emergency-stable"] = cfg.getValue(section, 'emergency-stable')
            settings["pre-up"] = cfg.getValue(section, 'pre-up')
            settings["post-up"] = cfg.getValue(section, 'post-up')
            settings["pre-stable"] = cfg.getValue(section, 'pre-stable')
            settings["post-stable"] = cfg.getValue(section, 'post-stable')
        except:
            settings["emergency"] = 'emergency-[VERSION]'
            settings["emergency-stable"] = 'emergency-stable-[VERSION]'
            settings["pre-up"] = 'pre-up-[VERSION]'
            settings["post-up"] = 'post-up-[VERSION]'
            settings["pre-stable"] = 'pre-stable-[VERSION]'
            settings["post-stable"] = 'post-stable-[VERSION]'
            cfg.setValue(section, 'emergency', settings["emergency"])
            cfg.setValue(section, 'emergency-stable', settings["emergency-stable"])
            cfg.setValue(section, 'pre-up', settings["pre-up"])
            cfg.setValue(section, 'post-up', settings["post-up"])
            cfg.setValue(section, 'pre-stable', settings["pre-stable"])
            cfg.setValue(section, 'post-stable', settings["post-stable"])

        section = 'mirror'
        try:
            settings["mirrors-list"] = cfg.getValue(section, 'mirrors-list')
            settings["dl-test"] = cfg.getValue(section, 'dl-test')
            settings["dl-test-solydxk"] = cfg.getValue(section, 'dl-test-solydxk')
            settings["timeout-secs"] = int(cfg.getValue(section, 'timeout-secs'))
        except:
            settings["mirrors-list"] = 'http://packages.solydxk.com/mirrors.list'
            settings["dl-test"] = 'production/README.mirrors.html'
            settings["dl-test-solydxk"] = 'production/dists/solydxk/kdenext/binary-amd64/Packages.gz'
            settings["timeout-secs"] = 10
            cfg.setValue(section, 'mirrors-list', settings["mirrors-list"])
            cfg.setValue(section, 'dl-test', settings["dl-test"])
            cfg.setValue(section, 'dl-test-solydxk', settings["dl-test-solydxk"])
            cfg.setValue(section, 'timeout-secs', settings["timeout-secs"])

        section = 'icons'
        try:
            settings["icon-apply"] = cfg.getValue(section, 'icon-apply')
            settings["icon-disconnected"] = cfg.getValue(section, 'icon-disconnected')
            settings["icon-emergency"] = cfg.getValue(section, 'icon-emergency')
            settings["icon-error"] = cfg.getValue(section, 'icon-error')
            settings["icon-exec"] = cfg.getValue(section, 'icon-exec')
            settings["icon-info"] = cfg.getValue(section, 'icon-info')
            settings["icon-unknown"] = cfg.getValue(section, 'icon-unknown')
            settings["icon-base"] = cfg.getValue(section, 'icon-base')
            settings["icon-warning"] = cfg.getValue(section, 'icon-warning')
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
            cfg.setValue(section, 'icon-apply', settings["icon-apply"])
            cfg.setValue(section, 'icon-disconnected', settings["icon-disconnected"])
            cfg.setValue(section, 'icon-emergency', settings["icon-emergency"])
            cfg.setValue(section, 'icon-error', settings["icon-error"])
            cfg.setValue(section, 'icon-exec', settings["icon-exec"])
            cfg.setValue(section, 'icon-info', settings["icon-info"])
            cfg.setValue(section, 'icon-unknown', settings["icon-unknown"])
            cfg.setValue(section, 'icon-base', settings["icon-base"])
            cfg.setValue(section, 'icon-warning', settings["icon-warning"])

        section = 'misc'
        try:
            settings["secs-wait-user-input"] = int(cfg.getValue(section, 'secs-wait-user-input'))
            settings["hrs-check-status"] = float(cfg.getValue(section, 'hrs-check-status'))
            settings["umfilessubdir-prd"] = cfg.getValue(section, 'umfilessubdir-prd')
            settings["umfilessubdir-tst"] = cfg.getValue(section, 'umfilessubdir-tst')
            settings["testing-repo-matches"] = cfg.getValue(section, 'testing-repo-matches').split(",")
            settings["apt-packages"] = cfg.getValue(section, 'apt-packages').split(",")
        except:
            settings["secs-wait-user-input"] = 5
            settings["hrs-check-status"] = 1
            settings["umfilessubdir-prd"] = 'umfiles/prd'
            settings["umfilessubdir-tst"] = 'umfiles/tst'
            settings["testing-repo-matches"] = ["business-testing", "/testing"]
            settings["apt-packages"] = ["dpkg", "apt-get", "synaptic", "adept", "adept-notifier"]
            cfg.setValue(section, 'secs-wait-user-input', settings["secs-wait-user-input"])
            cfg.setValue(section, 'hrs-check-status', settings["hrs-check-status"])
            cfg.setValue(section, 'umfilessubdir-prd', settings["umfilessubdir-prd"])
            cfg.setValue(section, 'umfilessubdir-tst', settings["umfilessubdir-tst"])
            cfg.setValue(section, 'testing-repo-matches', ",".join(settings["testing-repo-matches"]))
            cfg.setValue(section, 'apt-packages', ",".join(settings["apt-packages"]))

        return settings

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
