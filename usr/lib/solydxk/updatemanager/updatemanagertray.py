#! /usr/bin/env python3
#-*- coding: utf-8 -*-

from gi.repository import Gtk, GObject
import sys
import os
import gettext
import threading
from umglobal import UmGlobal
from umnotifier import UmNotifier
from umrefresh import UmRefresh
from os.path import join, abspath, dirname, exists, basename
from dialogs import MessageDialogSafe
from execcmd import ExecCmd

# i18n: http://docs.python.org/2/library/gettext.html
gettext.install("updatemanager", "/usr/share/locale")
#t = gettext.translation("updatemanager", "/usr/share/locale")
#_ = t.gettext

# Need to initiate threads for Gtk
GObject.threads_init()


class UpdateManagerTray(object):

    def __init__(self):
        # Check if script is running
        self.scriptDir = abspath(dirname(__file__))
        self.filesDir = join(self.scriptDir, "files")
        self.scriptName = basename(__file__)
        self.umglobal = UmGlobal()
        self.ec = ExecCmd()

        # Kill previous instance of UM tray if it exists
        pid = self.umglobal.getScriptPid(self.scriptName, True)
        #print((">>> tray pid: %d" % pid))
        if pid > 0:
            print((sys.argv[1:]))
            if 'reload' in sys.argv[1:]:
                print(("Kill UM tray with pid: %d" % pid))
                os.system("kill %d" % pid)
            else:
                print(("Exit - UM tray already running with pid: %d" % pid))
                sys.exit(1)

        # Build status icon menu
        self.refreshText = _("Refresh")
        self.quitText = _("Quit")
        menu = Gtk.Menu()
        menuUm = Gtk.MenuItem(_("Update Manager"))
        menuUm.connect('activate', self.icon_activate)
        menu.append(menuUm)
        # Separator not functioning in wheezy
        #menuSep1 = Gtk.SeparatorMenuItem()
        #menu.append(menuSep1)
        menuPref = Gtk.MenuItem(_("Preferences"))
        menuPref.connect('activate', self.open_preferences)
        menu.append(menuPref)
        menuRefresh = Gtk.MenuItem(self.refreshText)
        menuRefresh.connect('activate', self.manualRefresh)
        menu.append(menuRefresh)
        menuQuit = Gtk.MenuItem(self.quitText)
        menuQuit.connect('activate', self.quit_tray)
        menu.append(menuQuit)

        self.statusIcon = Gtk.StatusIcon()
        self.umrefresh = UmRefresh(self.statusIcon, self.umglobal)
        self.notifier = UmNotifier(self.statusIcon, self.umglobal, self.umrefresh)

        self.statusIcon.connect('activate', self.icon_activate)
        self.statusIcon.connect('popup-menu', self.popup_menu, menu)

        # Initiate first check
        self.refresh()

        # Loop the refresh function
        # For some reason you cannot start a threaded class from init
        self.timeout = int(self.umglobal.settings["hrs-check-status"] * 60 * 60)
        GObject.timeout_add_seconds(self.timeout, self.refresh)

    def refresh(self, widget=None):
        self.umrefresh.refresh()
        # Return True or timeout_add_seconds will only run once
        return True

    def manualRefresh(self, widget=None):
        self.umrefresh.refresh()
        self.showInfoDlg(self.refreshText, _("Refresh finished"))

    def popup_menu(self, widget, button, time, data):
        data.show_all()
        data.popup(None, None, None, None, button, time)

    def icon_activate(self, widget):
        if self.umglobal.getScriptPid("updatemanager.py")  == 0:
            # Run UM in its own thread
            pref_thread = threading.Thread(target=self.ec.run, args=("updatemanager",))
            pref_thread.setDaemon(True)
            pref_thread.start()

    def open_preferences(self, widget):
        # Run preferences in its own thread
        pref_thread = threading.Thread(target=self.ec.run, args=("updatemanager -p",))
        pref_thread.setDaemon(True)
        pref_thread.start()

    def showInfoDlg(self, title, message):
        MessageDialogSafe(title, message, Gtk.MessageType.INFO, None).show()

    def quit_tray(self, widget):
        if exists(join(self.filesDir, ".uminstall")):
            self.showInfoDlg(self.quitText, _("Cannot quit: upgrade in progress"))
        else:
            msg = _('Please enter your password')
            pids = []
            pids.append(self.umglobal.getScriptPid("updatemanager.py"))
            pids.append(self.umglobal.getScriptPid("updatemanagerpref.py"))
            if pids:
                execCmd = False
                cmd = "gksudo --message \"<b>%s</b>\" kill" % msg
                for pid in pids:
                    if pid > 0:
                        execCmd = True
                        cmd += " %d" % pid
                print(cmd)
                if execCmd:
                    os.system(cmd)
            self.notifier.quit()
            Gtk.main_quit()

if __name__ == '__main__':
    # Create an instance of our GTK application
    try:
        UpdateManagerTray()
        Gtk.main()
    except KeyboardInterrupt:
        pass
