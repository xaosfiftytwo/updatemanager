#! /usr/bin/env python3
#-*- coding: utf-8 -*-

from gi.repository import GdkPixbuf
from execcmd import ExecCmd
from os.path import join, abspath, dirname
import os


class UmRefresh(object):

    def __init__(self, statusIcon, umglobal):
        self.scriptDir = abspath(dirname(__file__))
        self.ec = ExecCmd()
        self.statusIcon = statusIcon
        self.umglobal = umglobal
        self.pbExec = GdkPixbuf.Pixbuf.new_from_file(self.umglobal.settings["icon-exec"])
        self.pbApply = GdkPixbuf.Pixbuf.new_from_file(self.umglobal.settings["icon-apply"])
        self.pbEmergency = GdkPixbuf.Pixbuf.new_from_file(self.umglobal.settings["icon-emergency"])
        self.pbInfo = GdkPixbuf.Pixbuf.new_from_file(self.umglobal.settings["icon-info"])
        self.pbDisconnected = GdkPixbuf.Pixbuf.new_from_file(self.umglobal.settings["icon-disconnected"])
        self.pbError = GdkPixbuf.Pixbuf.new_from_file(self.umglobal.settings["icon-error"])
        self.counter = 0
        self.quit = False

    def refresh(self):
        uptodateText = _("Your system is up to date")
        updavText = _("There are updates available")
        emergencyText = _("There is an emergency update available")
        noConText = _("No internet connection")
        errText = _("Unable to retrieve sources information")
        stableText = _("New stable version available")
        self.counter += 1
        print(("UmRefresh refresh count #: %d" % self.counter))

        self.statusIcon.set_from_pixbuf(self.pbExec)
        self.statusIcon.set_tooltip_text(_("Refreshing..."))

        pid = self.umglobal.getScriptPid("updatemanager.py")
        if pid == 0:
            os.system("rm %s" % join(self.scriptDir, ".um*"))

        self.umglobal.getLocalInfo()
        if self.umglobal.repos:
            if self.counter > 1:
                self.umglobal.getServerInfo()
            if self.umglobal.hasInternet:
                # Check update status
                if self.umglobal.isStable:
                    if self.umglobal.newEmergency:
                        self.statusIcon.set_from_pixbuf(self.pbEmergency)
                        self.statusIcon.set_tooltip_text(emergencyText)
                    elif self.checkForUpdates():
                        if self.umglobal.newStable:
                            self.statusIcon.set_from_pixbuf(self.pbInfo)
                            self.statusIcon.set_tooltip_text(stableText)
                        else:
                            self.statusIcon.set_from_pixbuf(self.pbInfo)
                            self.statusIcon.set_tooltip_text(updavText)
                    else:
                        self.statusIcon.set_from_pixbuf(self.pbApply)
                        self.statusIcon.set_tooltip_text(uptodateText)
                else:
                    if self.umglobal.newEmergency:
                        self.statusIcon.set_from_pixbuf(self.pbEmergency)
                        self.statusIcon.set_tooltip_text(emergencyText)
                    elif self.checkForUpdates():
                        if self.umglobal.newUp:
                            self.statusIcon.set_from_pixbuf(self.pbInfo)
                            self.statusIcon.set_tooltip_text(_("New UP: %s" % self.umglobal.serverUpVersion))
                        else:
                            self.statusIcon.set_from_pixbuf(self.pbInfo)
                            self.statusIcon.set_tooltip_text(updavText)
                    else:
                        self.statusIcon.set_from_pixbuf(self.pbApply)
                        self.statusIcon.set_tooltip_text(uptodateText)
            else:
                self.statusIcon.set_from_pixbuf(self.pbDisconnected)
                self.statusIcon.set_tooltip_text(noConText)
        else:
            self.statusIcon.set_from_pixbuf(self.pbError)
            self.statusIcon.set_tooltip_text(errText)

        print("Done refreshing")

    def checkForUpdates(self):
        cmd = "apt-show-versions -u"
        #cmd = "aptitude search '~U'"

        # Get the output of the command in a list
        lst = self.ec.run(cmd=cmd, realTime=False)

        if lst:
            return True
        else:
            return False
