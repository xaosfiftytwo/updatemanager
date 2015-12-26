#! /usr/bin/env python3

from gi.repository import GObject
from execcmd import ExecCmd
from os.path import join
from os import remove
from glob import glob

# i18n: http://docs.python.org/3/library/gettext.html
import gettext
from gettext import gettext as _
gettext.textdomain('updatemanager')

# Need to initiate threads for Gtk
GObject.threads_init()


class UmRefresh(object):

    def __init__(self, umglobal, indicator):
        self.ec = ExecCmd()
        self.indicator = indicator
        self.umglobal = umglobal
        self.quit = False

    def changeIcon(self, iconName, tooltip):
        if self.umglobal.isKf5:
            # Use this for KDE5
            print(("> icon: {}, tooltip: {}".format(iconName, tooltip)))
            # tooltop is not showing
            self.indicator.set_icon_full(self.umglobal.settings[iconName], tooltip)
            # Attention icon is not doing anything
            #self.indicator.set_attention_icon_full(self.umglobal.settings[iconName], tooltip)
            # This isn't working either: Plasma 5 is not being refreshed, 4 not showing anything at all
            #self.indicator.set_title("<strong>{}</strong><br>{}".format(self.umglobal.title, tooltip))
        else:
            # Use this for KDE4
            iconPath = join(self.umglobal.iconsDir, self.umglobal.settings[iconName])
            print(("> icon: {}, tooltip: {}".format(iconPath, tooltip)))
            self.indicator.set_from_file(iconPath)
            self.indicator.set_tooltip_text(tooltip)

    def refresh(self):
        # Don't refresh if the apt cache is being refreshed
        if not self.isAptExecuting():
            if not self.umglobal.isProcessRunning("updatemanager.py"):
                for fle in glob(join(self.umglobal.filesDir, ".um*")):
                    remove(fle)

            self.umglobal.getLocalInfo()
            if self.umglobal.repos:
                if self.umglobal.hasInternet:
                    # Check update status
                    if self.checkForUpdates():
                        if self.umglobal.newUpd:
                            self.umglobal.updatesText = _("New update: %s" % self.umglobal.serverUpdVersion)
                            print((self.umglobal.updatesText))
                            self.changeIcon("icon-updates", self.umglobal.updatesText)
                        else:
                            self.umglobal.updatesText = _("There are updates available")
                            print((self.umglobal.updatesText))
                            self.changeIcon("icon-updates", self.umglobal.updatesText)
                    else:
                        print((self.umglobal.connectedText))
                        self.changeIcon("icon-connected", self.umglobal.connectedText)
                else:
                    print((self.umglobal.disconnectedText))
                    self.changeIcon("icon-disconnected", self.umglobal.disconnectedText)
                    # Check every 30 seconds if there is a connection
                    GObject.timeout_add_seconds(30, self.refresh)
                    self.umglobal.getServerInfo()
                    return True
            else:
                self.umglobal.errorText = _("Unable to retrieve sources information")
                print((self.umglobal.errorText))
                self.changeIcon("icon-error", self.umglobal.errorText)

            print("Done refreshing")

    def isAptExecuting(self):
        procLst = self.ec.run("ps -U root -u root -o comm=", False)
        for aptProc in self.umglobal.settings["apt-packages"]:
            if aptProc in procLst:
                return True
        return False

    def checkForUpdates(self):
        # Get updateable packages which are not held back
        cmd = "env LANG=C aptitude search '~U' | awk '{print $2}'"
        updateables = self.ec.run(cmd=cmd, realTime=False)

        if updateables:
            # Get packages that were kept back by the user
            cmd = "env LANG=C dpkg --get-selections | grep hold$ | awk '{print $1}'"
            keptbacks = self.ec.run(cmd=cmd, realTime=False)
            if keptbacks:
                for upd in updateables:
                    if upd not in keptbacks:
                        return True
            else:
                return True
        else:
            return False
