#! /usr/bin/env python3
#-*- coding: utf-8 -*-

from execcmd import ExecCmd
import gettext
import re

# i18n: http://docs.python.org/2/library/gettext.html
gettext.install("updatemanager", "/usr/share/locale")
#t = gettext.translation("updatemanager", "/usr/share/locale")
#_ = t.lgettext


class UmApt(object):

    def __init__(self, umglobal):
        self.ec = ExecCmd()
        self.umglobal = umglobal

        self.packagesVersionInfo = []
        self.packagesNotAvailable = []
        self.createPackagesVersionInfoLists()

        self.upgradablePackagesText = _("The following packages will be upgraded:")
        self.upgradablePackages = []
        self.newPackagesText = _("The following NEW packages will be installed:")
        self.newPackages = []
        self.removedPackagesText = _("The following packages will be REMOVED:")
        self.removedPackages = []
        self.heldbackPackagesText = _("The following packages have been kept back:")
        self.heldbackPackages = []
        self.createPackageLists()

        #print("===============================================")
        #print((str(self.packagesVersionInfo)))
        #print("===============================================")
        #print((str(self.packagesNotAvailable)))
        #print("===============================================")
        #print((str(self.upgradablePackages)))
        #print("===============================================")
        #print((str(self.newPackages)))
        #print("===============================================")
        #print((str(self.removedPackages)))
        #print("===============================================")
        #print((str(self.heldbackPackages)))
        #print("===============================================")

    def createPackagesVersionInfoLists(self):
        # Reset variables
        self.packagesVersionInfo = []
        self.packagesNotAvailable = []

        # Use env LANG=C to ensure the output of apt-show-versions is always en_US
        cmd = "env LANG=C bash -c 'apt-show-versions'"

        # Get the output of the command in a list
        lst = self.ec.run(cmd=cmd, realTime=False)

        # Loop through each line and fill the info list
        for line in lst:
            matchObj = re.search("([a-z0-9-]+):([.\S]+)\s+(\d[.\S]*)[a-z ]+(.*)", line)
            if not matchObj:
                # For stable - not used (too many bugs to work out)
                matchObj = re.search("([a-z0-9-]+)/([.\S]+)[a-z ]+(\d[.\S]*)[a-z ]*(.*)", line)
            if matchObj:
                self.packagesVersionInfo.append([matchObj.group(1),
                                                 matchObj.group(2),
                                                 matchObj.group(3),
                                                 matchObj.group(4)])
            elif "no available version" in line.lower():
                matchObj = re.search("(.*):[a-z]", line)
                if matchObj:
                    pck = matchObj.group(1)
                    cmdChk = "env LANG=C bash -c 'apt-cache show %s | grep Version:'" % pck
                    chkLst = self.ec.run(cmdChk, False)
                    if len(chkLst) < 2:
                        self.packagesNotAvailable.append(pck)

    def createPackageLists(self):
        # Reset variables
        self.upgradablePackages = []
        self.newPackages = []
        self.removedPackages = []
        self.heldbackPackages = []

        # Create approriate command
        # Use env LANG=C to ensure the output of dist-upgrade is always en_US
        cmd = "env LANG=C bash -c 'apt-get dist-upgrade --assume-no'"
        if self.umglobal.isStable:
            cmd = "env LANG=C bash -c 'apt-get upgrade --assume-no'"

        # Get the output of the command in a list
        lst = self.ec.run(cmd=cmd, realTime=False)

        # Loop through each line and fill the package lists
        prevLine = None
        for line in lst:
            if line[0:1].strip() == "":
                if "removed:" in prevLine.lower():
                    self.fillPackageList(self.removedPackages, line.strip())
                elif "new packages" in prevLine.lower():
                    self.fillPackageList(self.newPackages, line.strip())
                elif "kept back:" in prevLine.lower():
                    self.fillPackageList(self.heldbackPackages, line.strip())
                elif "upgraded:" in prevLine.lower():
                    self.fillPackageList(self.upgradablePackages, line.strip(), True)
            else:
                prevLine = line

    def fillPackageList(self, packageList, line, addVersionInfo=False):
        packages = line.split(" ")
        for package in packages:
            package = package.strip()
            if addVersionInfo:
                for info in self.packagesVersionInfo:
                    if package == info[0]:
                        packageList.append([package, info[2], info[3]])
                        break
            else:
                packageList.append(package)

    def getDistUpgradeInfo(self, upgradablesOnly=False):
        info = ""
        if upgradablesOnly:
            if self.upgradablePackages:
                info += "<strong>%s</strong><br>%s" % (self.upgradablePackagesText, " ".join(self.upgradablePackages))
        else:
            if self.removedPackages:
                info += "<strong>%s</strong><br>%s" % (self.removedPackagesText, " ".join(self.removedPackages))
            if self.newPackages:
                if info != "":
                    info += "<p>&nbsp;</p>"
                info += "<strong>%s</strong><br>%s" % (self.newPackagesText, " ".join(self.newPackages))
            if self.heldbackPackages:
                if info != "":
                    info += "<p>&nbsp;</p>"
                info += "<strong>%s</strong><br>%s" % (self.heldbackPackagesText, " ".join(self.heldbackPackages))
        return info

    def showVersions(self, upgradablesOnly=False, packageNames=[]):
        pcks = []
        cmd = "apt-show-versions"
        if upgradablesOnly:
            cmd = "%s -u" % cmd
            if not packageNames:
                packageNames = self.ec.run("aptitude search '~U' | awk '{print $2}'", False)

        versionInfo = self.ec.run(cmd, realTime=False)
        for line in versionInfo:
            data = line.split(" ")
            pck = None
            oldVer = None
            newVer = None
            for d in data:
                d = d.strip()
                if pck is None and ":" in d:
                    pck = d.split(":")[0]
                elif pck is None and "/" in d:
                    pck = d.split("/")[0]
                if oldVer is None:
                    if d[0:1].isdigit():
                        oldVer = d
                else:
                    if newVer is None and d[0:1].isdigit():
                        newVer = d

            if pck is not None and oldVer is not None:
                if packageNames:
                    for pn in packageNames:
                        if pn == pck:
                            pcks.append([pck, oldVer, newVer])
                elif newVer is not None:
                    pcks.append([pck, oldVer, newVer])
        return pcks

    def getUpgradablePackages(self, packageNames=[]):
        if packageNames:
            upckList = []
            for packageName in packageNames:
                for upck in self.upgradablePackages:
                    if upck[0] == packageName:
                        upckList.append(upck)
                        break
            return upckList
        else:
            return self.upgradablePackages

    # Get the package version number
    def getPackageVersion(self, packageName, candidate=False):
        cmd = "env LANG=C bash -c 'apt-show-versions -p %s'" % packageName
        lst = self.ec.run(cmd, False)
        for line in lst:
            matchObj = re.search("([a-z0-9-]+):([.\S]+)\s+(\d[.\S]*)[a-z ]+(.*)", line)
            if matchObj:
                if candidate:
                    return matchObj.group(4)
                else:
                    return matchObj.group(3)
        return ""

    def aptHasErrors(self):
        ret = self.ec.run("apt-get --assume-no upgrade", False, False)
        if ret[0:2].upper() == "E:":
            return ret
        return None

    def getAptCacheLockedProgram(self, aptPackages):
        procLst = self.ec.run("ps -U root -u root -o comm=", False)
        for aptProc in aptPackages:
            if aptProc in procLst:
                return aptProc
        return None
