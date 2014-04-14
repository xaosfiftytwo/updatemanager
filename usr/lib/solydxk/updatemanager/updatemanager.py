#! /usr/bin/env python3
#-*- coding: utf-8 -*-

# Depends: apt-show-versions, python3-gi, python-vte, gir1.2-vte-2.90, gir1.2-webkit-3.0, python3-pyinotify

# from gi.repository import Gtk, GdkPixbuf, GObject, Pango, Gdk
from gi.repository import Gtk, Gdk, GObject
import sys
import os
import re
from os import remove, access, chmod
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
        self.builder = Gtk.Builder()
        self.builder.add_from_file(join(self.scriptDir, '../../../share/solydxk/updatemanager/updatemanager.glade'))

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

        # Translations
        self.window.set_title(_("SolydXK Update Manager"))
        self.btnInstall.set_label(_("Install"))
        self.btnRefresh.set_label(_("Refresh"))
        self.btnOutput.set_label(_("Output"))
        self.btnInfo.set_label(_("Information"))
        self.btnPreferences.set_label(_("Preferences"))
        self.btnPackages.set_label(_("Packages"))
        self.uptodateText = _("Your system is up to date")

        # Cleanup first
        os.system("rm -f %s" % join(self.scriptDir, ".um*"))

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
        self.swTerminal.modify_bg(Gtk.StateType.NORMAL, Gdk.color_parse(self.terminal.backgroundColor))

        # Disable all buttons
        self.btnInfo.set_sensitive(False)
        self.btnPreferences.set_sensitive(False)
        self.btnOutput.set_sensitive(False)
        self.btnRefresh.set_sensitive(False)
        self.btnInstall.set_sensitive(False)
        self.btnPackages.set_sensitive(False)

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
        self.log.write("Packages no longer available: %s" % ", ".join(self.apt.packagesNotAvailable), "UM.init", "warning")

        self.upgradables = []
        self.upgradableUM = []
        self.tvHandler = TreeViewHandler(self.tvPck)

        # Version information
        ver = _("Version")
        self.version = "%s: %s" % (ver, self.apt.getPackageVersion('updatemanager'))
        self.pushMessage(self.version)

        # Log basic information
        self.log.write("==============================================", "UM.init", "debug")
        self.log.write("UM version = %s" % self.version, "UM.init", "debug")
        if self.umglobal.isStable:
            self.log.write("UM localStable = %s, serverStable = %s, newStable = %s" % (self.umglobal.localStableVersion, self.umglobal.serverStableVersion, str(self.umglobal.newStable)), "UM.init", "debug")
        else:
            self.log.write("UM localUp = %s, serverUp = %s, newUp = %s" % (self.umglobal.localUpVersion, self.umglobal.serverUpVersion, str(self.umglobal.newUp)), "UM.init", "debug")
        self.log.write("UM localEmergency = %s, serverEmergency = %s, newEmergency = %s" % (self.umglobal.localEmergencyVersion, self.umglobal.serverEmergencyVersion, str(self.umglobal.newEmergency)), "UM.init", "debug")
        self.log.write("==============================================", "UM.init", "debug")
        mirrorsList = join(self.scriptDir, basename(self.umglobal.settings["mirrors-list"]))
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
                            em = join(self.scriptDir, self.umglobal.settings['emergency-stable'].replace("[VERSION]", self.umglobal.serverEmergencyVersion))
                            cmd = "/bin/bash %(em)s" % { "em": em }
                            nid = 'uminstall'
                            self.prepForCommand(nid)
                            self.terminal.executeCommand(cmd, nid)
                            self.log.write("Execute command: %s (%s)" % (cmd, nid), "UM.on_btnInstall_clicked", "debug")
                            # Save emergency version in hist file
                            self.umglobal.saveHistVersion("emergency", self.umglobal.serverEmergencyVersion)
                            self.log.write("Save history emergency=%s" % self.umglobal.serverEmergencyVersion, "UM.on_btnInstall_clicked", "debug")
                    elif self.umglobal.newStable:
                        msg = self.apt.getDistUpgradeInfo()
                        answer = True
                        if msg != "":
                            answer = self.showConfirmationDlg(contMsg, msg)
                        if answer:
                            # Pre and post scripts for stable
                            cmd = "apt-get -y --force-yes dist-upgrade"
                            if self.umglobal.newStable:
                                pre = join(self.scriptDir, self.umglobal.settings['pre-stable'].replace("[VERSION]", self.umglobal.serverStableVersion))
                                post = join(self.scriptDir, self.umglobal.settings['post-stable'].replace("[VERSION]", self.umglobal.serverStableVersion))
                                if exists(pre):
                                    cmd = "/bin/bash %(pre)s; %(cmd)s" % { "pre": pre, "cmd": cmd }
                                if exists(post):
                                    cmd = "%(cmd)s; /bin/bash %(post)s" % { "cmd": cmd, "post": post }
                            nid = 'uminstall'
                            self.prepForCommand(nid)
                            self.terminal.executeCommand(cmd, nid)
                            self.log.write("Execute command: %s (%s)" % (cmd, nid), "UM.on_btnInstall_clicked", "debug")
                            # Save stable version in hist file
                            self.umglobal.saveHistVersion("stable", self.umglobal.serverStableVersion)
                            self.log.write("Save history stable= %s" % self.umglobal.serverStableVersion, "UM.on_btnInstall_clicked", "debug")
                    else:
                        dialog = QuestionDialog(self.btnInstall.get_label(), contMsg, self.window)
                        if (dialog.show()):
                            cmd = "apt-get -y --force-yes upgrade"
                            nid = 'uminstall'
                            self.prepForCommand(nid)
                            self.terminal.executeCommand(cmd, nid)
                            self.log.write("Execute command: %s (%s)" % (cmd, nid), "UM.on_btnInstall_clicked", "debug")
                else:
                    if self.umglobal.newEmergency:
                        dialog = QuestionDialog(self.btnInfo.get_label(), contEmMsg, self.window)
                        if (dialog.show()):
                            em = join(self.scriptDir, self.umglobal.settings['emergency'].replace("[VERSION]", self.umglobal.serverEmergencyVersion))
                            cmd = "/bin/bash %(em)s" % { "em": em }
                            nid = 'uminstall'
                            self.prepForCommand(nid)
                            self.terminal.executeCommand(cmd, nid)
                            self.log.write("Execute command: %s (%s)" % (cmd, nid), "UM.on_btnInstall_clicked", "debug")
                            # Save emergency version in hist file
                            self.umglobal.saveHistVersion("emergency", self.umglobal.serverEmergencyVersion)
                            self.log.write("Save history emergency=%s" % self.umglobal.serverEmergencyVersion, "UM.on_btnInstall_clicked", "debug")
                    else:
                        msg = self.apt.getDistUpgradeInfo()
                        answer = True
                        if msg != "":
                            answer = self.showConfirmationDlg(contMsg, msg)
                        if answer:
                            cmd = "apt-get -y --force-yes dist-upgrade"
                            if self.umglobal.newUp:
                                pre = join(self.scriptDir, self.umglobal.settings['pre-up'].replace("[VERSION]", self.umglobal.serverUpVersion))
                                post = join(self.scriptDir, self.umglobal.settings['post-up'].replace("[VERSION]", self.umglobal.serverUpVersion))
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
        pref_thread = threading.Thread(target=self.ec.run, args=(join(self.scriptDir, "updatemanagerpref.py &"),))
        pref_thread.setDaemon(True)
        pref_thread.start()

    # ===============================================
    # General functions
    # ===============================================

    def prepForCommand(self, nid):
        os.system("touch %s" % join(self.scriptDir, ".%s" % nid))
        self.btnRefresh.set_sensitive(False)
        self.btnInstall.set_sensitive(False)

    def on_waiting_for_answer(self, obj, line, col, row):
        # Feed the terminal with an answer (only when safe)
        self.log.write("Waiting for answer: %s (col=%d, row=%d)" % (line, col, row), "UM.on_waiting_for_answer", "info")
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

    def on_line_added(self, terminal, line, col, row):
        self.log.write("Lined added: %s (col=%d, row=%d)" % (line, col, row), "UM.on_line_added", "info")

    def on_command_done(self, terminal, pid, nid):
        if nid != "init":
            self.log.write("Command finished (pid=%s, nid=%s)" % (pid, nid), "UM.on_command_done", "info")
            if nid == "uminstallum":
                # Reload UM
                self.log.write("updatemanager updated: reload UM", "UM.on_command_done", "debug")
                pid = self.umglobal.getScriptPid("updatemanagerpref.py")
                if pid > 0:
                    os.system("kill %d" % pid)
                os.system(join(self.scriptDir, "updatemanagertray.py reload &"))
                os.system("gksudo --message \"%s\" %s/updatemanager.py reload &" % (_("Please enter your password to restart the update manager"), self.scriptDir))
                # Execution of this script ends here: a new instance was started after the update

            # Cleanup name file
            os.system("rm -f %s" % join(self.scriptDir, ".%s" % nid))

            if nid == "umrefresh":
                # Run post update when needed
                self.postUpdate()

            # Refresh data after install or update
            self.umglobal.collectData()
            self.apt.createPackagesVersionInfoLists()
            self.apt.createPackageLists()
            self.fillTreeView()
            self.btnInstall.set_sensitive(True)
            if not self.umglobal.newEmergency:
                self.btnRefresh.set_sensitive(True)
                self.btnPackages.set_sensitive(True)
            self.loadInfo()
            if self.umglobal.newEmergency or self.umglobal.newStable or self.umglobal.newUp:
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
            if self.umglobal.newEmergency:
                self.btnPackages.set_sensitive(False)
            else:
                self.btnPackages.set_sensitive(True)

            self.showOutput()
            cmd = "dpkg --configure -a; apt-get -y --force-yes -f install; apt-get update"
            nid = 'umrefresh'
            self.prepForCommand(nid)
            self.terminal.executeCommand(cmd, nid)
            self.log.write("Execute command: %s (%s)" % (cmd, nid), "UM.refresh", "debug")

    def postUpdate(self):
        # Check for changed version information
        if self.umglobal.isStable:
            if self.umglobal.newEmergency and self.umglobal.serverEmergencyVersion is not None:
                self.getScripts([self.umglobal.settings['emergency-stable'].replace("[VERSION]", self.umglobal.serverEmergencyVersion)])
            elif self.umglobal.serverStableVersion is not None:
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
        self.upgradableUM = self.apt.getUpgradablePackages(packageNames=["updatemanager"])
        if self.upgradableUM:
            self.upgradables = self.upgradableUM
        else:
            # Get a list of packages that can be upgraded
            self.upgradableUM = []
            self.upgradables = self.apt.getUpgradablePackages()
            if not self.upgradables:
                # Check for black listed packages
                cmd = "dpkg --get-selections | grep hold$ | awk '{print $1}'"
                lst = self.ec.run(cmd, False)
                for pck in lst:
                    self.upgradables.append([pck.strip(), _("blacklisted"), ""])

        contentList = [[_("Package"), _("Current version"), _("New version")]] + self.upgradables
        self.tvHandler.fillTreeview(contentList=contentList, columnTypesList=['str', 'str', 'str'], firstItemIsColName=True)

    def showPackages(self):
        self.nbMain.set_current_page(0)

    def showOutput(self):
        self.nbMain.set_current_page(1)
        self.terminal.grab_focus()

    def showInfo(self):
        self.nbMain.set_current_page(2)

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
        # Delete old pre or post files
        oldFiles = glob(join(self.scriptDir, 'pre-*')) + glob(join(self.scriptDir, 'post-*')) + glob(join(self.scriptDir, 'emergency-*'))
        for fle in oldFiles:
            remove(fle)
        for fle in files:
            # Get the new scripts if they exist
            url = join(self.umglobal.umfilesUrl, fle)
            try:
                txt = urlopen(url).read().decode('utf-8')
                if txt != '':
                    # Save to a file and make executable
                    flePath = join(self.scriptDir, fle)
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
                    if self.umglobal.newStable:
                        url = "%s/%s" % (self.umglobal.umfilesUrl, self.umglobal.settings['new-stable-info'])
                    else:
                        url = join("file://%s" % self.scriptDir, self.umglobal.settings['stable-info'])
                else:
                    url = "%s/%s" % (self.umglobal.umfilesUrl, self.umglobal.settings['up-info'])
        elif self.umglobal.isStable:
            url = os.path.join("file://%s" % self.scriptDir, self.umglobal.settings['stable-info'])

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
