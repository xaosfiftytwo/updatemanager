#! /usr/bin/env python3

import re
from config import Config
import os
from os.path import join, abspath, dirname, exists, basename
from urllib.request import urlopen, URLError
from datetime import date
from execcmd import ExecCmd

# i18n: http://docs.python.org/3/library/gettext.html
import gettext
from gettext import gettext as _
gettext.textdomain('updatemanager')


class UmGlobal(object):

    def __init__(self, collectData=True):
        # Get the settings
        self.scriptDir = abspath(dirname(__file__))
        self.filesDir = join(self.scriptDir, "files")
        self.shareDir = self.scriptDir.replace('lib', 'share')
        self.iconsDir = join(self.shareDir, 'icons')
        self.htmlDir = join(self.shareDir, "html")
        self.ec = ExecCmd()
        self.cfg = Config(join(self.filesDir, 'updatemanager.conf'))
        self.title = _("Update Manager")
        self.status = None
        self.isKf5 = False

        # Autostart
        self.autostartDir = '/etc/xdg/autostart'
        self.autostartFile = 'updatemanagertray.desktop'
        self.autostartSourceFile = join(self.filesDir, self.autostartFile)
        self.autostartDestFile = join(self.autostartDir, self.autostartFile)

        self.umfiles = {}
        self.umfiles['umupd'] = join(self.filesDir, ".umupd")
        self.umfiles['umrefresh'] = join(self.filesDir, ".umrefresh")
        self.umfiles['ummaintenance'] = join(self.filesDir, ".ummaintenance")
        self.umfiles['uminstallum'] = join(self.filesDir, ".uminstallum")

        # Status texts
        self.connectedText = _("Your system is up to date")
        self.disconnectedText = _("No internet connection")
        self.errorText = _("Error")
        self.executeText = _("Executing command")
        self.updatesText = _("There are updates available")
        self.warningText = _("Warning")

        # Variables
        self.localUpdVersion = None
        self.serverUpdVersion = None
        self.newUpd = False
        self.hasInternet = False
        self.repos = []

        # Set global variables
        if collectData:
            self.collectData()

    def collectData(self):
        # Get the settings
        self.settings = self.getSettings()
        # Check if KDE5 is running
        self.isKf5 = self.isProcessRunning("kf5")
        # Collect local information
        self.getLocalInfo()
        # Collect server information
        self.getServerInfo()

    def getServerInfo(self):
        self.newUpd = False
        self.serverUpdVersion = None
        self.hasInternet = False

        url = "%s/%s/%s" % (self.settings['solydxk'], self.settings["umfilesdir"], self.settings['repo-info'])
        cont = None
        try:
            cont = urlopen(url, timeout=10)
            self.hasInternet = True
        except URLError:
            pass

        if self.hasInternet:
            for line in cont.readlines():
                # urlopen returns bytes, need to convert to str
                line = line.decode('utf-8').strip()
                elements = line.split("=")
                parameter = elements[0].strip()
                value = elements[1].strip()
                if len(value) > 0:
                    # Write the parameter, and the value if no hist file exist: assume clean install
                    self.writeNonExistingHist(parameter)
                    if parameter == "upd":
                        self.serverUpdVersion = value

            cont.close()

            # Check for new versions
            if self.serverUpdVersion is not None:
                self.newUpd = self.isNewServerVersion(self.serverUpdVersion, self.localUpdVersion)

    def writeNonExistingHist(self, parameter):
        upHistFile = join(self.filesDir, self.settings['hist'])
        if not exists(upHistFile):
            self.saveHistVersion(parameter, "2000.01.01")
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

    def isPackageInstalled(self, package, version=None):
        try:
            cmd = "env LANG=C apt-cache policy %s | grep Installed:" % package
            lst = self.ec.run(cmd, realTime=False)[0].strip().split(' ')
            if version is not None:
                if lst[1] == version:
                    return True
                else:
                    return False
            else:
                return True
        except:
            return False

    def getLocalInfo(self):
        # Get configured repos
        self.repos = []
        with open("/etc/apt/sources.list", 'r') as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            matchObj = re.search("^deb\s*(http[:\/a-zA-Z0-9\.\-]*)", line)
            if matchObj:
                repo = matchObj.group(1)
                self.repos.append(repo)

        # Cleanup hist file first
        self.cleanupHist()

        # Get the latest local history versions
        self.localUpdVersion = self.getHistVersion(parameter="upd")
        if self.localUpdVersion is None:
            self.localUpdVersion = "2000.01.01"

    def getHistVersion(self, parameter, version=None):
        upHistFile = join(self.filesDir, self.settings['hist'])
        if exists(upHistFile):
            with open(upHistFile, 'r') as f:
                lines = f.readlines()
            for line in lines[::-1]:
                lst = line.split("=")
                if len(lst) == 2:
                    p = lst[0].strip()
                    v = lst[1].strip()
                    if p == parameter and len(v) == 10:
                        if version is not None:
                            # Get latest with given version
                            if version == v:
                                return v
                        else:
                            # Get latest
                            return v
        return None

    def cleanupHist(self):
        upHistFile = join(self.filesDir, self.settings['hist'])
        if exists(upHistFile):
            # Remove old or incorrect entries
            os.system("sed -r '/=.*[a-zA-Z]+/d' %s" % upHistFile)
            # Remove duplicate lines
            os.system("awk '!a[$0]++' %s" % upHistFile)
            #os.chmod(upHistFile, 0o666)

    def saveHistVersion(self, parameter, newVersion):
        histVersion = self.getHistVersion(parameter, newVersion)
        if histVersion != newVersion:
            # Save the file
            upHistFile = join(self.filesDir, self.settings['hist'])
            with open(upHistFile, 'a') as f:
                line = "{0}={1}\n".format(parameter, newVersion)
                f.write(line)

    def getMirrorData(self, excludeMirrors=[], getDeadMirrors=False):
        mirrorData = []

        mirrorsList = join(self.filesDir, basename(self.settings["mirrors-list"]))
        if getDeadMirrors:
            mirrorsList = "%s.dead" % mirrorsList

        #if os.getuid() != 0 and not exists(mirrorsList):
            #mirrorsList = join('/tmp', basename(self.settings["mirrors-list"]))

        try:
            # Download the mirrors list from the server
            url = self.settings["mirrors-list"]
            if getDeadMirrors:
                url = "%s.dead" % url
            txt = urlopen(url).read().decode('utf-8')
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
                if len(data) > 2:
                    if getDeadMirrors:
                        blnAdd = False
                        for repo in self.repos:
                            if data[2] in repo:
                                blnAdd = True
                                break
                    else:
                        blnAdd = True
                        for excl in excludeMirrors:
                            if excl in data[2]:
                                blnAdd = False
                                break
                    if blnAdd:
                        mirrorData.append(data)
        return mirrorData

    def getSettings(self):
        settings = {}

        section = 'url'
        try:
            settings["solydxk"] = self.cfg.getValue(section, 'solydxk')
        except:
            settings["solydxk"] = 'http://repository.solydxk.com'
            self.saveSettings(section, 'solydxk', settings["solydxk"])

        section = 'localfiles'
        try:
            settings["log"] = self.cfg.getValue(section, 'log')
            settings["not-found"] = self.cfg.getValue(section, 'not-found')
            settings["up-to-date"] = self.cfg.getValue(section, 'up-to-date')
            settings["updates"] = self.cfg.getValue(section, 'updates')
            settings["hist"] = self.cfg.getValue(section, 'hist')
        except:
            settings["log"] = 'updatemanager.log'
            settings["not-found"] = 'notfound.html'
            settings["up-to-date"] = 'uptodate.html'
            settings["updates"] = 'updates.html'
            settings["hist"] = 'updatemanager.hist'
            self.saveSettings(section, 'log', settings["log"])
            self.saveSettings(section, 'not-found', settings["not-found"])
            self.saveSettings(section, 'up-to-date', settings["up-to-date"])
            self.saveSettings(section, 'updates', settings["updates"])
            self.saveSettings(section, 'hist', settings["hist"])

        section = 'serverfiles'
        try:
            settings["repo-info"] = self.cfg.getValue(section, 'repo-info')
            settings["upd-info"] = self.cfg.getValue(section, 'upd-info')
        except:
            settings["repo-info"] = 'repo.info'
            settings["upd-info"] = 'update.html'
            self.saveSettings(section, 'repo-info', settings["repo-info"])
            self.saveSettings(section, 'upd-info', settings["upd-info"])

        section = 'serverscripts'
        try:
            settings["pre-upd"] = self.cfg.getValue(section, 'pre-upd')
            settings["post-upd"] = self.cfg.getValue(section, 'post-upd')

        except:
            settings["pre-upd"] = 'pre-upd-[VERSION]'
            settings["post-upd"] = 'post-upd-[VERSION]'
            self.saveSettings(section, 'pre-upd', settings["pre-upd"])
            self.saveSettings(section, 'post-upd', settings["post-upd"])

        section = 'mirror'
        try:
            settings["mirrors-list"] = self.cfg.getValue(section, 'mirrors-list')
            settings["dl-test"] = self.cfg.getValue(section, 'dl-test')
        except:
            settings["mirrors-list"] = 'http://repository.solydxk.com/mirrors.list'
            settings["dl-test"] = 'README.mirrors.html'
            self.saveSettings(section, 'mirrors-list', settings["mirrors-list"])
            self.saveSettings(section, 'dl-test', settings["dl-test"])

        section = 'icons'
        try:
            settings["icon-connected"] = self.cfg.getValue(section, 'icon-connected')
            settings["icon-disconnected"] = self.cfg.getValue(section, 'icon-disconnected')
            settings["icon-error"] = self.cfg.getValue(section, 'icon-error')
            settings["icon-execute"] = self.cfg.getValue(section, 'icon-execute')
            settings["icon-updates"] = self.cfg.getValue(section, 'icon-updates')
            settings["icon-warning"] = self.cfg.getValue(section, 'icon-warning')
        except:
            settings["icon-connected"] = 'connected.svg'
            settings["icon-disconnected"] = 'disconnected.svg'
            settings["icon-error"] = 'error.svg'
            settings["icon-execute"] = 'execute.svg'
            settings["icon-updates"] = 'updates.svg'
            settings["icon-warning"] = 'warning.svg'
            self.saveSettings(section, 'icon-connected', settings["icon-connected"])
            self.saveSettings(section, 'icon-disconnected', settings["icon-disconnected"])
            self.saveSettings(section, 'icon-error', settings["icon-error"])
            self.saveSettings(section, 'icon-execute', settings["icon-execute"])
            self.saveSettings(section, 'icon-updates', settings["icon-updates"])
            self.saveSettings(section, 'icon-warning', settings["icon-warning"])

        section = 'misc'
        try:
            settings["allow-terminal-user-input"] = True
            bln = self.cfg.getValue(section, 'allow-terminal-user-input').lower()
            if bln == "false":
                settings["allow-terminal-user-input"] = False
            settings["hrs-check-status"] = int(self.cfg.getValue(section, 'hrs-check-status'))
            settings["umfilesdir"] = self.cfg.getValue(section, 'umfilesdir')
            settings["apt-packages"] = self.cfg.getValue(section, 'apt-packages').split(",")
            settings["hide-tabs"] = self.cfg.getValue(section, 'hide-tabs').split(",")
            settings["um-dependencies"] = self.cfg.getValue(section, 'um-dependencies').split(",")
            settings["apt-get-string"] = self.cfg.getValue(section, 'apt-get-string')
            settings["autostart"] = True
            if not exists(self.autostartDestFile):
                settings["autostart"] = False
        except:
            settings["allow-terminal-user-input"] = True
            settings["hrs-check-status"] = 1
            settings["umfilesdir"] = 'umfiles'
            settings["apt-packages"] = ["dpkg", "apt-get", "synaptic", "adept", "adept-notifier"]
            settings["hide-tabs"] = ["maintenance"]
            settings["um-dependencies"] = ["gksu", "apt-show-versions", "deborphan", "apt", "curl", "python3-gi", "python-vte", "gir1.2-vte-2.90", "gir1.2-webkit-3.0", "python3", "gir1.2-gtk-3.0", "python3-pyinotify"]
            settings["apt-get-string"] = 'DEBIAN_FRONTEND=gnome apt-get --assume-yes -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold --force-yes'
            settings["autostart"] = True
            if not exists(self.autostartDestFile):
                settings["autostart"] = False
            self.saveSettings(section, 'allow-terminal-user-input', str(settings["allow-terminal-user-input"]).lower())
            self.saveSettings(section, 'hrs-check-status', settings["hrs-check-status"])
            self.saveSettings(section, 'umfilesdir', settings["umfilesdir"])
            self.saveSettings(section, 'apt-packages', ",".join(settings["apt-packages"]))
            self.saveSettings(section, 'hide-tabs', ",".join(settings["hide-tabs"]))
            self.saveSettings(section, 'um-dependencies', ",".join(settings["um-dependencies"]))
            self.saveSettings(section, 'apt-get-string', settings["apt-get-string"])

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

    def getProcessPids(self, processName, fuzzy=True):
        if fuzzy:
            pids = self.ec.run(cmd="ps -ef | grep -v sudo | grep -v grep | grep '%s' | awk '{print $2}'" % processName, realTime=False)
        else:
            pids = self.ec.run(cmd="pidof {}".format(processName, realTime=False))
        return pids

    def isProcessRunning(self, processName, fuzzy=True, excludeSelf=True):
        pids = self.getProcessPids(processName, fuzzy)
        if len(pids) > 0:
            return True
        return False

    def killScriptProcess(self, scriptName):
        msg = _('Please enter your password')
        pids = self.getProcessPids(scriptName)
        for pid in pids:
            print(("Kill %s process with pid: %s" % (scriptName, pid)))
            cmd = "gksudo --message \"<b>%s</b>\" kill %s" % (msg, pid)
            self.ec.run(cmd, False)

    def reloadWindow(self, scriptPath, runAsUser):
        path = self.ec.run(cmd="which python3", returnAsList=False)
        if exists(path):
            try:
                os.execl(path, path, scriptPath, runAsUser)
            except OSError as err:
                self.log.write("Reload UM: %s" % str(err), "UM.reloadWindow", "error")

    def getKernelVersion(self):
        version = self.ec.run(cmd="uname -r", realTime=False)[0]
        try:
            ind = version.rindex("-")
            return version[0:ind]
        except:
            return version

    def getKernelArchitecture(self):
        return self.ec.run(cmd="uname -m", realTime=False)[0]

    def getDistribution(self):
        distribution = ""
        if exists('/etc/solydxk/info'):
            distribution = self.ec.run("cat /etc/solydxk/info | grep EDITION | cut -d'=' -f 2", realTime=False, returnAsList=False)
        return distribution

    def isUpgrading(self):
        if exists(self.umfiles['umupd']):
            return True
        else:
            return False

    def isRefreshing(self):
        if exists(self.umfiles['umrefresh']):
            return True
        else:
            return False

    def getLoginName(self):
        return self.ec.run(cmd="logname", realTime=False, returnAsList=False)

    # Only allow numbers in entry field
    # umglobal.onlyNumbers(self.txtField)
    def onlyNumbers(self, widget):
        def filter(entry, *args):
            text = entry.get_text().strip().lower()
            entry.set_text(''.join([i for i in text if i in '0123456789']))
        widget.connect('changed', filter)
