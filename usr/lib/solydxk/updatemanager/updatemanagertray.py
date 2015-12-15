#! /usr/bin/env python3

# Depends: gir1.2-appindicator3-0.1
# Documentation: http://lazka.github.io/pgi-docs/AppIndicator3-0.1

# Make sure the right Gtk and AppIndicator3 version is loaded
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')

from gi.repository import Gtk, Gdk, GObject, AppIndicator3
import threading
import argparse
import os
from umglobal import UmGlobal
from umnotifier import UmNotifier
from umrefresh import UmRefresh
from os.path import basename, join
from dialogs import MessageDialog
from execcmd import ExecCmd

# i18n: http://docs.python.org/3/library/gettext.html
import gettext
from gettext import gettext as _
gettext.textdomain('updatemanager')

# Need to initiate threads for Gtk
GObject.threads_init()


class UpdateManagerTray(object):

    def __init__(self):
        # Check if script is running
        self.scriptName = basename(__file__)
        self.umglobal = UmGlobal()
        self.ec = ExecCmd()
        self.status = AppIndicator3.IndicatorStatus

        # Load window and widgets
        self.builder = Gtk.Builder()
        self.builder.add_from_file(join(self.umglobal.shareDir, 'updatemanagerlegend.glade'))
        go = self.builder.get_object
        # Main window objects
        self.legend = go("windowLegenda")
        go("imgConnected").set_from_file(join(self.umglobal.iconsDir, self.umglobal.settings["icon-connected"]))
        go("imgDisconnected").set_from_file(join(self.umglobal.iconsDir, self.umglobal.settings["icon-disconnected"]))
        go("imgError").set_from_file(join(self.umglobal.iconsDir, self.umglobal.settings["icon-error"]))
        go("imgExecute").set_from_file(join(self.umglobal.iconsDir, self.umglobal.settings["icon-execute"]))
        go("imgUpdates").set_from_file(join(self.umglobal.iconsDir, self.umglobal.settings["icon-updates"]))
        go("imgWarning").set_from_file(join(self.umglobal.iconsDir, self.umglobal.settings["icon-warning"]))
        go("lblConnected").set_label(self.umglobal.connectedText)
        go("lblDisconnected").set_label(self.umglobal.disconnectedText)
        go("lblExecute").set_label(self.umglobal.executeText)
        self.lblError = go("lblError")
        self.lblWarning = go("lblWarning")
        self.lblUpdates = go("lblUpdates")
        self.builder.connect_signals(self)

        # Handle arguments
        parser = argparse.ArgumentParser(description='SolydXK Update Manager Tray')
        parser.add_argument('-r','--reload', action="store_true", help='')
        args, extra = parser.parse_known_args()

        #print((">> args = {}".format(args)))
        if args.reload:
            pids = self.umglobal.getProcessPids("updatemanagertray.py")
            if len(pids) > 1:
                print(("updatemanagertray.py already running - kill pid {}".format(pids[0])))
                os.system("kill {}".format(pids[0]))

        # Build status icon menu
        self.quitText = _("Quit")
        menu = Gtk.Menu()
        menuUm = Gtk.MenuItem(self.umglobal.title)
        menuUm.connect('activate', self.open_um)
        menu.append(menuUm)
        # Separator not functioning in wheezy
        menuSep1 = Gtk.SeparatorMenuItem()
        menu.append(menuSep1)
        menuQupd = Gtk.MenuItem(_("Quick Update"))
        menuQupd.connect('activate', self.quick_update)
        menu.append(menuQupd)
        menuSep2 = Gtk.SeparatorMenuItem()
        menu.append(menuSep2)
        menuPref = Gtk.MenuItem(_("Preferences"))
        menuPref.connect('activate', self.open_preferences)
        menu.append(menuPref)
        menuLegend = Gtk.MenuItem(_("Legend"))
        menuLegend.connect('activate', self.open_legend)
        menu.append(menuLegend)
        menuQuit = Gtk.MenuItem(self.quitText)
        menuQuit.connect('activate', self.quit_tray)
        menu.append(menuQuit)
        menu.show_all()

        if self.umglobal.isKf5:
            print(("> Running KDE5"))
            # Use this for KDE5
            self.indicator = AppIndicator3.Indicator.new_with_path("updatemanager",
                                                              self.umglobal.settings["icon-connected"],
                                                              AppIndicator3.IndicatorCategory.SYSTEM_SERVICES,
                                                              self.umglobal.iconsDir)
            # Title not showing in KDE4
            self.indicator.set_title("<strong>{}</strong>".format(self.umglobal.title))
            self.indicator.set_secondary_activate_target(menuUm)
            self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self.indicator.set_menu(menu)
        else:
            print(("> Running KDE4"))
            # Use this for KDE4
            self.indicator = Gtk.StatusIcon()
            #self.indicator.connect('activate', self.open_um)
            self.indicator.connect('popup-menu', self.popup_menu, menu)

        self.umrefresh = UmRefresh(self.umglobal, self.indicator)
        self.notifier = UmNotifier(self.umglobal, self.umrefresh, self.indicator)

        # Initiate first check
        self.refresh()

    def refresh(self, widget=None):
        if not self.umglobal.isProcessRunning("updatemanager.py"):
            self.umrefresh.refresh()
        # Return True or timeout_add_seconds will only run once
        return True

    def popup_menu(self, widget, button, time, data):
        data.show_all()
        data.popup(None, None, None, None, button, time)

    def open_um(self, widget):
        if not self.umglobal.isProcessRunning("updatemanager.py"):
            # Run UM in its own thread
            pref_thread = threading.Thread(target=self.ec.run, args=("updatemanager",))
            pref_thread.setDaemon(True)
            pref_thread.start()

    def quick_update(self, widget):
        if not self.umglobal.isProcessRunning("updatemanager.py"):
            parm = ""
            if not self.umglobal.newUpd:
                # Quick update
                parm = " -q"
            # Run UM in its own thread
            pref_thread = threading.Thread(target=self.ec.run, args=("updatemanager{}".format(parm),))
            pref_thread.setDaemon(True)
            pref_thread.start()

    def open_preferences(self, widget):
        # Run preferences in its own thread
        if not self.umglobal.isProcessRunning("updatemanagerpref.py"):
            pref_thread = threading.Thread(target=self.ec.run, args=("updatemanager -p",))
            pref_thread.setDaemon(True)
            pref_thread.start()

    def quit_tray(self, widget):
        if self.umglobal.isUpgrading():
            MessageDialog(self.quitText, _("Cannot quit: upgrade in progress"))
        else:
            self.umglobal.killScriptProcess("updatemanager.py")
            self.umglobal.killScriptProcess("updatemanagerpref.py")
            self.notifier.quit()
            Gtk.main_quit()

    # Show the legend window
    def open_legend(self, widget):
        self.lblError.set_label(self.umglobal.errorText)
        self.lblUpdates.set_label(self.umglobal.updatesText)
        self.lblWarning.set_label(self.umglobal.warningText)
        self.legend.show_all()

    # Hide the legend window when mouse leaves the window
    def on_windowLegenda_leave_notify_event(self, widget, event):
        if event.detail != Gdk.NotifyType.NONLINEAR:
            return False
        self.legend.hide()


if __name__ == '__main__':
    # Create an instance of our GTK application
    try:
        UpdateManagerTray()
        Gtk.main()
    except KeyboardInterrupt:
        pass
