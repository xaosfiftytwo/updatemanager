#! /usr/bin/env python3
#-*- coding: utf-8 -*-

# Depends: python3-gi, python-vte, gir1.2-vte-2.90

# Password settings
# http://docs.python.org/2/library/spwd.html#module-spwd

# sudo apt-get install python3-gi
# from gi.repository import Gtk, GdkPixbuf, GObject, Pango, Gdk
from gi.repository import Gtk, GLib
import sys
import os
import gettext
# abspath, dirname, join, expanduser, exists, basename
from os.path import join, abspath, dirname, basename
from execcmd import ExecCmd
from treeview import TreeViewHandler
from dialogs import MessageDialogSafe
from mirror import MirrorGetSpeed, Mirror
from queue import Queue
from umglobal import UmGlobal
from logger import Logger


# i18n: http://docs.python.org/2/library/gettext.html
gettext.install("updatemanager", "/usr/share/locale")
#t = gettext.translation("updatemanager", "/usr/share/locale")
#_ = t.lgettext


#class for the main window
class UpdateManagerPref(object):

    def __init__(self):
        # Check if script is running
        self.scriptName = basename(__file__)
        self.umglobal = UmGlobal()
        print((sys.argv[1:]))
        self.user = sys.argv[1:][0].strip()
        if self.user == "root" or self.user == "reload":
            self.user = ""

        # Kill previous instance of UM preferences if it exists
        pid = self.umglobal.getScriptPid(self.scriptName, True)
        if pid > 0:
            # Only load a new instance if there is already an instance running
            # This is used by the installer when upgrading
            if 'reload' in sys.argv[1:]:
                print(("Kill preferences window with pid: %d" % pid))
                os.system("kill %d" % pid)
            else:
                print(("Exit - preferences already running with pid: %d" % pid))
                sys.exit(1)

        # Initiate logging
        self.logFile = join('/var/log', self.umglobal.settings['log'])
        self.log = Logger(self.logFile)

        # Load window and widgets
        self.scriptDir = abspath(dirname(__file__))
        self.filesDir = join(self.scriptDir, "files")
        self.builder = Gtk.Builder()
        self.builder.add_from_file(join(self.scriptDir, '../../../share/solydxk/updatemanager/updatemanagerpref.glade'))

        # Preferences window objects
        go = self.builder.get_object
        self.window = go("windowPref")
        self.window.set_icon_from_file(self.umglobal.settings["icon-base"])
        self.nbPref = go('nbPref')
        self.btnSaveMirrors = go('btnSaveMirrors')
        self.btnCheckMirrorsSpeed = go("btnCheckMirrorsSpeed")
        self.lblMirrors = go('lblMirrors')
        self.tvMirrors = go("tvMirrors")
        self.btnRemoveBlackList = go("btnRemoveBlacklist")
        self.btnAddBlackList = go("btnAddBlacklist")
        self.tvBlacklist = go("tvBlacklist")
        self.tvAvailable = go("tvAvailable")
        self.lblGeneral = go("lblGeneral")
        self.txtUserWait = go("txtUserWait")
        self.txtCheckStatus = go("txtCheckStatus")
        self.btnSaveGeneral = go("btnSaveGeneral")

        # Only allow numbers
        self.filterText(self.txtUserWait)
        self.filterText(self.txtCheckStatus)

        # GUI translations
        self.window.set_title(_("Update Manager Preferfences"))
        self.btnSaveMirrors.set_label(_("Save mirrors"))
        self.btnCheckMirrorsSpeed.set_label(_("Check mirrrors speed"))
        self.btnRemoveBlackList.set_label(_("Remove"))
        self.btnAddBlackList.set_label(_("Blacklist"))
        self.lblMirrors.set_label(_("Repository mirrors"))
        self.lblGeneral.set_label(_("General"))
        go("lblBlacklist").set_label(_("Blacklisted packages"))
        go("lblMirrorsText").set_label(_("Select the fastest production repository"))
        go("lblBlacklistText").set_label(_("Blacklisted packages"))
        go("lblAvailableText").set_label(_("Available packages"))
        go("lblGlobalSettings").set_label(_("Global settings"))
        go("lblUserWait").set_label(_("Wait for user input for"))
        go("lblUserWaitSecs").set_label(_("seconds (0 = disable automatic answering)"))
        go("lblCheckStatus").set_label(_("Check status every"))
        go("lblCheckStatusHour").set_label(_("hours"))

        # Initiate the treeview handler and connect the custom toggle event with on_tvMirrors_toggle
        self.tvMirrorsHandler = TreeViewHandler(self.tvMirrors)
        self.tvMirrorsHandler.connect('checkbox-toggled', self.on_tvMirrors_toggle)

        self.tvBlacklistHandler = TreeViewHandler(self.tvBlacklist)
        self.tvAvailableHandler = TreeViewHandler(self.tvAvailable)

        # Initialize
        self.ec = ExecCmd(loggerObject=self.log)
        self.queue = Queue()
        self.excludeMirrors = ['security']
        self.mirrors = self.getMirrors()
        self.threads = {}
        self.blacklist = []
        self.available = []

        self.fillGeneralSettings()
        self.fillTreeViewMirrors()
        self.fillTreeViewBlackList()
        self.fillTreeViewAvailable()

        # Connect the signals and show the window
        self.builder.connect_signals(self)
        self.window.show()

    # ===============================================
    # Main window functions
    # ===============================================

    def on_btnSaveGeneral_clicked(self, widget):
        self.saveGeneralSettings()

    def on_btnCheckMirrorsSpeed_clicked(self, widget):
        self.checkMirrorsSpeed()

    def on_btnSaveMirrors_clicked(self, widget):
        self.saveMirrors()

    def on_btnCancel_clicked(self, widget):
        self.window.destroy()

    def on_btnRemoveBlacklist_clicked(self, widget):
        self.removeBlacklist()

    def on_btnAddBlacklist_clicked(self, widget):
        self.addBlacklist()


    # ===============================================
    # Blacklist functions
    # ===============================================

    def fillGeneralSettings(self):
        self.txtCheckStatus.set_text(str(self.umglobal.settings["hrs-check-status"]))
        self.txtUserWait.set_text(str(self.umglobal.settings["secs-wait-user-input"]))

    def fillTreeViewBlackList(self):
        self.blacklist = []
        cmd = "dpkg --get-selections | grep hold$ | awk '{print $1}'"
        lst = self.ec.run(cmd, False)
        for pck in lst:
            self.blacklist.append([False, pck.strip()])
        # Fill treeview
        columnTypesList = ['bool', 'str']
        self.tvBlacklistHandler.fillTreeview(self.blacklist, columnTypesList, 0, 400, False)

    def fillTreeViewAvailable(self):
        self.available = []
        cmd = "dpkg --get-selections | grep install$ | awk '{print $1}'"
        lst = self.ec.run(cmd, False)
        for pck in lst:
            self.available.append([False, pck.strip()])
        # Fill treeview
        columnTypesList = ['bool', 'str']
        self.tvAvailableHandler.fillTreeview(self.available, columnTypesList, 0, 400, False)

    def addBlacklist(self):
        packages = self.tvAvailableHandler.getToggledValues()
        for pck in packages:
            self.log.write("Blacklist package: %s" % pck, "UMPref.addBlacklist", "debug")
            cmd = "echo '%s hold' | dpkg --set-selections" % pck
            os.system(cmd)
        self.fillTreeViewBlackList()
        self.fillTreeViewAvailable()

    def removeBlacklist(self):
        packages = self.tvBlacklistHandler.getToggledValues()
        for pck in packages:
            self.log.write("Remove package from blacklist: %s" % pck, "UMPref.removeBlacklist", "debug")
            cmd = "echo '%s install' | dpkg --set-selections" % pck
            os.system(cmd)
        self.fillTreeViewBlackList()
        self.fillTreeViewAvailable()
    # ===============================================
    # Mirror functions
    # ===============================================

    def fillTreeViewMirrors(self):
        # Fill mirror list
        if len(self.mirrors) > 1:
            testing = False
            for repo in self.umglobal.repos:
                for match in self.umglobal.settings["testing-repo-matches"]:
                    if match in repo:
                        testing = True
                        break
            if testing:
                msg = _("You are pointing to the testing repositories.\n\n"
                        "Only production repositories do have mirrors.\n"
                        "Please change to production manually.")
                self.showInfo(self.lblMirrors.get_label(), msg, self.window)
                self.nbPref.get_nth_page(1).set_visible(False)
            else:
                # Fill treeview
                columnTypesList = ['bool', 'str', 'str', 'str', 'str']
                self.tvMirrorsHandler.fillTreeview(self.mirrors, columnTypesList, 0, 400, True)
                self.nbPref.get_nth_page(1).set_visible(True)
        else:
            self.nbPref.get_nth_page(1).set_visible(False)

    def saveMirrors(self):
        # Safe mirror settings
        replaceRepos = []
        # Get user selected mirrors
        model = self.tvMirrors.get_model()
        itr = model.get_iter_first()
        while itr is not None:
            sel = model.get_value(itr, 0)
            if sel:
                repo = model.get_value(itr, 2)
                url = model.get_value(itr, 3)
                # Get currently selected data
                for mirror in self.mirrors:
                    if mirror[0] and mirror[2] == repo and mirror[3] != url:
                        # Currently selected mirror
                        replaceRepos.append([mirror[3], url])
                        break
            itr = model.iter_next(itr)

        if replaceRepos:
            self.btnSaveMirrors.set_sensitive(False)
            self.btnCheckMirrorsSpeed.set_sensitive(False)
            cmd = "touch %s" % join(self.filesDir, ".umrefresh")
            os.system(cmd)

            m = Mirror()
            m.save(replaceRepos, self.excludeMirrors)
            self.ec.run(cmd="apt-get update", outputTreeView=self.tvMirrors)
            self.umglobal.getLocalInfo()
            self.mirrors = self.getMirrors()
            self.fillTreeViewMirrors()

            cmd = "rm -f %s" % join(self.filesDir, ".umrefresh")
            os.system(cmd)
            self.btnSaveMirrors.set_sensitive(True)
            self.btnCheckMirrorsSpeed.set_sensitive(True)

    def getMirrors(self):
        mirrors = [[_("Current"), _("Country"), _("Repository"), _("URL"), _("Speed")]]
        mirrorData = self.umglobal.getMirrorData(self.excludeMirrors)
        for mirror in  mirrorData:
            if mirror:
                self.log.write("Mirror data: %s" % ' '.join(mirror), "UMPref.getMirrors", "debug")
                if self.umglobal.isStable:
                    if mirror[1].lower() == 'business':
                        blnCurrent = self.isUrlInSources(mirror[2])
                        mirrors.append([blnCurrent, mirror[0], mirror[1], mirror[2], ''])
                else:
                    if mirror[1].lower() != 'business':
                        blnCurrent = self.isUrlInSources(mirror[2])
                        mirrors.append([blnCurrent, mirror[0], mirror[1], mirror[2], ''])
        return mirrors

    def isUrlInSources(self, url):
        blnRet = False
        for repo in self.umglobal.repos:
            if url in repo:
                #print((">>> add %s" % url))
                blnRet = True
                for excl in self.excludeMirrors:
                    #print((">>> excl=%s - repo=%s" % (excl, repo)))
                    if excl in repo:
                        #print(">>> skip")
                        blnRet = False
                        break
                break
        return blnRet

    def checkMirrorsSpeed(self):
        name = 'mirrorspeed'
        self.btnCheckMirrorsSpeed.set_sensitive(False)
        self.btnSaveMirrors.set_sensitive(False)
        t = MirrorGetSpeed(self.mirrors, self.queue, self.umglobal)
        self.threads[name] = t
        t.daemon = True
        t.start()
        self.queue.join()
        GLib.timeout_add(5, self.checkThread, name)

    def checkThread(self, name):
        if self.threads[name].is_alive():
            lst = self.queue.get()
            if lst:
                self.writeSpeed(lst[0], lst[1])
            return True

        # Thread is done
        del self.threads[name]
        self.btnCheckMirrorsSpeed.set_sensitive(True)
        self.btnSaveMirrors.set_sensitive(True)
        return False

    def writeSpeed(self, url, speed):
        model = self.tvMirrors.get_model()
        itr = model.get_iter_first()
        while itr is not None:
            repo = model.get_value(itr, 3)
            if repo == url:
                self.log.write("Mirror speed for %s = %s" % (url, speed), "UMPref.writeSpeed", "debug")
                model.set_value(itr, 4, speed)
            itr = model.iter_next(itr)
        self.tvMirrors.set_model(model)
        # Repaint GUI, or the update won't show
        while Gtk.events_pending():
            Gtk.main_iteration()

    def on_tvMirrors_toggle(self, obj, path, colNr, toggleValue):
        path = int(path)
        model = self.tvMirrors.get_model()
        selectedIter = model.get_iter(path)
        selectedRepo = model.get_value(selectedIter, 2)

        rowCnt = 0
        itr = model.get_iter_first()
        while itr is not None:
            if rowCnt != path:
                repo = model.get_value(itr, 2)
                if repo == selectedRepo:
                    model[itr][0] = False
            itr = model.iter_next(itr)
            rowCnt += 1

    # ===============================================
    # General functions
    # ===============================================

    def saveGeneralSettings(self):
        #print("> saveGeneralSettings")
        ui_saved = False
        cs_saved = False
        secs = self.umglobal.strToNumber(self.txtUserWait.get_text(), True)
        #print(secs)
        if self.umglobal.settings["secs-wait-user-input"] != secs:
            #print("> save secs-wait-user-input 1")
            self.umglobal.saveSettings('misc', 'secs-wait-user-input', secs)
            ui_saved = True
            #print("> save secs-wait-user-input 2")
        hrs = self.umglobal.strToNumber(self.txtCheckStatus.get_text(), True)
        #print(hrs)
        if self.umglobal.settings["hrs-check-status"] != hrs:
            #print("> save hrs-check-status 1")
            self.umglobal.saveSettings('misc', 'hrs-check-status', hrs)
            cs_saved = True
            #print("> save hrs-check-status 2")
        if ui_saved or cs_saved:
            msg = _("The new settings will take effect after UM restart.")
            self.showInfo(self.lblGeneral.get_label(), msg, self.window)
        else:
            msg = _("No changes were made.")
            self.showInfo(self.lblGeneral.get_label(), msg, self.window)

    def filterText(self, widget):
        def filter(entry, *args):
            text = entry.get_text().strip().lower()
            entry.set_text(''.join([i for i in text if i in '0123456789']))
        widget.connect('changed', filter)

    def showInfo(self, title, message, parent):
        MessageDialogSafe(title, message, Gtk.MessageType.INFO, parent).show()

    # Close the gui
    def on_windowPref_destroy(self, widget):
        Gtk.main_quit()

if __name__ == '__main__':
    # Create an instance of our GTK application
    try:
        UpdateManagerPref()
        Gtk.main()
    except KeyboardInterrupt:
        pass
