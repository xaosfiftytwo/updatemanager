#! /usr/bin/env python3

# Depends: python3-pyinotify
# Documentation: http://pyinotify.sourceforge.net/

import pyinotify
from gi.repository import GObject

# i18n: http://docs.python.org/3/library/gettext.html
import gettext
from gettext import gettext as _
gettext.textdomain('updatemanager')


class EventHandler(pyinotify.ProcessEvent):
    def __init__(self, umrefresh):
        self.executing = False
        self.umrefresh = umrefresh

    def process_IN_CREATE(self, event):
        #print((">>> process_IN_CREATE: %s" % event.pathname))
        if not self.executing:
            if event.pathname == self.umrefresh.umglobal.umfiles['umrefresh']:
                print(("Creating: %s" % event.pathname))
                self.executing = True
                # You cannot handle GUI changes in a thread
                # Use idle_add to let the calling thread handle GUI stuff when there's time left
                GObject.idle_add(self.changeIcon, "icon-execute", _("Refreshing update list..."))
            if not self.executing:
                if event.pathname == self.umrefresh.umglobal.umfiles['umupd']:
                    print(("Creating: %s" % event.pathname))
                    self.executing = True
                    GObject.idle_add(self.changeIcon, "icon-execute", _("Installing updates..."))

    def process_IN_DELETE(self, event):
        #print((">>> process_IN_DELETE: %s" % event.pathname))
        if event.pathname == self.umrefresh.umglobal.umfiles['umupd'] or \
           event.pathname == self.umrefresh.umglobal.umfiles['umrefresh']:
            print(("Deleting: %s" % event.pathname))
            self.executing = False
            GObject.idle_add(self.refresh)

    def process_IN_MODIFY(self, event):
        #print((">>> process_IN_MODIFY: %s" % event.pathname))
        if '/sources.list' in event.pathname:
            print(("Modifying: %s" % event.pathname))
            self.umrefresh.umglobal.warningText = _("Sources changed: start UM to refresh")
            GObject.idle_add(self.changeIcon, "icon-warning", self.umrefresh.umglobal.warningText)

    def process_IN_CLOSE_WRITE(self, event):
        #print((">>> process_IN_CLOSE_WRITE: %s" % event.pathname))
        if event.pathname == '/var/cache/apt/pkgcache.bin':
            print(("Closing: %s" % event.pathname))
            self.executing = True
            GObject.idle_add(self.refresh)

    def changeIcon(self, iconName, tooltip):
        self.umrefresh.changeIcon(iconName, tooltip)

    def refresh(self):
        self.umrefresh.refresh()


class UmNotifier(object):

    def __init__(self, umrefresh):

        self.umrefresh = umrefresh

        self.wm = pyinotify.WatchManager()  # Watch Manager
        self.notifier = pyinotify.ThreadedNotifier(self.wm, EventHandler(self.umrefresh))
        self.notifier.start()

        # IN_ACCESS           File was accessed (read)
        # IN_ATTRIB           Metadata changed (permissions, timestamps, extended attributes, etc.)
        # IN_CLOSE_WRITE      File opened for writing was closed
        # IN_CLOSE_NOWRITE    File not opened for writing was closed
        # IN_CREATE           File/directory created in watched directory
        # IN_DELETE           File/directory deleted from watched directory
        # IN_DELETE_SELF      Watched file/directory was itself deleted
        # IN_MODIFY           File was modified
        # IN_MOVE_SELF        Watched file/directory was itself moved
        # IN_MOVED_FROM       File moved out of watched directory
        # IN_MOVED_TO         File moved into watched directory
        # IN_OPEN             File was opened

        # rec = recursion - if set to True, sub directories are included
        src = '/etc/apt/sources.list'
        apt = '/var/cache/apt/'
        self.srcWatch = self.wm.add_watch(src, pyinotify.IN_MODIFY, rec=False)
        self.srcdWatch = self.wm.add_watch("%s.d/" % src, pyinotify.IN_MODIFY, rec=False)
        self.umWatch = self.wm.add_watch(self.umrefresh.umglobal.filesDir, pyinotify.IN_CREATE | pyinotify.IN_DELETE, rec=False)
        self.aptWatch = self.wm.add_watch(apt, pyinotify.IN_CLOSE_WRITE, rec=False)
        print("Added file watches on %s, %s.d/, %s, %s" % (src, src, self.umrefresh.umglobal.filesDir, apt))

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
