#! /usr/bin/env python3

# Depends: python3-pyinotify
# Documentation: http://pyinotify.sourceforge.net/

import pyinotify
from os.path import join
from gi.repository import GObject

# Need to initiate threads for Gtk,
# or else EventHandler will not get called from ThreadedNotifier
GObject.threads_init()

# i18n: http://docs.python.org/3/library/gettext.html
import gettext
from gettext import gettext as _
gettext.textdomain('updatemanager')


class EventHandler(pyinotify.ProcessEvent):
    def __init__(self, umglobal, umrefresh, indicator):
        self.executing = False
        self.indicator = indicator
        self.umglobal = umglobal
        self.umrefresh = umrefresh

    def process_IN_CREATE(self, event):
        #print((">>> process_IN_CREATE: %s" % event.pathname))
        if not self.executing:
            if event.pathname == self.umglobal.umfiles['umrefresh']:
                print(("Creating: %s" % event.pathname))
                self.executing = True
                # You cannot handle GUI changes in a thread
                # Use idle_add to let the calling thread handle GUI stuff when there's time left
                GObject.idle_add(self.changeIcon, "icon-execute", _("Refreshing update list..."))
            if not self.executing:
                if event.pathname == self.umglobal.umfiles['umupd']:
                    print(("Creating: %s" % event.pathname))
                    self.executing = True
                    GObject.idle_add(self.changeIcon, "icon-execute", _("Installing updates..."))

    def process_IN_DELETE(self, event):
        #print((">>> process_IN_DELETE: %s" % event.pathname))
        if event.pathname == self.umglobal.umfiles['umupd'] or \
           event.pathname == self.umglobal.umfiles['umrefresh']:
            print(("Deleting: %s" % event.pathname))
            self.executing = False
            GObject.idle_add(self.refresh)

    def process_IN_MODIFY(self, event):
        if '/sources.list' in event.pathname:
            print(("Modifying: %s" % event.pathname))
            self.umglobal.warningText = _("Sources changed: start UM to refresh")
            GObject.idle_add(self.changeIcon, "icon-warning", self.umglobal.warningText)
        elif 'pkgcache.bin' in event.pathname:
            print(("Modifying: %s" % event.pathname))
            GObject.idle_add(self.refresh)

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
        self.umrefresh.refresh()


class UmNotifier(object):

    def __init__(self, umglobal, umrefresh, indicator):
        self.indicator = indicator
        self.umglobal = umglobal
        self.umrefresh = umrefresh

        self.wm = pyinotify.WatchManager()  # Watch Manager
        self.notifier = pyinotify.ThreadedNotifier(self.wm, EventHandler(self.umglobal, self.umrefresh, self.indicator))
        self.notifier.start()

        # rec = recursion - if set to True, sub directories are included
        src = '/etc/apt/sources.list'
        apt = '/var/cache/apt/pkgcache.bin'
        self.srcWatch = self.wm.add_watch(src, pyinotify.IN_MODIFY, rec=False)
        self.srcdWatch = self.wm.add_watch("%s.d/" % src, pyinotify.IN_MODIFY, rec=False)
        self.umWatch = self.wm.add_watch(self.umglobal.filesDir, pyinotify.IN_CREATE | pyinotify.IN_DELETE, rec=False)
        self.aptWatch = self.wm.add_watch(apt, pyinotify.IN_MODIFY, rec=False)
        #self.lockWatch = self.wm.add_watch('/var/lib/dpkg/lock', pyinotify.IN_CLOSE_NOWRITE, rec=False)
        print("Added file watches on %s, %s.d/, %s, %s" % (src, src, self.umglobal.filesDir, apt))

    def quit(self):
        #print("Quit UmNotifier")
        try:
            self.wm.rm_watch(list(self.srcWatch.values()))
            self.wm.rm_watch(list(self.srcdWatch.values()))
            self.wm.rm_watch(list(self.umWatch.values()))
            self.wm.rm_watch(list(self.aptWatch.values()))
            #self.wm.rm_watch(list(self.lockWatch.values()))
            self.notifier.stop()
        except Exception as details:
            print(("Exception while quitting UmNotifier: %s" % details))
