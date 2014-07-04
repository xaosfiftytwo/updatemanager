#! /usr/bin/env python3
#-*- coding: utf-8 -*-

# Depends: apt-show-versions, python3-gi, python-vte, gir1.2-vte-2.90, gir1.2-webkit-3.0, python3-pyinotify

# from gi.repository import Gtk, GdkPixbuf, GObject, Pango, Gdk
from gi.repository import Gtk, Gdk, GObject
import sys
import os
from os import remove, access, chmod, makedirs
from shutil import move
import gettext
import threading
# abspath, dirname, join, expanduser, exists, basename
from os.path import join, abspath, dirname, exists, basename
from execcmd import ExecCmd
from treeview import TreeViewHandler
from dialogs import MessageDialogSafe, QuestionDialog, CustomQuestionDialog
from umapt import UmApt
from logger import Logger
from urllib.request import urlopen
from glob import glob
from terminal import VirtualTerminal
from umglobal import UmGlobal
from simplebrowser import SimpleBrowser

# i18n: http://docs.python.org/2/library/gettext.html
gettext.install("updatemanager", "/usr/share/locale")
#t = gettext.translation("updatemanager", "/usr/share/locale")
#_ = t.lgettext

# Need to initiate threads for Gtk
GObject.threads_init()


#class for the main window
class UpdateManager(object):

    def __init__(self):
        # Check if script is running
        self.scriptName = basename(__file__)
        self.umglobal = UmGlobal()
        print((sys.argv[1:]))
        self.user = sys.argv[1:][0].strip()
        if self.user == "root" or self.user == "reload":
            self.user = ""

        # Kill previous instance of UM if it exists
        pid = self.umglobal.getScriptPid(self.scriptName, True)
        if pid > 0:
            if 'reload' in sys.argv[1:]:
                # Only load a new instance if there is already an instance running
                # This is used by the installer when upgrading
                print(("Kill update manager window with pid: %d" % pid))
                os.system("kill %d" % pid)
            else:
                print(("Exit - UM already running with pid: %d" % pid))
                sys.exit(1)

        # Load window and widgets
        self.scriptDir = abspath(dirname(__file__))
        self.filesDir = join(self.scriptDir, "files")
        self.builder = Gtk.Builder()
        self.builder.add_from_file(join(self.scriptDir, '../../../share/solydxk/updatemanager/updatemanager.glade'))

        # Make sure the files directory is set correctly
        self.checkFilesDir()

        # Main window objects
        go = self.builder.get_object
        self.window = go("windowMain")
        self.window.set_icon_from_file(self.umglobal.settings["icon-base"])
        self.tvPck = go("tvPck")
        self.swTerminal = go("swTerminal")
        self.statusbar = go("statusbar")
        self.btnInstall = go("btnInstall")
        self.btnRefresh = go("btnRefresh")
        self.btnPackages = go("btnPackages")
        self.btnOutput = go("btnOutput")
        self.btnInfo = go("btnInfo")
        self.btnPreferences = go("btnPreferences")
        self.nbMain = go("nbMain")
        self.swInfo = go("swInfo")
        self.btnMaintenance = go("btnMaintenance")
        self.lblMaintenance = go("lblMaintenance")
        self.tvMaintenance = go("tvMaintenance")
        self.btnMaintenanceExecute = go("btnMaintenanceExecute")
        self.chkMaintenanceSelectAll = go("chkMaintenanceSelectAll")
        self.radUnneeded = go("radUnneeded")
        self.radCleanCache = go("radCleanCache")
        self.radDowngradable = go("radDowngradable")
        self.radNotavailable = go("radNotavailable")
        self.radOldKernel = go("radOldKernel")
        self.lblMaintenanceHelp = go("lblMaintenanceHelp")

        # Translations
        self.window.set_title(_("SolydXK Update Manager"))
        self.btnInstall.set_label(_("Install"))
        self.btnRefresh.set_label(_("Refresh"))
        self.btnOutput.set_label(_("Output"))
        self.btnInfo.set_label(_("Information"))
        self.btnPreferences.set_label(_("Preferences"))
        self.btnPackages.set_label(_("Packages"))
        self.uptodateText = _("Your system is up to date")
        self.lblMaintenance.set_label(_("Maintenance"))
        self.btnMaintenanceExecute.set_label(_("Execute"))
        self.chkMaintenanceSelectAll.set_label(_("Select all"))
        self.radUnneeded.set_label(_("Not needed"))
        self.radCleanCache.set_label(_("Clean cache"))
        self.radDowngradable.set_label(_("Downgrade"))
        self.radNotavailable.set_label(_("Not available"))
        self.radOldKernel.set_label(_("Old kernels"))
        go("lblUnneeded").set_label(_("Remove not needed packages."))
        go("lblCleanCache").set_label(_("Clean up the apt cache."))
        go("lblDowngradable").set_label(_("Only lower version is available."))
        go("lblNotavailable").set_label(_("Packages not in the repositories."))
        go("lblOldKernel").set_label(_("Remove old kernels."))
        self.lblMaintenanceHelp.set_label(_("Make sure you create\n"
                                             "a system image before you\n"
                                             "continue (e.g. Clonezilla)."))

        self.upgradablePackagesText = _("The following packages will be upgraded:")
        self.newPackagesText = _("The following NEW packages will be installed:")
        self.removedPackagesText = _("The following packages will be REMOVED:")
        self.heldbackPackagesText = _("The following packages have been kept back:")
        self.downgradePackagesText = _("The following packages are going to be downgraded:")

        # Cleanup first
        for fle in glob(join(self.filesDir, '.um*')):
            remove(fle)

        # Initiate logging
        self.logFile = join('/var/log', self.umglobal.settings['log'])
        print(("UM log = %s" % self.logFile))
        if access(self.logFile, os.W_OK):
            remove(self.logFile)
        self.log = Logger(self.logFile)

        # VTE Terminal
        self.terminal = VirtualTerminal(maxWaitForAnswer=self.umglobal.settings['secs-wait-user-input'])
        self.swTerminal.add(self.terminal)
        self.terminal.set_vexpand(True)
        self.terminal.set_hexpand(True)
        self.terminal.connect('command-done', self.on_command_done)
        self.terminal.connect('line-added', self.on_line_added)
        self.terminal.connect('waiting-for-answer', self.on_waiting_for_answer)
        if self.umglobal.isStable:
            self.terminal.setTerminalColors("#000000", "#FFFFFF")
        else:
            palletList = ['#4A4A4A', '#BD1919', '#118011', '#CE6800', '#1919BC', '#8D138D', '#139494', '#A7A7A7']
            self.terminal.setTerminalColors("#000000", "#FFFFFF", palletList)
        self.swTerminal.modify_bg(Gtk.StateType.NORMAL, Gdk.color_parse("#FFFFFF"))

        # Disable all buttons
        self.btnInfo.set_sensitive(False)
        self.btnPreferences.set_sensitive(False)
        self.btnOutput.set_sensitive(False)
        self.btnRefresh.set_sensitive(False)
        self.btnInstall.set_sensitive(False)
        self.btnPackages.set_sensitive(False)
        self.btnMaintenance.set_sensitive(False)

        # Hide tabs if needed
        for tab in self.umglobal.settings["hide-tabs"]:
            if tab == "packages":
                self.nbMain.get_nth_page(0).set_visible(False)
                self.btnPackages.set_visible(False)
            elif tab == "output":
                self.nbMain.get_nth_page(1).set_visible(False)
                self.btnOutput.set_visible(False)
            elif tab == "info":
                self.nbMain.get_nth_page(2).set_visible(False)
                self.btnInfo.set_visible(False)
            elif tab == "maintenance":
                self.nbMain.get_nth_page(3).set_visible(False)
                self.btnMaintenance.set_visible(False)

        # Connect the signals and show the window
        self.builder.connect_signals(self)
        self.window.show()

        # Force the window to show
        while Gtk.events_pending():
            Gtk.main_iteration()

        # Just show something that we're busy
        msg = _("Gathering information...")
        self.terminal.executeCommand('echo "%s"' % msg, 'init')
        self.showOutput()

        # Initialize
        self.ec = ExecCmd(loggerObject=self.log)
        self.apt = UmApt(self.umglobal)
        self.kernelVersion = self.umglobal.getKernelVersion().split("-")[0]
        self.upgradables = []
        self.upgradableUM = []
        self.tvHandler = TreeViewHandler(self.tvPck)
        self.tvMaintenanceHandler = TreeViewHandler(self.tvMaintenance)

        # Version information
        ver = _("Version")
        pckVer = self.apt.getPackageVersion('updatemanager')
        up = _("UP")
        versionInfo = "%(ver)s: %(pckVer)s\t%(up)s: %(upVer)s" % { "ver": ver, "pckVer": pckVer, "up": up, "upVer": self.umglobal.localUpVersion }
        self.pushMessage(versionInfo)

        # Log basic information
        self.log.write("==============================================", "UM.init", "debug")
        self.log.write("UM version = %s" % versionInfo, "UM.init", "debug")
        if self.umglobal.isStable:
            if self.umglobal.newNewStable:
                self.log.write("UM localNewStable = %s, serverNewStable = %s, newNewStable = %s" % (self.umglobal.localNewStableVersion, self.umglobal.serverNewStableVersion, str(self.umglobal.newNewStable)), "UM.init", "debug")
            else:
                self.log.write("UM localStable = %s, serverStable = %s, newStable = %s" % (self.umglobal.localStableVersion, self.umglobal.serverStableVersion, str(self.umglobal.newStable)), "UM.init", "debug")
        else:
            self.log.write("UM localUp = %s, serverUp = %s, newUp = %s" % (self.umglobal.localUpVersion, self.umglobal.serverUpVersion, str(self.umglobal.newUp)), "UM.init", "debug")
        self.log.write("UM localEmergency = %s, serverEmergency = %s, newEmergency = %s" % (self.umglobal.localEmergencyVersion, self.umglobal.serverEmergencyVersion, str(self.umglobal.newEmergency)), "UM.init", "debug")
        self.log.write("==============================================", "UM.init", "debug")
        mirrorsList = join(self.filesDir, basename(self.umglobal.settings["mirrors-list"]))
        if exists(mirrorsList):
            self.log.write("Mirrors list", "UM.init", "debug")
            with open(mirrorsList, 'r') as f:
                for line in f.readlines():
                    self.log.write(line, "UM.init", "debug")
            self.log.write("==============================================", "UM.init", "debug")

        # Load the initial information page
        self.loadInfo()

        # Refresh apt cache
        self.refresh()

        # Initialize maintenance screen
        self.fillTreeViewMaintenance()

    # ===============================================
    # Main window functions
    # ===============================================

    def on_btnInstall_clicked(self, widget):
        aptHasErrors = self.apt.aptHasErrors()
        if aptHasErrors is not None:
            self.showInfoDlg(self.btnInstall.get_label(), aptHasErrors)
        elif self.upgradables or self.umglobal.newEmergency:
            self.showOutput()
            contMsg = _("Continue installation?")
            contEmMsg = _("Continue emergency installation?")
            if self.upgradableUM:
                cmd = "apt-get -y --force-yes install updatemanager"
                nid = 'uminstallum'
                self.prepForCommand(nid)
                self.terminal.executeCommand(cmd, nid)
                self.log.write("Execute command: %s (%s)" % (cmd, nid), "UM.on_btnInstall_clicked", "debug")
            else:
                if self.umglobal.isStable:
                    if self.umglobal.newEmergency:
                        dialog = QuestionDialog(self.btnInfo.get_label(), contEmMsg, self.window)
                        if (dialog.show()):
                            em = join(self.filesDir, self.umglobal.settings['emergency-stable'].replace("[VERSION]", self.umglobal.serverEmergencyVersion))
                            cmd = "/bin/bash %(em)s" % { "em": em }
                            nid = 'uminstall'
                            self.prepForCommand(nid)
                            self.terminal.executeCommand(cmd, nid)
                            self.log.write("Execute command: %s (%s)" % (cmd, nid), "UM.on_btnInstall_clicked", "debug")
                            # Save emergency version in hist file
                            self.umglobal.saveHistVersion("emergency", self.umglobal.serverEmergencyVersion)
                            self.log.write("Save history emergency=%s" % self.umglobal.serverEmergencyVersion, "UM.on_btnInstall_clicked", "debug")
                    elif self.umglobal.newNewStable:
                        msg = self.getDistUpgradeInfo()
                        answer = True
                        if msg != "":
                            answer = self.showConfirmationDlg(contMsg, msg)
                        if answer:
                            # Pre and post scripts for stable
                            cmd = "apt-get -y --force-yes dist-upgrade"
                            # We can't have a new stable upgrade and a stable upgrade at the same time: use the same pre/post-stable variables
                            pre = join(self.filesDir, self.umglobal.settings['pre-stable'].replace("[VERSION]", self.umglobal.serverStableVersion))
                            post = join(self.filesDir, self.umglobal.settings['post-stable'].replace("[VERSION]", self.umglobal.serverStableVersion))
                            if exists(pre):
                                cmd = "/bin/bash %(pre)s; %(cmd)s" % { "pre": pre, "cmd": cmd }
                            if exists(post):
                                cmd = "%(cmd)s; /bin/bash %(post)s" % { "cmd": cmd, "post": post }
                            nid = 'uminstall'
                            self.prepForCommand(nid)
                            self.terminal.executeCommand(cmd, nid)
                            self.log.write("Execute command: %s (%s)" % (cmd, nid), "UM.on_btnInstall_clicked", "debug")
                            # Save newstable version in hist file
                            self.umglobal.saveHistVersion("newstable", self.umglobal.serverNewStableVersion)
                            self.log.write("Save history newstable= %s" % self.umglobal.serverNewStableVersion, "UM.on_btnInstall_clicked", "debug")
                    else:
                        dialog = QuestionDialog(self.btnInstall.get_label(), contMsg, self.window)
                        if (dialog.show()):
                            cmd = "apt-get -y --force-yes upgrade"
                            #if self.umglobal.newStable:
                            pre = join(self.filesDir, self.umglobal.settings['pre-stable'].replace("[VERSION]", self.umglobal.serverStableVersion))
                            post = join(self.filesDir, self.umglobal.settings['post-stable'].replace("[VERSION]", self.umglobal.serverStableVersion))
                            if exists(pre):
                                cmd = "/bin/bash %(pre)s; %(cmd)s" % { "pre": pre, "cmd": cmd }
                            if exists(post):
                                cmd = "%(cmd)s; /bin/bash %(post)s" % { "cmd": cmd, "post": post }
                            nid = 'uminstall'
                            self.prepForCommand(nid)
                            self.terminal.executeCommand(cmd, nid)
                            # Save stable version in hist file
                            self.umglobal.saveHistVersion("stable", self.umglobal.serverStableVersion)
                            self.log.write("Execute command: %s (%s)" % (cmd, nid), "UM.on_btnInstall_clicked", "debug")
                else:
                    if self.umglobal.newEmergency:
                        dialog = QuestionDialog(self.btnInfo.get_label(), contEmMsg, self.window)
                        if (dialog.show()):
                            em = join(self.filesDir, self.umglobal.settings['emergency'].replace("[VERSION]", self.umglobal.serverEmergencyVersion))
                            cmd = "/bin/bash %(em)s" % { "em": em }
                            nid = 'uminstall'
                            self.prepForCommand(nid)
                            self.terminal.executeCommand(cmd, nid)
                            self.log.write("Execute command: %s (%s)" % (cmd, nid), "UM.on_btnInstall_clicked", "debug")
                            # Save emergency version in hist file
                            self.umglobal.saveHistVersion("emergency", self.umglobal.serverEmergencyVersion)
                            self.log.write("Save history emergency=%s" % self.umglobal.serverEmergencyVersion, "UM.on_btnInstall_clicked", "debug")
                    else:
                        msg = self.getDistUpgradeInfo()
                        #answer = True
                        answer = False
                        if msg != "":
                            answer = self.showConfirmationDlg(contMsg, msg)
                        if answer:
                            cmd = "apt-get -y --force-yes dist-upgrade"
                            #if self.umglobal.newUp:
                            pre = join(self.filesDir, self.umglobal.settings['pre-up'].replace("[VERSION]", self.umglobal.serverUpVersion))
                            post = join(self.filesDir, self.umglobal.settings['post-up'].replace("[VERSION]", self.umglobal.serverUpVersion))
                            if exists(pre):
                                cmd = "/bin/bash %(pre)s; %(cmd)s" % { "pre": pre, "cmd": cmd }
                            if exists(post):
                                cmd = "%(cmd)s; /bin/bash %(post)s" % { "cmd": cmd, "post": post }
                            nid = 'uminstall'
                            self.prepForCommand(nid)
                            self.terminal.executeCommand(cmd, nid)
                            self.log.write("Execute command: %s (%s)" % (cmd, nid), "UM.on_btnInstall_clicked", "debug")
                            # Save up version in hist file
                            self.umglobal.saveHistVersion("up", self.umglobal.serverUpVersion)
                            self.log.write("Save history up=%s" % self.umglobal.serverUpVersion, "UM.on_btnInstall_clicked", "debug")
        else:
            self.showInfoDlg(self.btnInstall.get_label(), self.uptodateText)

    def on_btnRefresh_clicked(self, widget):
        self.refresh()

    def on_btnPackages_clicked(self, widget):
        self.showPackages()

    def on_btnOutput_clicked(self, widget):
        self.showOutput()

    def on_btnInfo_clicked(self, widget):
        self.showInfo()

    def on_btnPreferences_clicked(self, widget):
        # Run preferences in its own thread
        pref_thread = threading.Thread(target=self.openPreferences)
        pref_thread.setDaemon(True)
        pref_thread.start()

    def openPreferences(self):
        print("> openPreferences")
        os.system(join(self.scriptDir, "updatemanagerpref.py %s &" % self.user))

    def on_btnMaintenance_clicked(self, widget):
        self.showMaintenance()

    def on_radCleanCache_toggled(self, widget):
        if widget.get_active():
            self.fillTreeViewMaintenance()

    def on_radUnneeded_toggled(self, widget):
        if widget.get_active():
            message = _("You might need to run this several times.\n\n%s" % self.lblMaintenanceHelp.get_label().replace("\n", " "))
            MessageDialogSafe(self.btnMaintenance.get_label(), message, Gtk.MessageType.WARNING, self.window).show()
            self.fillTreeViewMaintenance()

    def on_radNotavailable_toggled(self, widget):
        if widget.get_active():
            message = _("Removing not available packages may break your system!\n\n%s" % self.lblMaintenanceHelp.get_label().replace("\n", " "))
            MessageDialogSafe(self.btnMaintenance.get_label(), message, Gtk.MessageType.WARNING, self.window).show()
            self.fillTreeViewMaintenance()

    def on_radOldKernel_toggled(self, widget):
        if widget.get_active():
            message = _("Once removed you will not be able to boot these kernels!\n\n%s" % self.lblMaintenanceHelp.get_label().replace("\n", " "))
            MessageDialogSafe(self.btnMaintenance.get_label(), message, Gtk.MessageType.WARNING, self.window).show()
            self.fillTreeViewMaintenance()

    def on_radDowngradable_toggled(self, widget):
        if widget.get_active():
            message = _("Downgrading packages may break your system!\n\n%s" % self.lblMaintenanceHelp.get_label().replace("\n", " "))
            MessageDialogSafe(self.btnMaintenance.get_label(), message, Gtk.MessageType.WARNING, self.window).show()
            self.fillTreeViewMaintenance()

    def on_btnMaintenanceExecute_clicked(self, widget):
        self.executeMaintenance()

    def on_chkMaintenanceSelectAll_toggled(self, widget):
        self.tvMaintenanceHandler.treeviewToggleAll(toggleColNrList=[0], toggleValue=widget.get_active())



    # ===============================================
    # Maintenance functions
    # ===============================================

    def enableMaintenance(self, enable=True):
        self.btnMaintenanceExecute.set_sensitive(enable)
        self.radUnneeded.set_sensitive(enable)
        self.radCleanCache.set_sensitive(enable)
        self.radDowngradable.set_sensitive(enable)
        self.radOldKernel.set_sensitive(enable)
        self.radNotavailable.set_sensitive(enable)
        self.chkMaintenanceSelectAll.set_sensitive(enable)
        if enable:
            self.chkMaintenanceSelectAll.set_active(False)

    def fillTreeViewMaintenance(self):
        blnCleanCache = self.radCleanCache.get_active()
        blnUnneeded = self.radUnneeded.get_active()
        blnDowngradable = self.radDowngradable.get_active()
        blnNotavailable = self.radNotavailable.get_active()
        blnOldKernels = self.radOldKernel.get_active()

        self.enableMaintenance(False)

        columnTypesList = ['bool', 'str', 'str', 'str']
        packages = [["", _("Package"), _("Installed"), _("Available")]]
        # Clear the treeview first
        self.tvMaintenanceHandler.fillTreeview(packages, columnTypesList, 0, 400, True)

        msg = ""
        if blnCleanCache:
            msg = _("Hit the Execute button to clean the cache.")
            columnTypesList = ['str']
            packages.append([msg])
        elif blnUnneeded:
            msg = self.radUnneeded.get_label()
            self.apt.createPackageLists("apt-get autoremove")
            for pck in self.apt.removedPackages:
                packages.append([False, pck[0], pck[1], pck[2]])
            self.apt.createPackageLists()
            # Add orphaned files
            self.apt.fillOrphanedPackages()
            for pck in self.apt.orphanedPackages:
                packages.append([False, pck[0], pck[1], pck[2]])
        elif blnNotavailable:
            msg = self.radNotavailable.get_label()
            self.apt.fillNotAvailablePackages()
            for pck in self.apt.notavailablePackages:
                if pck[0][0:6] != "linux-":
                    packages.append([False, pck[0], pck[1], ""])
        elif blnOldKernels:
            msg = self.radOldKernel.get_label()
            self.apt.fillNotAvailablePackages()
            for pck in self.apt.notavailablePackages:
                if pck[0][0:6] == "linux-" and self.kernelVersion not in pck[0]:
                    packages.append([False, pck[0], pck[1], ""])
        elif blnDowngradable:
            msg = self.radDowngradable.get_label()
            self.apt.fillDowngradablePackages()
            for pck in self.apt.downgradablePackages:
                packages.append([False, pck[0], pck[1], pck[2]])

        if len(packages) > 1:
            self.tvMaintenanceHandler.fillTreeview(packages, columnTypesList, 0, 400, True)
        else:
            if not blnCleanCache:
                msg += _("\ndid not return any results.")
                self.showInfoDlg(self.btnMaintenance.get_label(), msg)

        self.enableMaintenance(True)

    def executeMaintenance(self):
        blnCleanCache = self.radCleanCache.get_active()
        blnDowngradable = self.radDowngradable.get_active()
        blnNotNeeded = self.radUnneeded.get_active()
        downgradeString = ""
        deleteString = ""
        updateGrub = False
        cmd = ""

        self.enableMaintenance(False)

        if blnCleanCache:
            safe = False
            msg = _("Do you want to completely clean the apt cache?\n\n"
                    "When No, only unavailable installation packages are removed.")
            dialog = QuestionDialog(self.radCleanCache.get_label(), msg, self.window)
            if (dialog.show()):
                safe = True
            self.apt.cleanCache(safe)
            msg = _("Apt cache has been cleaned.")
            self.showInfoDlg(self.radCleanCache.get_label(), msg)
        else:
            # Get user selected packages
            model = self.tvMaintenance.get_model()
            itr = model.get_iter_first()
            while itr is not None:
                sel = model.get_value(itr, 0)
                if sel:
                    pck = model.get_value(itr, 1)
                    avVer = model.get_value(itr, 3)
                    if blnDowngradable:
                        downgradeString += " %(pck)s=%(avVer)s" % {"pck": pck, "avVer": avVer}
                    else:
                        deleteString += " %s" % pck
                        if "linux-image" in pck:
                            updateGrub = True
                itr = model.iter_next(itr)

            if downgradeString != "":
                cmd = "apt-get --yes --force-yes install %s" % downgradeString
            elif deleteString != "":
                cmd = "apt-get --yes --force-yes purge %s" % deleteString

        if cmd != "":
            self.apt.createPackageLists(cmd)
            msg = self.getDistUpgradeInfo()
            answer = True
            if msg != "":
                contMsg = _("Execute maintenance changes?")
                answer = self.showConfirmationDlg(contMsg, msg)
            if answer:
                if updateGrub:
                    cmd += "; update-grub"
                self.showOutput()
                nid = 'ummaintenance'
                self.prepForCommand(nid)
                self.terminal.executeCommand(cmd, nid)
                if blnNotNeeded:
                    cmd = "apt-get purge --yes --force-yes $(COLUMNS=132 dpkg -l | grep ^rc | awk '{ print $2 }')"
                    self.terminal.executeCommand(cmd, nid)
                self.log.write("Execute command: %s (%s)" % (cmd, nid), "UM.executeMaintenance", "debug")

        self.enableMaintenance(True)

    # ===============================================
    # General functions
    # ===============================================

    def prepForCommand(self, nid):
        os.system("touch %s" % join(self.filesDir, ".%s" % nid))
        self.btnRefresh.set_sensitive(False)
        self.btnInstall.set_sensitive(False)
        self.btnMaintenance.set_sensitive(False)

    def on_waiting_for_answer(self, obj, line):
        # Feed the terminal with an answer (only when safe)
        self.log.write("Waiting for answer on line: %s" % line, "UM.on_waiting_for_answer", "info")
        line = line.strip()
        if line == ":" or line == "(":
            cmd = 'q\r\n'
            self.terminal.feed_child(cmd, len(cmd))
            print(">> Assume changes to read: hit q before enter")
        else:
            print(">> Hit enter")
            cmd = '\r\n'
            # Just hit enter (use default selection)
            self.terminal.feed_child(cmd, len(cmd))

    def on_line_added(self, terminal, line):
        self.log.write(line, "UM.on_line_added", "info")

    def on_command_done(self, terminal, pid, nid):
        if nid != "init":
            self.log.write("Command finished (pid=%s, nid=%s)" % (pid, nid), "UM.on_command_done", "info")
            if nid == "uminstallum":
                # Reload UM
                self.log.write("updatemanager updated: reload UM", "UM.on_command_done", "debug")
                pid = self.umglobal.getScriptPid("updatemanagerpref.py")
                if pid > 0:
                    os.system("kill %d" % pid)
                # Reload tray as user
                if self.user != "":
                    cmd = "sudo -u %s %s" % (self.user, join(self.scriptDir, "updatemanagertray.py reload &"))
                    os.system(cmd)
                # Reload UM window
                path = self.ec.run(cmd="which python3", returnAsList=False)
                if exists(path):
                    try:
                        os.execl(path, path, "%s/updatemanager.py" % self.scriptDir, self.user)
                    except OSError as err:
                        self.log.write("Reload UM: %s" % str(err), "UM.on_command_done", "error")

            # Cleanup name file
            remove(join(self.filesDir, ".%s" % nid))

            if nid == "umrefresh":
                # Run post update when needed
                self.postUpdate()

            if nid == 'uminstall':
                # Remove scripts
                self.deleteScripts()

            if nid == "ummaintenance":
                self.enableMaintenance(True)
                self.fillTreeViewMaintenance()
                self.btnInstall.set_sensitive(True)
                if not self.umglobal.newEmergency:
                    self.btnRefresh.set_sensitive(True)
                    self.btnPackages.set_sensitive(True)
                    self.btnMaintenance.set_sensitive(True)
                self.showMaintenance()
            else:
                # Refresh data after install or update
                self.umglobal.collectData()
                self.apt.createPackageLists()
                self.fillTreeView()
                self.btnInstall.set_sensitive(True)
                if not self.umglobal.newEmergency:
                    self.btnRefresh.set_sensitive(True)
                    self.btnPackages.set_sensitive(True)
                    self.btnMaintenance.set_sensitive(True)
                self.loadInfo()
                if self.umglobal.newEmergency or self.umglobal.newStable or self.umglobal.newNewStable or self.umglobal.newUp:
                    self.showInfo()
                else:
                    aptHasErrors = self.apt.aptHasErrors()
                    if aptHasErrors is not None:
                        self.showInfoDlg(self.btnInfo.get_label(), aptHasErrors)
                    elif self.upgradables:
                        self.showPackages()
                    else:
                        self.showInfo()
                        self.showInfoDlg(self.btnInfo.get_label(), self.uptodateText)

    def refresh(self):
        prog = self.apt.getAptCacheLockedProgram(self.umglobal.settings["apt-packages"])
        if prog is not None:
            msg = _("Another program is locking the apt cache\n\n"
                    "Please, close the program before refreshing:\n"
                    "* %s" % prog)
            self.showInfoDlg(self.btnRefresh.get_label(), msg)
        else:
            self.btnInfo.set_sensitive(True)
            self.btnPreferences.set_sensitive(True)
            self.btnOutput.set_sensitive(True)
            self.btnRefresh.set_sensitive(False)
            self.btnInstall.set_sensitive(False)
            self.btnMaintenance.set_sensitive(False)
            if self.umglobal.newEmergency:
                self.btnPackages.set_sensitive(False)
            else:
                self.btnPackages.set_sensitive(True)

            self.showOutput()
            cmd = "dpkg --configure -a; apt-get -y --force-yes -f install; apt-get update"
            nid = 'umrefresh'
            self.prepForCommand(nid)
            self.terminal.executeCommand(cmd, nid, True)
            self.log.write("Execute command: %s (%s)" % (cmd, nid), "UM.refresh", "debug")

    def postUpdate(self):
        # Check for changed version information
        if self.umglobal.isStable:
            if self.umglobal.newEmergency and self.umglobal.serverEmergencyVersion is not None:
                self.getScripts([self.umglobal.settings['emergency-stable'].replace("[VERSION]", self.umglobal.serverEmergencyVersion)])
            elif self.umglobal.newNewStable and self.umglobal.serverNewStableVersion is not None:
                self.getScripts([self.umglobal.settings['pre-stable'].replace("[VERSION]", self.umglobal.serverNewStableVersion),
                                self.umglobal.settings['post-stable'].replace("[VERSION]", self.umglobal.serverNewStableVersion)])
            elif self.umglobal.newStable and self.umglobal.serverStableVersion is not None:
                self.getScripts([self.umglobal.settings['pre-stable'].replace("[VERSION]", self.umglobal.serverStableVersion),
                                self.umglobal.settings['post-stable'].replace("[VERSION]", self.umglobal.serverStableVersion)])
        else:
            if self.umglobal.newEmergency and self.umglobal.serverEmergencyVersion is not None:
                self.getScripts([self.umglobal.settings['emergency'].replace("[VERSION]", self.umglobal.serverEmergencyVersion)])
            elif self.umglobal.newUp and self.umglobal.serverUpVersion is not None:
                self.getScripts([self.umglobal.settings['pre-up'].replace("[VERSION]", self.umglobal.serverUpVersion),
                                self.umglobal.settings['post-up'].replace("[VERSION]", self.umglobal.serverUpVersion)])

    def fillTreeView(self):
        self.log.write("Fill treeview", "UM.fillTreeView", "debug")
        # First check if this application is upgradable
        self.upgradableUM = self.getUpgradablePackages(packageNames=["updatemanager"])
        if self.upgradableUM:
            self.upgradables = self.upgradableUM
        else:
            # Get a list of packages that can be upgraded
            self.upgradableUM = []
            self.upgradables = self.getUpgradablePackages()
            if not self.upgradables:
                # Check for black listed packages
                cmd = "dpkg --get-selections | grep hold$ | awk '{print $1}'"
                lst = self.ec.run(cmd, False)
                for pck in lst:
                    self.upgradables.append([pck.strip(), _("blacklisted"), ""])

        contentList = [[_("Package"), _("Current version"), _("New version")]] + self.upgradables
        self.tvHandler.fillTreeview(contentList=contentList, columnTypesList=['str', 'str', 'str'], firstItemIsColName=True)

    def getUpgradablePackages(self, packageNames=[]):
        if packageNames:
            upckList = []
            for packageName in packageNames:
                for upck in self.apt.upgradablePackages:
                    if upck[0] == packageName:
                        upckList.append(upck)
                        break
            return upckList
        else:
            return self.apt.upgradablePackages

    def getDistUpgradeInfo(self, upgradablesOnly=False):
        info = ""
        if upgradablesOnly:
            if self.apt.upgradablePackages:
                info = "<strong>%s</strong><br>" % self.apt.upgradablePackagesText
                for pck in self.apt.upgradablePackages:
                    info += "%s " % pck[0]
        else:
            if self.apt.removedPackages:
                info = "<strong>%s</strong><br>" % self.removedPackagesText
                for pck in self.apt.removedPackages:
                    info += "%s " % pck[0]
            if self.apt.newPackages:
                if info != "":
                    info += "<p>&nbsp;</p>"
                info += "<strong>%s</strong><br>" % self.newPackagesText
                for pck in self.apt.newPackages:
                    info += "%s " % pck[0]
            if self.apt.heldbackPackages:
                if info != "":
                    info += "<p>&nbsp;</p>"
                info += "<strong>%s</strong><br>" % self.heldbackPackagesText
                for pck in self.apt.heldbackPackages:
                    info += "%s " % pck[0]
            if self.apt.downgradablePackages:
                if info != "":
                    info += "<p>&nbsp;</p>"
                info += "<strong>%s</strong><br>" % self.downgradePackagesText
                for pck in self.apt.downgradablePackages:
                    info += "%s " % pck[0]
        return info

    def showPackages(self):
        self.nbMain.set_current_page(0)

    def showOutput(self):
        self.nbMain.set_current_page(1)
        self.terminal.grab_focus()

    def showInfo(self):
        self.nbMain.set_current_page(2)

    def showMaintenance(self):
        self.nbMain.set_current_page(3)

    def showInfoDlg(self, title, message):
        MessageDialogSafe(title, message, Gtk.MessageType.INFO, self.window).show()

    def showConfirmationDlg(self, title, message):
        head = "<html><head><style>body { font-family: Arial, Helvetica, Verdana, Sans-serif; font-size: 12px; color: #555555; background: #ffffff; }</style></head><body>"
        end = "</body></html>"
        html = "%s%s%s" % (head, message, end)
        sw = Gtk.ScrolledWindow()
        sw.add(SimpleBrowser(html))
        return CustomQuestionDialog(title, sw, 550, 300, self.window).show()

    # Get pre-install script and post-install script from the server
    def getScripts(self, files):
        for fle in files:
            flePath = join(self.filesDir, fle)
            if not exists(flePath):
                # Get the new scripts if they exist
                url = join(self.umglobal.umfilesUrl, fle)
                try:
                    txt = urlopen(url).read().decode('utf-8')
                    if txt != '':
                        # Save to a file and make executable
                        self.log.write("Save script = %s" % flePath, "UM.getScripts", "debug")
                        with open(flePath, 'w') as f:
                            f.write(txt)
                        chmod(flePath, 0o755)
                except:
                    pass

    def loadInfo(self):
        url = join("file://%s" % self.scriptDir, self.umglobal.settings['not-found'])
        self.btnInfo.set_icon_name("help-about")
        if self.umglobal.umfilesUrl is not None:
            if self.umglobal.newEmergency:
                self.btnInfo.set_icon_name("emblem-important")
                if self.umglobal.isStable:
                    url = "%s/%s" % (self.umglobal.umfilesUrl, self.umglobal.settings['emergency-stable-info'])
                else:
                    url = "%s/%s" % (self.umglobal.umfilesUrl, self.umglobal.settings['emergency-info'])
            else:
                if self.umglobal.isStable:
                    if self.umglobal.newNewStable:
                        url = "%s/%s" % (self.umglobal.umfilesUrl, self.umglobal.settings['new-stable-info'])
                    else:
                        url = "%s/%s" % (self.umglobal.umfilesUrl, self.umglobal.settings['stable-info'])
                else:
                    url = "%s/%s" % (self.umglobal.umfilesUrl, self.umglobal.settings['up-info'])
        elif self.umglobal.isStable:
            url = "%s/%s" % (self.umglobal.umfilesUrl, self.umglobal.settings['stable-info'])

        self.log.write("Load info url: %s" % url, "UM.loadInfo", "debug")

        children = self.swInfo.get_children()
        if children:
            children[0].openUrl(url)
        else:
            self.swInfo.add(SimpleBrowser(url))

    def pushMessage(self, message):
        if message is not None:
            context = self.statusbar.get_context_id('message')
            self.statusbar.push(context, message)

    def checkFilesDir(self):
        if not exists(self.filesDir):
            makedirs(self.filesDir)
        oldFiles = glob(join(self.scriptDir, 'pre-*')) + \
                   glob(join(self.scriptDir, 'post-*')) + \
                   glob(join(self.scriptDir, 'emergency-*')) + \
                   [join(self.scriptDir, 'updatemanager.hist')] + \
                   [join(self.scriptDir, 'mirrors.list')]
        for fle in oldFiles:
            fleName = basename(fle)
            if not exists(join(self.filesDir, fleName)):
                move(fle, self.filesDir)
            else:
                if exists(fle):
                    remove(fle)
        chmod(self.filesDir, 0o777)

    def deleteScripts(self):
        oldFiles = glob(join(self.filesDir, 'pre-*')) + glob(join(self.filesDir, 'post-*')) + glob(join(self.filesDir, 'emergency-*'))
        for fle in oldFiles:
            remove(fle)

    # Close the gui
    def on_windowMain_destroy(self, widget):
        # Close the app
        Gtk.main_quit()

if __name__ == '__main__':
    # Create an instance of our GTK application
    try:
        UpdateManager()
        Gtk.main()
    except KeyboardInterrupt:
        pass
