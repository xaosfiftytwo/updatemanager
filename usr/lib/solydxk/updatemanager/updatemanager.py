#!/usr/bin/env python

try:
    import pygtk
    pygtk.require("2.0")
    import os
    import commands
    import sys
    import string
    import gtk
    import gtk.glade
    import time
    import gettext
    import urllib2
    import webkit
    import webbrowser
    import re
    import csv
    import Queue
    import glib
    import apt
    from execcmd import ExecCmd
    from mirror import MirrorGetSpeed, Mirror
    from treeview import TreeViewHandler
    from glob import glob
    from config import Config
    from datetime import date
    from changelogRetriever import ChangelogRetriever
    from threadClasses import AutomaticRefreshThread, InstallThread, RefreshThread
    import functions
    from logger import Logger
except Exception, detail:
    print detail
    pass

# Indexes for main model
INDEX_UPGRADE = 0
INDEX_PACKAGE_NAME = 1
INDEX_OLD_VERSION = 2
INDEX_NEW_VERSION = 3
INDEX_SIZE = 4
INDEX_STR_SIZE = 5
INDEX_DESCRIPTION = 6
INDEX_SOURCE_PACKAGE = 7

# Indexes for history model
INDEX_HISTORY_DATE = 0
INDEX_HISTORY_PACKAGE_NAME = 1
INDEX_HISTORY_OLD_VERSION = 2
INDEX_HISTORY_NEW_VERSION = 3

# i18n
gettext.install("updatemanager", "/usr/share/locale")

class UM:

    def __init__(self):
        try:
            nrUpdMgr = commands.getoutput("ps -A | grep updatemanager$ | wc -l")
            if (nrUpdMgr != "0"):
                if (os.getuid() == 0):
                    os.system("killall updatemanager")
                else:
                    print "Another updatemanager is already running, exiting."
                    sys.exit(1)
        except Exception, detail:
            print detail

        # Rename the process (or it will be listed as "Python" instead of "updatemanager")
        architecture = commands.getoutput("uname -a")
        if (architecture.find("x86_64") >= 0):
            import ctypes
            libc = ctypes.CDLL('libc.so.6')
            libc.prctl(15, 'updatemanager', 0, 0, 0)
        else:
            import dl
            if os.path.exists('/lib/libc.so.6'):
                libc = dl.open('/lib/libc.so.6')
                libc.call('prctl', 15, 'updatemanager', 0, 0, 0)
            elif os.path.exists('/lib/i386-linux-gnu/libc.so.6'):
                libc = dl.open('/lib/i386-linux-gnu/libc.so.6')
                libc.call('prctl', 15, 'updatemanager', 0, 0, 0)

        # Get current (lib) and share directory
        self.curdir = os.path.dirname(os.path.realpath(__file__))
        self.sharedir = os.path.join(self.curdir.replace('/lib/', '/share/'))
        self.gladefile = os.path.join(self.sharedir, "updatemanager.glade")

        # Initiate Glade builder
        self.builder = gtk.Builder()
        self.builder.add_from_file(self.gladefile)
        self.umWindow = self.builder.get_object('umWindow')
        self.prefWindow = self.builder.get_object('prefWindow')
        self.histWindow = self.builder.get_object('histWindow')
        self.infoWindow = self.builder.get_object('infoWindow')
        self.packWindow = self.builder.get_object('window_pack_info')

        # Initiate global variables
        self.ec = ExecCmd()
        self.historyLog = "/var/log/updatemanager.history"
        self.cfgignored = os.path.join(self.curdir, 'updatemanager.ignored')
        self.cfg = Config('updatemanager.conf')
        self.new_updatemanager = False
        self.app_hidden = True
        self.prefs = self.read_configuration()
        self.repos = self.get_apt_repos()
        self.mode = "user"
        if self.mode == 0:
            self.mode = "root"

        self.pid = os.getpid()
        self.statusIcon = gtk.StatusIcon()
        self.mirrors = self.getMirrors()
        self.queue = Queue.Queue()
        self.threads = {}
        self.upHistFile = os.path.join(self.curdir, "up.hist")

        self.treeview_update = self.builder.get_object("treeview_update")
        self.btnCheckMirrorsSpeed = self.builder.get_object("btnCheckMirrorsSpeed")
        self.statusIcon.set_from_file(self.prefs["icon_busy"])
        self.statusIcon.set_tooltip(_("Checking for updates"))
        self.statusIcon.set_visible(True)
        self.umWindow.set_title(_("Update Manager"))
        self.umWindow.set_default_size(self.prefs['dimensions_x'], self.prefs['dimensions_y'])
        self.vpaned_main = self.builder.get_object('vpaned_main')
        self.vpaned_main.set_position(self.prefs['dimensions_pane_position'])
        self.statusbar = self.builder.get_object("statusbar")
        self.context_id = self.statusbar.get_context_id("updatemanager")
        self.vbox_main = self.builder.get_object("vbox_main")
        self.umWindow.set_icon_from_file(self.prefs["icon_busy"])

        # Initiate logging
        self.logFile = os.path.join(self.curdir, "updatemanager.log")
        if os.access(self.logFile, os.W_OK):
            os.remove(self.logFile)
        self.log = Logger(self.logFile, 'debug', True, self.statusbar, self.umWindow, 10240)
        functions.log = self.log

        # Version information
        self.version = self.getPackageVersion('updatemanager')
        self.candidateVersion = self.getPackageVersion('updatemanager', True)
        self.serverUpVersion = None
        self.localUpVersion = None
        self.newUp = self.checkUpVersions()
        self.newUpVersion = None
        if self.newUp:
            self.newUpVersion = self.serverUpVersion
        self.log.write("self.newUp = %s" % str(self.newUp), "UM.init", "debug")
        self.log.write("self.serverUpVersion = %s" % str(self.serverUpVersion), "UM.init", "debug")
        self.log.write("self.localUpVersion = %s" % str(self.localUpVersion), "UM.init", "debug")

        # The blacklist treeview
        self.treeview_blacklist = self.builder.get_object("treeview_blacklist")
        column1 = gtk.TreeViewColumn(_("Ignored packages"), gtk.CellRendererText(), text=0)
        column1.set_sort_column_id(0)
        column1.set_resizable(True)
        self.treeview_blacklist.append_column(column1)
        self.treeview_blacklist.set_headers_clickable(True)
        self.treeview_blacklist.set_reorderable(False)

        # the history treeview
        column_date = gtk.TreeViewColumn(_("Date"), gtk.CellRendererText(), text=INDEX_HISTORY_DATE)
        column_date.set_sort_column_id(INDEX_HISTORY_DATE)
        column_date.set_resizable(True)
        column_package_name = gtk.TreeViewColumn(_("Package"), gtk.CellRendererText(), text=INDEX_HISTORY_PACKAGE_NAME)
        column_package_name.set_sort_column_id(INDEX_HISTORY_PACKAGE_NAME)
        column_package_name.set_resizable(True)
        column_old_version = gtk.TreeViewColumn(_("Old version"), gtk.CellRendererText(), text=INDEX_HISTORY_OLD_VERSION)
        column_old_version.set_sort_column_id(INDEX_HISTORY_OLD_VERSION)
        column_old_version.set_resizable(True)
        column_new_version = gtk.TreeViewColumn(_("New version"), gtk.CellRendererText(), text=INDEX_HISTORY_NEW_VERSION)
        column_new_version.set_sort_column_id(INDEX_HISTORY_NEW_VERSION)
        column_new_version.set_resizable(True)

        self.treeview_history = self.builder.get_object("treeview_history")
        self.treeview_history.append_column(column_date)
        self.treeview_history.append_column(column_package_name)
        self.treeview_history.append_column(column_old_version)
        self.treeview_history.append_column(column_new_version)
        self.treeview_history.set_headers_clickable(True)
        self.treeview_history.set_reorderable(False)
        self.treeview_history.set_search_column(INDEX_HISTORY_PACKAGE_NAME)
        self.treeview_history.set_enable_search(True)

        # Initiate the treeview handler and connect the custom toggle event with treeview_mirrors_toggle
        self.treeview_mirrors = self.builder.get_object("treeview_mirrors")
        self.treeview_mirrors_handler = TreeViewHandler(self.treeview_mirrors)
        self.treeview_mirrors_handler.connect('checkbox-toggled', self.treeview_mirrors_toggle)

        # i18n for menu item
        self.menuName = _("Update Manager")
        self.menuGenericName = _("Software Updates")
        self.menuComment = _("Show and install available updates")

        # Add events
        signals = {
            'on_treeview_update_button_release_event': self.menuPopup,
            'on_treeview_update-selection1_changed': self.display_selected_package,
            'on_notebook_details_switch_page': self.switch_page,
            'on_tool_apply_clicked': self.install,
            'on_tool_clear_clicked': self.clear,
            'on_tool_select_all_clicked': self.select_all,
            'on_tool_refresh_clicked': self.force_refresh,
            'on_tool_pack_info_clicked': self.open_pack_info,
            'on_button_close_pack_clicked': self.close_pack_info,
            'on_pref_button_cancel_clicked': self.pref_cancel,
            'on_pref_button_apply_clicked': self.pref_apply,
            'on_toolbutton_add_clicked': self.add_blacklisted_package,
            'on_toolbutton_remove_clicked': self.remove_blacklisted_package,
            'on_hist_button_close_clicked': self.history_cancel,
            'on_hist_button_clear_clicked': self.history_clear,
            'on_info_close_button_clicked': self.info_cancel,
            'on_btnCheckMirrorsSpeed_clicked': self.checkMirrorsSpeed,
            'on_button_icon_busy_clicked': self.change_icon,
            'on_umWindow_delete_event': self.close_window,
            'on_histWindow_delete_event': self.histWindow_hide,
            'on_infoWindow_delete_event': self.infoWindow_hide,
            'on_prefWindow_delete_event': self.prefWindow_hide,
            'on_window_pack_info_delete_event': self.packWindow_hide
        }
        self.builder.connect_signals(signals)

    def histWindow_hide(self, widget, data=None):
        self.histWindow.hide()
        return True

    def infoWindow_hide(self, widget, data=None):
        self.infoWindow.hide()
        return True

    def prefWindow_hide(self, widget, data=None):
        self.prefWindow.hide()
        return True

    def packWindow_hide(self, widget, data=None):
        self.packWindow.hide()
        return True

    # Get the package version number
    def getPackageVersion(self, packageName, candidate=False):
        version = ''
        try:
            cache = apt.Cache()
            pkg = cache[packageName]
            if candidate:
                version = pkg.candidate.version
            elif pkg.installed is not None:
                version = pkg.installed.version
        except:
            pass
        return version

    def get_apt_repos(self):
        repos = []
        cmds = ['cat /etc/apt/sources.list']
        #srcFiles = glob('/etc/apt/sources.list.d/*.list')
        #for fle in srcFiles:
        #    cmds.append("cat %s" % fle)
        for cmd in cmds:
            lstOut = self.ec.run(cmd)
            for line in lstOut:
                line = line.strip()
                matchObj = re.search("^deb\s*(http[:\/a-zA-Z0-9\.\-]*)", line)
                if matchObj:
                    repos.append(matchObj.group(1))
        return repos

    # Check for a new Update Pack
    def checkUpVersions(self):
        newUp = False
        if self.candidateVersion == self.version:
            if os.path.exists(self.upHistFile):
                with open(self.upHistFile, 'r') as fle:
                    version = fle.readlines()[-1].strip()
                    self.localUpVersion = version[len(version) - 10:]
                    self.log.write("upHistFile = %s | lastUp = %s" % (str(self.upHistFile), self.localUpVersion), "UM.checkUpVersion", "debug")
            elif os.path.exists("/var/log/updatemanager.packlevel"):
                self.localUpVersion = commands.getoutput("cat /var/log/updatemanager.packlevel").strip()
                self.log.write("packlevel = /var/log/updatemanager.packlevel | lastUp = %s" % self.localUpVersion, "UM.checkUpVersion", "debug")
            else:
                preFile = commands.getoutput("ls %s | grep '.pre'" % self.curdir)
                if preFile != "":
                    self.localUpVersion = preFile.replace(".pre", "")
                else:
                    # Nothing found, just save a default value
                    self.localUpVersion = "2000.01.01"
                self.log.write("preFile = %s | lastUp = %s" % (str(preFile), self.localUpVersion), "UM.checkUpVersion", "debug")

            # Strip the local up version
            self.localUpVersion = self.localUpVersion.strip().strip("\0")

            try:
                solydxk_repo_url = None
                for repo in self.repos:
                    if 'debian.solydxk.com/production' in repo:
                        solydxk_repo_url = "http://" + self.prefs["repurldebian"] + "/production"
                        break
                    if 'debian.solydxk.com/testing' in repo:
                        solydxk_repo_url = "http://" + self.prefs["repurldebian"] + "/testing"
                        break
                if solydxk_repo_url is not None:
                    url = "%s/update-pack-info.txt" % solydxk_repo_url
                    html = urllib2.urlopen(url)
                    for line in html.readlines():
                        elements = line.split("=")
                        variable = elements[0].strip()
                        value = elements[1].strip().strip("\0")
                        if variable == "version":
                            self.serverUpVersion = value
                            self.log.write("len(localUpVersion) = %s | len(serverUpVersion) = %s" % (str(len(self.localUpVersion)), str(len(self.serverUpVersion))), "UM.checkUpVersion", "debug")
                            if len(self.localUpVersion) == len(self.serverUpVersion):
                                instUpArr = self.localUpVersion.split('.')
                                valArr = self.serverUpVersion.split('.')
                                instDate = date(int(instUpArr[0]), int(instUpArr[1]), int(instUpArr[2]))
                                valDate = date(int(valArr[0]), int(valArr[1]), int(valArr[2]))
                                self.log.write("valDate %s > instDate %s" % (valDate, instDate), "UM.checkUpVersion", "debug")
                                if valDate > instDate:
                                    # There's a new UP
                                    newUp = True
                                    # Get the pre and post scripts
                                    self.getPrePostScripts(solydxk_repo_url, self.serverUpVersion)
                                    break
                                elif valDate == instDate and not os.path.exists(self.upHistFile):
                                    # Temporary hack for older updatemanagers that wrote the packlevel before the update
                                    self.log.write("Old previous updatemanager", "UM.checkUpVersion", "debug")
                                    newUp = True
                                    self.getPrePostScripts(solydxk_repo_url, self.serverUpVersion)
                                    break
                            else:
                                self.log.write("No packlevel", "UM.checkUpVersion", "debug")
                                newUp = True
                                self.getPrePostScripts(solydxk_repo_url, self.serverUpVersion)
                                break
                    html.close()
            except Exception, detail:
                print detail

        return newUp

    # Get pre-install script and post-install script from the server
    def getPrePostScripts(self, repoUrl, upVersion):
        if os.geteuid() == 0:
            baseUrl = repoUrl + '/' + upVersion
            basePath = os.path.join(self.curdir, upVersion)
            extensions = ['pre', 'post']
            for extension in extensions:
                try:
                    # Delete old pre or post files
                    oldFiles = glob(self.curdir + '/*.' + extension)
                    for oldFile in oldFiles:
                        os.remove(oldFile)
                    # Get the new scripts if they exist
                    url = baseUrl + '.' + extension
                    txt = urllib2.urlopen(url).read()
                    if txt != '':
                        # Save to a file and make executable
                        flePath = basePath + '.' + extension
                        fle = open(flePath, 'w')
                        fle.write(txt)
                        fle.close()
                        os.chmod(flePath, 0755)
                except:
                    pass

    def force_refresh(self, widget):
        refresh = RefreshThread(self.treeview_update, self.statusIcon, self.builder, self.prefs, self.log, self.newUpVersion)
        refresh.start()

    def clear(self, widget):
        model = self.treeview_update.get_model()
        itr = model.get_iter_first()
        while (itr is not None):
            model.set_value(itr, INDEX_UPGRADE, "false")
            itr = model.iter_next(itr)
        self.statusbar.push(self.context_id, _("No updates selected"))

    def select_all(self, widget):
        model = self.treeview_update.get_model()
        itr = model.get_iter_first()
        while (itr is not None):
            model.set_value(itr, INDEX_UPGRADE, "true")
            itr = model.iter_next(itr)
        itr = model.get_iter_first()
        download_size = 0
        num_selected = 0
        while (itr is not None):
            checked = model.get_value(itr, INDEX_UPGRADE)
            if (checked == "true"):
                size = model.get_value(itr, INDEX_SIZE)
                download_size = download_size + size
                num_selected = num_selected + 1
            itr = model.iter_next(itr)
        if num_selected == 0:
            self.statusbar.push(self.context_id, _("No updates selected"))
        elif num_selected == 1:
            self.statusbar.push(self.context_id, _("%(selected)d update selected (%(size)s)") % {'selected': num_selected, 'size': self.size_to_string(download_size)})
        else:
            self.statusbar.push(self.context_id, _("%(selected)d updates selected (%(size)s)") % {'selected': num_selected, 'size': self.size_to_string(download_size)})

    def install(self, widget):
        instThread = InstallThread(self.treeview_update, self.statusIcon, self.builder, self.prefs, self.log, self.newUpVersion, self.upHistFile, self.statusbar)
        instThread.start()

    def change_icon(self, widget, button):
        dialog = gtk.FileChooserDialog(_("Update Manager"), None, gtk.FILE_CHOOSER_ACTION_OPEN, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        filter1 = gtk.FileFilter()
        filter1.set_name("*.*")
        filter1.add_pattern("*")
        filter2 = gtk.FileFilter()
        filter2.set_name("*.png")
        filter2.add_pattern("*.png")
        dialog.add_filter(filter2)
        dialog.add_filter(filter1)

        if dialog.run() == gtk.RESPONSE_OK:
            filename = dialog.get_filename()
            if (button == "busy"):
                self.builder.get_object("image_busy").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(filename, 24, 24))
                self.prefs["icon_busy"] = filename
            if (button == "up2date"):
                self.builder.get_object("image_up2date").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(filename, 24, 24))
                self.prefs["icon_up2date"] = filename
            if (button == "updates"):
                self.builder.get_object("image_updates").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(filename, 24, 24))
                self.prefs["icon_updates"] = filename
            if (button == "error"):
                self.builder.get_object("image_error").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(filename, 24, 24))
                self.prefs["icon_error"] = filename
            if (button == "unknown"):
                self.builder.get_object("image_unknown").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(filename, 24, 24))
                self.prefs["icon_unknown"] = filename
            if (button == "apply"):
                self.builder.get_object("image_apply").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(filename, 24, 24))
                self.prefs["icon_apply"] = filename
        dialog.destroy()

    def pref_apply(self, widget):
        # Write updatemanager config
        section = 'UPDATEMANAGER'
        self.cfg.setValue(section, 'repurl', self.prefs["repurl"])
        self.cfg.setValue(section, 'repurldebian', self.prefs["repurldebian"])
        self.cfg.setValue(section, 'repdebian', self.prefs["repdebian"])
        #self.cfg.setValue(section, 'authors', self.prefs["authors"])
        self.cfg.setValue(section, 'testdomain', self.prefs["testdomain"])
        #self.cfg.setValue(section, 'mirrorsurl', self.prefs["mirrorsurl"])

        # Write refresh config
        section = 'refresh'
        self.prefs["timer_minutes"] = int(self.builder.get_object("timer_minutes").get_value())
        self.prefs["timer_hours"] = int(self.builder.get_object("timer_hours").get_value())
        self.prefs["timer_days"] = int(self.builder.get_object("timer_days").get_value())
        self.cfg.setValue(section, 'timer_minutes', self.prefs["timer_minutes"])
        self.cfg.setValue(section, 'timer_hours', self.prefs["timer_hours"])
        self.cfg.setValue(section, 'timer_days', self.prefs["timer_days"])

        #Write update config
        section = 'update'
        self.prefs["delay"] = int(self.builder.get_object("spin_delay").get_value())
        self.prefs["ping_domain"] = self.builder.get_object("ping_domain").get_text()
        self.prefs["close_synaptic"] = self.builder.get_object("checkbutton_close_synaptic").get_active()
        self.cfg.setValue(section, 'delay', self.prefs["delay"])
        self.cfg.setValue(section, 'ping_domain', self.prefs["ping_domain"])
        self.cfg.setValue(section, 'close_synaptic', self.prefs["close_synaptic"])

        #Write icons config
        section = 'icons'
        self.cfg.setValue(section, 'busy', self.prefs["icon_busy"])
        self.cfg.setValue(section, 'up2date', self.prefs["icon_up2date"])
        self.cfg.setValue(section, 'updates', self.prefs["icon_updates"])
        self.cfg.setValue(section, 'error', self.prefs["icon_error"])
        self.cfg.setValue(section, 'unknown', self.prefs["icon_unknown"])
        self.cfg.setValue(section, 'apply', self.prefs["icon_apply"])

        #Write blacklisted packages
        ignored_list = open(self.cfgignored, "w")
        model = self.treeview_blacklist.get_model()
        itr = model.get_iter_first()
        while itr is not None:
            pkg = model.get_value(itr, 0)
            itr = model.iter_next(itr)
            ignored_list.writelines(pkg + "\n")
        ignored_list.close()

        # Safe mirror settings
        replaceRepos = []
        # Get user selected mirrors
        model = self.treeview_mirrors.get_model()
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
            m = Mirror(self.log)
            m.save(replaceRepos)
            self.repos = self.get_apt_repos()
            self.mirrors = self.getMirrors()

        self.prefWindow.hide()
        refresh = RefreshThread(self.treeview_update, self.statusIcon, self.builder, self.prefs, self.log, self.newUpVersion)
        refresh.start()

    def info_cancel(self, widget):
        self.infoWindow.hide()

    def history_cancel(self, widget):
        self.histWindow.hide()

    def history_clear(self, widget):
        os.system("rm -rf /var/log/updatemanager.history")
        model = gtk.TreeStore(str, str, str, str)
        self.treeview_history.set_model(model)
        del model

    def pref_cancel(self, widget):
        self.prefWindow.hide()
        #return True

    def read_configuration(self):
        prefs = {}
        # Read updatemanager config
        section = 'UPDATEMANAGER'
        try:
            prefs["repurl"] = self.cfg.getValue(section, 'repurl')
            prefs["repurldebian"] = self.cfg.getValue(section, 'repurldebian')
            prefs["repdebian"] = self.cfg.getValue(section, 'repdebian')
            prefs["authors"] = self.cfg.getValue(section, 'authors').split(',')
            prefs["testdomain"] = self.cfg.getValue(section, 'testdomain')
            prefs["mirrorsurl"] = self.cfg.getValue(section, 'mirrorsurl')
        except:
            prefs["repurl"] = 'packages.solydxk.com'
            prefs["repurldebian"] = 'debian.solydxk.com'
            prefs["repdebian"] = 'ftp.debian.org'
            prefs["authors"] = "Schoelje <schoelje@solydxk.com>,Clement Lefebvre <root@linuxmint.com>,Chris Hodapp <clhodapp@live.com>"
            prefs["mirrorsurl"] = 'http://packages.solydxk.com/mirrors.list'

        #Read refresh config
        section = 'refresh'
        try:
            prefs["timer_minutes"] = int(self.cfg.getValue(section, 'timer_minutes'))
            prefs["timer_hours"] = int(self.cfg.getValue(section, 'timer_hours'))
            prefs["timer_days"] = int(self.cfg.getValue(section, 'timer_days'))
        except:
            prefs["timer_minutes"] = 15
            prefs["timer_hours"] = 0
            prefs["timer_days"] = 0

        #Read update config
        section = 'update'
        try:
            prefs["delay"] = int(self.cfg.getValue(section, 'delay'))
            prefs["ping_domain"] = self.cfg.getValue(section, 'ping_domain')
            prefs["close_synaptic"] = (self.cfg.getValue(section, 'close_synaptic') == "True")
        except:
            prefs["delay"] = 30
            prefs["ping_domain"] = prefs["testdomain"]
            prefs["close_synaptic"] = True

        #Read icons config
        section = 'icons'
        try:
            prefs["icon_busy"] = self.cfg.getValue(section, 'busy')
            prefs["icon_up2date"] = self.cfg.getValue(section, 'up2date')
            prefs["icon_updates"] = self.cfg.getValue(section, 'updates')
            prefs["icon_error"] = self.cfg.getValue(section, 'error')
            prefs["icon_unknown"] = self.cfg.getValue(section, 'unknown')
            prefs["icon_apply"] = self.cfg.getValue(section, 'apply')
        except:
            prefs["icon_busy"] = os.path.join(self.sharedir, "icons/base.svg")
            prefs["icon_up2date"] = os.path.join(self.sharedir, "icons/base-apply.svg")
            prefs["icon_updates"] = os.path.join(self.sharedir, "icons/base-info.svg")
            prefs["icon_error"] = os.path.join(self.sharedir, "icons/base-error.svg")
            prefs["icon_unknown"] = os.path.join(self.sharedir, "icons/base-unknown.svg")
            prefs["icon_apply"] = os.path.join(self.sharedir, "icons/base-exec.svg")

        #Read columns config
        section = 'visible_columns'
        try:
            prefs["package_column_visible"] = (self.cfg.getValue(section, 'package') == "True")
        except:
            prefs["package_column_visible"] = True
        try:
            prefs["old_version_column_visible"] = (self.cfg.getValue(section, 'old_version') == "True")
        except:
            prefs["old_version_column_visible"] = True
        try:
            prefs["new_version_column_visible"] = (self.cfg.getValue(section, 'new_version') == "True")
        except:
            prefs["new_version_column_visible"] = True
        try:
            prefs["size_column_visible"] = (self.cfg.getValue(section, 'size') == "True")
        except:
            prefs["size_column_visible"] = True

        #Read window dimensions
        try:
            section = 'dimensions'
            prefs["dimensions_x"] = int(self.cfg.getValue(section, 'x'))
            prefs["dimensions_y"] = int(self.cfg.getValue(section, 'y'))
            prefs["dimensions_pane_position"] = int(self.cfg.getValue(section, 'pane_position'))
        except:
            prefs["dimensions_x"] = 790
            prefs["dimensions_y"] = 540
            prefs["dimensions_pane_position"] = 230

        #Read package blacklist
        try:
            section = 'packages'
            prefs["blacklisted_packages"] = self.cfg.getValue(section, 'blacklisted_packages')
        except:
            prefs["blacklisted_packages"] = []

        return prefs

    def open_repositories(self, widget):
        if os.path.exists("/usr/bin/software-properties-gtk"):
            os.system("/usr/bin/software-properties-gtk &")
        elif os.path.exists("/usr/bin/software-properties-kde"):
            os.system("/usr/bin/software-properties-kde &")

    def open_preferences(self, widget):
        self.prefWindow.set_title(_("Preferences") + " - " + _("Update Manager"))

        self.builder.get_object("lblAutoRefresh").set_text(_("Auto-Refresh"))
        self.builder.get_object("lblRefreshInterval").set_text(_("Refresh the list of updates every:"))
        self.builder.get_object("lblRefreshNote").set_text("<i>" + _("Note: The list only gets refreshed while the update manager window is closed (system tray mode).") + "</i>")
        self.builder.get_object("lblRefreshNote").set_use_markup(True)
        self.builder.get_object("lblUpdateMethod").set_text(_("Update Method"))
        self.builder.get_object("lblIcons").set_text(_("Icons"))
        self.builder.get_object("lblIcon").set_markup("<b>" + _("Icon") + "</b>")
        self.builder.get_object("lblStatus").set_markup("<b>" + _("Status") + "</b>")
        self.builder.get_object("lblNewIcon").set_markup("<b>" + _("New Icon") + "</b>")
        self.builder.get_object("lblBusy").set_text(_("Busy"))
        self.builder.get_object("lblSystemUTD").set_text(_("System up-to-date"))
        self.builder.get_object("lblUpdatesAvailable").set_text(_("Updates available"))
        self.builder.get_object("lblError").set_text(_("Error"))
        self.builder.get_object("lblUnknown").set_text(_("Unknown state"))
        self.builder.get_object("lblApply").set_text(_("Applying updates"))
        self.builder.get_object("lblStartupDelay").set_text(_("Startup delay (in seconds):"))
        self.builder.get_object("lblInternetCheck").set_text(_("Internet check (domain name or IP address):"))
        self.builder.get_object("lblIgnoredPackages").set_text(_("Ignored packages"))
        self.builder.get_object("lblMirrors").set_text(_("Repository mirrors"))
        self.builder.get_object("lblMirrorsText").set_text(_("Select the fastest production repository"))

        self.btnCheckMirrorsSpeed.set_label(_("Check mirrors speed"))
        self.builder.get_object("checkbutton_close_synaptic").set_label(_("Close Synaptic progress window after upgrade"))

        self.prefWindow.set_icon_from_file(self.prefs["icon_busy"])

        self.builder.get_object("button_icon_busy").connect("clicked", self.change_icon, "busy")
        self.builder.get_object("button_icon_up2date").connect("clicked", self.change_icon, "up2date")
        self.builder.get_object("button_icon_updates").connect("clicked", self.change_icon, "updates")
        self.builder.get_object("button_icon_error").connect("clicked", self.change_icon, "error")
        self.builder.get_object("button_icon_unknown").connect("clicked", self.change_icon, "unknown")
        self.builder.get_object("button_icon_apply").connect("clicked", self.change_icon, "apply")

        self.prefs = self.read_configuration()

        self.builder.get_object("timer_minutes_label").set_text(_("minutes"))
        self.builder.get_object("timer_hours_label").set_text(_("hours"))
        self.builder.get_object("timer_days_label").set_text(_("days"))
        self.builder.get_object("timer_minutes").set_value(self.prefs["timer_minutes"])
        self.builder.get_object("timer_hours").set_value(self.prefs["timer_hours"])
        self.builder.get_object("timer_days").set_value(self.prefs["timer_days"])
        self.builder.get_object("ping_domain").set_text(self.prefs["ping_domain"])
        self.builder.get_object("spin_delay").set_value(self.prefs["delay"])
        self.builder.get_object("checkbutton_close_synaptic").set_active(self.prefs["close_synaptic"])

        if os.path.exists(self.prefs["icon_busy"]):
            self.builder.get_object("image_busy").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.prefs["icon_busy"], 24, 24))
        if os.path.exists(self.prefs["icon_up2date"]):
            self.builder.get_object("image_up2date").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.prefs["icon_up2date"], 24, 24))
        if os.path.exists(self.prefs["icon_updates"]):
            self.builder.get_object("image_updates").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.prefs["icon_updates"], 24, 24))
        if os.path.exists(self.prefs["icon_error"]):
            self.builder.get_object("image_error").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.prefs["icon_error"], 24, 24))
        if os.path.exists(self.prefs["icon_unknown"]):
            self.builder.get_object("image_unknown").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.prefs["icon_unknown"], 24, 24))
        if os.path.exists(self.prefs["icon_apply"]):
            self.builder.get_object("image_apply").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.prefs["icon_apply"], 24, 24))

        # Blacklisted packages
        #self.treeview_blacklist.show()
        model = gtk.TreeStore(str)
        model.set_sort_column_id(0, gtk.SORT_ASCENDING)
        self.treeview_blacklist.set_model(model)

        if os.path.exists(self.cfgignored):
            ignored_list = open(self.cfgignored, "r")
            for ignored_pkg in ignored_list:
                itr = model.insert_before(None, None)
                model.set_value(itr, 0, ignored_pkg.strip())
            del model
            ignored_list.close()

        # Fill mirror list
        if self.mirrors:
            # Fill treeview
            columnTypesList = ['bool', 'str', 'str', 'str', 'str']
            self.treeview_mirrors_handler.fillTreeview(self.mirrors, columnTypesList, 0, 400, True)

        self.prefWindow.show()

    def getMirrors(self):
        mirrors = None
        mirrorsList = os.path.join(self.curdir, 'mirrors.list')

        try:
            #print self.prefs["mirrorsurl"]
            txt = urllib2.urlopen(self.prefs["mirrorsurl"]).read()
            #print txt
            if txt != '':
                fle = open(mirrorsList, 'w')
                fle.write(txt)
                fle.close()
        except:
            pass

        if os.path.exists(mirrorsList):
            reader = csv.reader(open(mirrorsList, "r"))
            mirrorData = list(reader)
            if mirrorData:
                mirrors = [[_("Current"), _("Country"), _("Repository"), _("URL"), _("Speed")]]
                for mirror in  mirrorData:
                    if mirror:
                        #print ">>> mirror = %s" % str(mirror)
                        blnCurrent = self.isUrlInSources(mirror[2])
                        mirrors.append([blnCurrent, mirror[0], mirror[1], mirror[2], ''])
        return mirrors

    def isUrlInSources(self, url):
        blnRet = False
        for repo in self.repos:
            if url in repo:
                blnRet = True
                break
        return blnRet

    def checkMirrorsSpeed(self, widget):
        self.prefWindow.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
        self.btnCheckMirrorsSpeed.set_sensitive(False)
        t = MirrorGetSpeed(self.mirrors, self.queue, self.log)
        self.threads['mirrorspeed'] = t
        t.daemon = True
        t.start()
        self.queue.join()
        glib.timeout_add(5, self.checkMirrorsSpeedThread)

    def checkMirrorsSpeedThread(self):
        if self.threads['mirrorspeed'].is_alive():
            return True

        del self.threads['mirrorspeed']
        try:
            speeds = self.queue.get()
            if speeds:
                model = self.treeview_mirrors.get_model()
                itr = model.get_iter_first()
                while itr is not None:
                    repo = model.get_value(itr, 3)
                    for repoSpeed in speeds:
                        if repoSpeed[0] == repo:
                            if self.isNumeric(repoSpeed[1]):
                                model.set_value(itr, 4, "%s Kb/s" % str(repoSpeed[1]))
                            else:
                                model.set_value(itr, 4, str(repoSpeed[1]))
                            break
                    itr = model.iter_next(itr)
                self.treeview_mirrors.set_model(model)
            self.btnCheckMirrorsSpeed.set_sensitive(True)
            self.prefWindow.window.set_cursor(None)
        except Exception, detail:
            print detail
            self.btnCheckMirrorsSpeed.set_sensitive(True)
            self.prefWindow.window.set_cursor(None)

    def isNumeric(self, n):
        try:
            n = complex(n)
            return True
        except:
            try:
                n = float(n, 0)
                return True
            except:
                try:
                    n = int(n, 0)
                    return True
                except:
                    return False

    def add_blacklisted_package(self, widget):
        dialog = gtk.MessageDialog(None, gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_QUESTION, gtk.BUTTONS_OK, None)
        dialog.set_markup("<b>" + _("Please enter a package name:") + "</b>")
        dialog.set_title(_("Ignore a package"))
        dialog.set_icon_from_file(self.prefs["icon_busy"])
        entry = gtk.Entry()
        hbox = gtk.HBox()
        hbox.pack_start(gtk.Label(_("Package name:")), False, 5, 5)
        hbox.pack_end(entry)
        dialog.format_secondary_markup("<i>" + _("All available upgrades for this package will be ignored.") + "</i>")
        dialog.vbox.pack_end(hbox, True, True, 0)
        dialog.show_all()
        dialog.run()
        name = entry.get_text()
        dialog.destroy()
        pkg = name.strip()
        if pkg != '':
            model = self.treeview_blacklist.get_model()
            itr = model.insert_before(None, None)
            model.set_value(itr, 0, pkg)

    def remove_blacklisted_package(self, widget):
        selection = self.treeview_blacklist.get_selection()
        (model, itr) = selection.get_selected()
        if (itr is not None):
            #pkg = model.get_value(itr, 0)
            model.remove(itr)

    def treeview_mirrors_toggle(self, obj, path, colNr, toggleValue):
        path = int(path)
        model = self.treeview_mirrors.get_model()
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

    def open_history(self, widget):
        #Set the Glade file
        self.histWindow.set_icon_from_file(self.prefs["icon_busy"])
        self.histWindow.set_title(_("History of updates") + " - " + _("Update Manager"))

        self.treeview_history.show()
        model = gtk.TreeStore(str, str, str, str)    # (date, packageName, oldVersion, newVersion)
        if (os.path.exists(self.historyLog)):
            updates = commands.getoutput("cat %s" % self.historyLog)
            updates = string.split(updates, "\n")
            for pkg in updates:
                values = string.split(pkg, "\t")
                if len(values) == 4:
                    date = values[0]
                    package = values[1]
                    oldVersion = values[2]
                    newVersion = values[3]

                    itr = model.insert_after(None, None)
                    model.set_value(itr, INDEX_HISTORY_DATE, date)
                    model.row_changed(model.get_path(itr), itr)
                    model.set_value(itr, INDEX_HISTORY_PACKAGE_NAME, package)
                    model.set_value(itr, INDEX_HISTORY_OLD_VERSION, oldVersion)
                    model.set_value(itr, INDEX_HISTORY_NEW_VERSION, newVersion)

        self.treeview_history.set_model(model)
        del model
        self.histWindow.show()
        #self.builder.get_object("hist_button_close").connect("clicked", self.history_cancel, wTree)
        #self.builder.get_object("hist_button_clear").connect("clicked", self.history_clear, treeview_update)

    def open_pack_info(self, widget):
        #Set the Glade file
        self.packWindow.set_icon_from_file(self.prefs["icon_busy"])
        self.packWindow.set_title(_("Update Pack Info") + " - " + _("Update Manager"))

        #i18n
        self.builder.get_object("label_system_configuration").set_text(_("Your system configuration:"))
        self.builder.get_object("label_update_pack_available").set_text(_("Current Update Pack available:"))
        self.builder.get_object("label_update_pack_installed").set_text(_("Latest Update Pack used by this system:"))

        # Check APT configuration
        config_str = "<span color='red'><b>" + _("Could not identify your APT sources") + "</b></span>"
        solydxk_repo_url = None

        try:
            # There's 3 valid configurations (for main repo, multimedia and security):
            #
            #      1. Not recommended, fully rolling: Debian Testing, multimedia, security
            #      2. Recommended, Latest update packs: LM_Latest, LM_Latest_Multimedia, LM_Latest_Security
            #      3. For testers, Incoming update packs: LM_Incoming, LM_Incoming_Multimedia, LM_Incoming_Security

            # Which repo do the sources use for the main archive?
            main_points_to_debian = False
            main_points_to_production = False
            main_points_to_testing = False
            main_points_to_solydxk = False

            # Which repo do the sources use for multimedia?
            multimedia_points_to_debian = False
            multimedia_points_to_production = False
            multimedia_points_to_testing = False

            # Which repo do the sources use for security?
            security_points_to_debian = False
            security_points_to_production = False
            #security_points_to_testing = False

            solydxk_is_here = False    # Is the repo itself present?

            for repo in self.repos:
                repo = repo.strip().strip("/")
                #if repo.endswith('Packages.bz2'):
                #Check SOLYDXK from mirror list
                #print ">>> repo = %s" % repo
                xk = False
                for mirror in self.mirrors:
                    #print "    mirror = %s" % mirror
                    if mirror[3] in repo:
                        #print "    repo found"
                        xk = True
                        break

                if xk:
                    solydxk_is_here = True
                    #print "solydxk_is_here"
                    #Check main archive
                    if 'production' in repo:
                        #print "solydxk production"
                        main_points_to_production = True
                        main_points_to_solydxk = True
                        #Check multimedia (multimedia is in UP process)
                        if 'multimedia' in repo:
                            #print "solydxk production multimedia"
                            multimedia_points_to_production = True
                        else:
                            solydxk_repo_url = repo
                            #print "repo = %s" % repo
                    elif 'testing' in repo:
                        #print "solydxk testing"
                        main_points_to_testing = True
                        main_points_to_solydxk = True
                        if 'multimedia' in repo:
                            #print "solydxk testing multimedia"
                            multimedia_points_to_testing = True
                        else:
                            solydxk_repo_url = repo
                            #print "repo = %s" % repo
                    #Check security (security is NOT in UP process)
                    elif 'security' in repo:
                        #print "solydxk security"
                        security_points_to_production = True
                else:
                    #print "NOT solydxk"
                    if 'debian.org/debian' in repo and '//ftp.' in repo:
                        #print "debian"
                        main_points_to_debian = True
                    elif 'debian-multimedia.org' in repo or 'deb-multimedia.org' in repo:
                        #print "debian multimedia"
                        multimedia_points_to_debian = True
                    elif 'security.debian.org' in repo:
                        #print "debian security"
                        security_points_to_debian = True

            isc = self.builder.get_object("image_system_config")
            if main_points_to_debian and main_points_to_solydxk:
                #Conflict between DEBIAN and SOLYDXK
                config_str = _("Your system is pointing to " + self.prefs["repdebian"] + " and " + self.prefs["repurldebian"]) + "\n" + _("These repositories conflict with each other")
                isc.set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
            elif main_points_to_testing and main_points_to_production:
                #Conflict between SOLYDXK_TESTING and SOLYDXK_PRODUCTION
                config_str = _("Your system is pointing to " + self.prefs["repurldebian"] + "/production and " + self.prefs["repurldebian"] + "/testing") + "\n" + _("These repositories conflict with each other")
                isc.set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
            elif not solydxk_is_here:
                #Missing SOLYDXK
                config_str = _("Your system is not pointing to the SolydXK repositories") + "\n" + _("Add \"deb http://" + self.prefs["repurl"] + "/ solydxk main upstream import \" to your APT sources")
                isc.set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
            elif not (main_points_to_solydxk or main_points_to_debian):
                #Missing DEBIAN or SOLYDXK
                config_str = _("Your system is not pointing to any Debian repository") + "\n" + _("Add \"deb http://" + self.prefs["repurldebian"] + "/production testing main contrib non-free\" to your APT sources")
                isc.set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
            else:
                if main_points_to_debian:
                    config_str = _("Your system is pointing directly to Debian") + "\n" + _("This is only recommended for experienced users")
                    isc.set_from_stock(gtk.STOCK_DIALOG_WARNING, gtk.ICON_SIZE_SMALL_TOOLBAR)
                elif main_points_to_testing:
                    if multimedia_points_to_debian:
                        config_str = _("Your system is pointing directly at deb-multimedia.org") + "\n" + _("Replace \"deb http://deb-multimedia.org testing main non-free\" with \"deb http://" + self.prefs["repurldebian"] + "/testing/multimedia testing main non-free\" in your APT sources")
                        isc.set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
                    elif security_points_to_debian:
                        config_str = _("Your system is pointing directly at security.debian.org") + "\n" + _("Replace \"deb http://security.debian.org testing/updates main contrib non-free\" with \"deb http://" + self.prefs["repurldebian"] + "/security testing/updates main contrib non-free\" in your APT sources")
                        isc.set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
                    elif (multimedia_points_to_production or security_points_to_production):
                        config_str = _("Some of your repositories point to production, others point to testing") + "\n" + _("Please check your APT sources.")
                        isc.set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
                    else:
                        config_str = _("Your system is pointing to the \"SolydXK testing\" repository") + "\n" + _("This is only recommend for experienced users")
                        isc.set_from_stock(gtk.STOCK_DIALOG_WARNING, gtk.ICON_SIZE_SMALL_TOOLBAR)
                elif main_points_to_production:
                    if multimedia_points_to_debian:
                        config_str = _("Your system is pointing directly at deb-multimedia.org") + "\n" + _("Replace \"deb http://deb-multimedia.org testing main non-free\" with \"deb http://" + self.prefs["repurldebian"] + "/production/multimedia testing main non-free\" in your APT sources")
                        isc.set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
                    elif security_points_to_debian:
                        config_str = _("Your system is pointing directly at security.debian.org") + "\n" + _("Replace \"deb http://security.debian.org testing/updates main contrib non-free\" with \"deb http://" + self.prefs["repurldebian"] + "/security testing/updates main contrib non-free\" in your APT sources")
                        isc.set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
                    elif (multimedia_points_to_testing):
                        config_str = _("Some of your repositories point to production, but multimedia to testing") + "\n" + _("Please check your APT sources.")
                        isc.set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
                    else:
                        config_str = _("Your system is pointing to the \"SolydXK production\" repository")
                        isc.set_from_stock(gtk.STOCK_DIALOG_INFO, gtk.ICON_SIZE_SMALL_TOOLBAR)
        except Exception, detail:
            print detail

        if solydxk_repo_url is not None:
            scrolledContainer = self.builder.get_object("scrolled_pack_info")
            children = scrolledContainer.get_children()
            if children:
                browser = children[0]
            else:
                browser = webkit.WebView()
                # Add browser to widget
                scrolledContainer.add(browser)
                # listen for clicks of links
                browser.connect("new-window-policy-decision-requested", self.on_nav_request)
                browser.connect("button-press-event", lambda w, e: e.button == 3)
            url = "%s/update-pack.html" % solydxk_repo_url
            browser.open(url)
            browser.show()

        self.builder.get_object("label_system_configuration_value").set_markup("<b>%s</b>" % config_str)
        self.builder.get_object("label_update_pack_available_value").set_markup("<b>%s</b>" % self.serverUpVersion)
        self.builder.get_object("label_update_pack_installed_value").set_markup("<b>%s</b>" % self.localUpVersion)

        self.packWindow.show()

    def on_nav_request(self, browser, frame, request, action, decision, *args, **kwargs):
        # User clicked on a <a href link: open uri in new tab or new default browser
        reason = action.get_reason()
        if (reason == 0):    # = WEBKIT_WEB_NAVIGATION_REASON_LINK_CLICKED
            if decision is not None:
                decision.ignore()
                uri = request.get_uri()
                webbrowser.open_new_tab(uri)
        else:
            if decision is not None:
                decision.use()

    def close_pack_info(self, widget):
        self.packWindow.hide()

    def open_information(self, widget):
        self.infoWindow.set_title(_("Update Manager Log"))
        self.infoWindow.set_icon_from_file(self.prefs["icon_busy"])
        self.builder.get_object("lblPermissions").set_text(_("Permissions:"))
        self.builder.get_object("lblProcessID").set_text(_("Process ID:"))
        self.builder.get_object("lblLogFile").set_text(_("Log file:"))

        self.builder.get_object("mode_label").set_text(str(self.mode))
        self.builder.get_object("processid_label").set_text(str(self.pid))
        self.builder.get_object("log_filename").set_text(str(self.logFile))

        if os.path.exists(self.logFile):
            logText = commands.getoutput("cat %s" % self.logFile)
        else:
            logText = "No log file found"

        txtbuffer = gtk.TextBuffer()
        txtbuffer.set_text(logText)
        self.builder.get_object("log_textview").set_buffer(txtbuffer)
        self.infoWindow.show()

    def open_about(self, widget):
        dlg = gtk.AboutDialog()
        dlg.set_title(_("About") + " - " + _("Update Manager"))
        dlg.set_program_name("updatemanager")
        dlg.set_comments(_("Update Manager") + " %s" % self.version)
        try:
            h = open('/usr/share/common-licenses/GPL', 'r')
            s = h.readlines()
            gpl = ""
            for line in s:
                gpl += line
            h.close()
            dlg.set_license(gpl)
        except Exception, detail:
            print detail

        dlg.set_authors(self.prefs["authors"])
        dlg.set_icon_from_file(self.prefs["icon_busy"])
        dlg.set_logo(gtk.gdk.pixbuf_new_from_file(self.prefs["icon_busy"]))

        def close(w, res):
            if res == gtk.RESPONSE_CANCEL:
                w.hide()
        dlg.connect("response", close)
        dlg.show()

    def quit_cb(self, widget, data=None):
        if data:
            data.set_visible(False)
        try:
            self.log.write(_("Exiting - requested by user"), 'UM.quit_cb', 'info')
            self.save_window_size(self.umWindow, self.vpaned_main)
        except:
            pass    # cause log might already been closed
        # Whatever works best heh :)
        pid = os.getpid()
        os.system("kill -9 %s &" % pid)

    def popup_menu_cb(self, widget, button, time, data=None):
        if button == 3:
            if data:
                data.show_all()
                data.popup(None, None, None, 3, time)
        pass

    def close_window(self, window, event):
        window.hide()
        self.save_window_size(window, self.vpaned_main)
        self.app_hidden = True
        return True

    def hide_window(self, widget):
        self.umWindow.hide()
        self.app_hidden = True

    def activate_icon_cb(self, widget, data):
        if self.app_hidden:
                # check credentials
            if os.getuid() != 0:
                try:
                    self.log.write(_("Launching updatemanager in root mode..."), 'UM.activate_icon_cb', 'info')
                except:
                    pass    # cause we might have closed it already
                os.system("gksudo --message \"" + _("Please enter your password to start the update manager") + "\" " + self.curdir + "/updatemanager.py show &")
            else:
                self.umWindow.show()
                self.app_hidden = False
        else:
            self.umWindow.hide()
            self.app_hidden = True
            self.save_window_size(self.umWindow, self.vpaned_main)

    def save_window_size(self, window, vpaned):
        section = 'dimensions'
        self.cfg.setValue(section, 'x', window.get_size()[0])
        self.cfg.setValue(section, 'y', window.get_size()[1])
        self.cfg.setValue(section, 'pane_position', vpaned.get_position())

    def display_selected_package(self, selection):
        self.builder.get_object("textview_description").get_buffer().set_text("")
        self.builder.get_object("textview_changes").get_buffer().set_text("")
        (model, itr) = selection.get_selected()
        if (itr is not None):
            #selected_package = model.get_value(itr, INDEX_PACKAGE_NAME)
            description_txt = model.get_value(itr, INDEX_DESCRIPTION)
            self.builder.get_object("notebook_details").set_current_page(0)
            self.builder.get_object("textview_description").get_buffer().set_text(description_txt)

    def switch_page(self, notebook, page, page_num):
        selection = self.treeview_update.get_selection()
        (model, itr) = selection.get_selected()
        if (itr is not None):
            selected_package = model.get_value(itr, INDEX_PACKAGE_NAME)
            description_txt = model.get_value(itr, INDEX_DESCRIPTION)
            if (page_num == 0):
                # Description tab
                self.builder.get_object("textview_description").get_buffer().set_text(description_txt)
            if (page_num == 1):
                # Changelog tab
                version = model.get_value(itr, INDEX_NEW_VERSION)
                retriever = ChangelogRetriever(selected_package, version, self.builder, self.prefs)
                retriever.start()

    def celldatafunction_checkbox(self, column, cell, model, itr):
        cell.set_property("activatable", True)
        checked = model.get_value(itr, INDEX_UPGRADE)
        if (checked == "true"):
            cell.set_property("active", True)
        else:
            cell.set_property("active", False)

    def toggled(self, renderer, path, treeview, statusbar, context_id):
        model = treeview.get_model()
        itr = model.get_iter(path)
        if (itr is not None):
            checked = model.get_value(itr, INDEX_UPGRADE)
            if (checked == "true"):
                model.set_value(itr, INDEX_UPGRADE, "false")
            else:
                model.set_value(itr, INDEX_UPGRADE, "true")

        itr = model.get_iter_first()
        download_size = 0
        num_selected = 0
        while (itr is not None):
            checked = model.get_value(itr, INDEX_UPGRADE)
            if (checked == "true"):
                size = model.get_value(itr, INDEX_SIZE)
                download_size = download_size + size
                num_selected = num_selected + 1
            itr = model.iter_next(itr)
        if num_selected == 0:
            statusbar.push(context_id, _("No updates selected"))
        elif num_selected == 1:
            statusbar.push(context_id, _("%(selected)d update selected (%(size)s)") % {'selected':num_selected, 'size':self.size_to_string(download_size)})
        else:
            statusbar.push(context_id, _("%(selected)d updates selected (%(size)s)") % {'selected':num_selected, 'size':self.size_to_string(download_size)})

    def size_to_string(self, size):
        strSize = str(size) + _("B")
        if (size >= 1024):
            strSize = str(size / 1024) + _("KB")
        if (size >= (1024 * 1024)):
            strSize = str(size / (1024 * 1024)) + _("MB")
        if (size >= (1024 * 1024 * 1024)):
            strSize = str(size / (1024 * 1024 * 1024)) + _("GB")
        return strSize

    def setVisibleColumn(self, checkmenuitem, column, configName):
        section = 'visible_columns'
        self.cfg.setValue(section, configName, checkmenuitem.get_active())
        column.set_visible(checkmenuitem.get_active())

    def menuPopup(self, widget, event):
        if event.button == 3:
            (model, iter) = widget.get_selection().get_selected()
            if (iter is not None):
                selected_package = model.get_value(iter, INDEX_PACKAGE_NAME)
                menu = gtk.Menu()
                menuItem = gtk.MenuItem(_("Ignore updates for this package"))
                menuItem.connect("activate", self.add_to_ignore_list, selected_package)
                menu.append(menuItem)
                menu.show_all()
                menu.popup(None, None, None, 3, 0)

    def add_to_ignore_list(self, widget, pkg):
        with open(self.cfgignored, "a") as fle:
            fle.write(pkg)
        self.force_refresh(widget)

    # ===============================================
    # Main
    # ===============================================

    def main(self, argv):
        self.log.write(_("Launching updatemanager in %(mode)s...") % { "mode": self.mode }, 'UM.main', 'info')

        # Initiate threading
        gtk.gdk.threads_init()

        try:
            # Get the window socket (needed for synaptic later on)
            if os.getuid() != 0:
                # If we're not in root mode do that (don't know why it's needed.. very weird)
                socket = gtk.Socket()
                self.vbox_main.pack_start(socket, True, True, 0)
                socket.show()
                window_id = repr(socket.get_id())

            # the treeview
            cr = gtk.CellRendererToggle()
            cr.connect("toggled", self.toggled, self.treeview_update, self.statusbar, self.context_id)
            column_upgrade = gtk.TreeViewColumn(_("Upgrade"), cr)
            column_upgrade.set_cell_data_func(cr, self.celldatafunction_checkbox)
            column_upgrade.set_sort_column_id(INDEX_UPGRADE)
            column_upgrade.set_resizable(True)

            column_package = gtk.TreeViewColumn(_("Package"), gtk.CellRendererText(), text=INDEX_PACKAGE_NAME)
            column_package.set_sort_column_id(INDEX_PACKAGE_NAME)
            column_package.set_resizable(True)

            column_old_version = gtk.TreeViewColumn(_("Old version"), gtk.CellRendererText(), text=INDEX_OLD_VERSION)
            column_old_version.set_sort_column_id(INDEX_OLD_VERSION)
            column_old_version.set_resizable(True)

            column_new_version = gtk.TreeViewColumn(_("New version"), gtk.CellRendererText(), text=INDEX_NEW_VERSION)
            column_new_version.set_sort_column_id(INDEX_NEW_VERSION)
            column_new_version.set_resizable(True)

            column_size = gtk.TreeViewColumn(_("Size"), gtk.CellRendererText(), text=INDEX_STR_SIZE)
            column_size.set_sort_column_id(INDEX_SIZE)
            column_size.set_resizable(True)

            self.treeview_update.append_column(column_upgrade)
            self.treeview_update.append_column(column_package)
            self.treeview_update.append_column(column_old_version)
            self.treeview_update.append_column(column_new_version)
            self.treeview_update.append_column(column_size)
            self.treeview_update.set_headers_clickable(True)
            self.treeview_update.set_reorderable(False)
            self.treeview_update.show()

            model = gtk.TreeStore(str, str, str, str, int, str, str, str)    # upgrade, pkgname, oldversion, newversion, size, strsize, description, sourcePackage)
            model.set_sort_column_id(INDEX_PACKAGE_NAME, gtk.SORT_ASCENDING)
            self.treeview_update.set_model(model)
            del model

            # Build status icon menu
            menu = gtk.Menu()
            menuItem3 = gtk.ImageMenuItem(gtk.STOCK_REFRESH)
            menuItem3.connect('activate', self.force_refresh)
            menu.append(menuItem3)
            menuItem2 = gtk.ImageMenuItem(gtk.STOCK_DIALOG_INFO)
            menuItem2.connect('activate', self.open_information)
            menu.append(menuItem2)
            if os.getuid() == 0:
                menuItem4 = gtk.ImageMenuItem(gtk.STOCK_PREFERENCES)
                menuItem4.connect('activate', self.open_preferences)
                menu.append(menuItem4)
            menuItem = gtk.ImageMenuItem(gtk.STOCK_QUIT)
            menuItem.connect('activate', self.quit_cb)
            menu.append(menuItem)
            self.statusIcon.connect('activate', self.activate_icon_cb, None)
            self.statusIcon.connect('popup-menu', self.popup_menu_cb, menu)

            # Set text for all visible widgets (because of i18n)
            self.builder.get_object("tool_pack_info").set_label(_("Update Pack Info"))
            self.builder.get_object("tool_apply").set_label(_("Install Updates"))
            self.builder.get_object("tool_refresh").set_label(_("Refresh"))
            self.builder.get_object("tool_select_all").set_label(_("Select All"))
            self.builder.get_object("tool_clear").set_label(_("Clear"))
            self.builder.get_object("lblDescription").set_text(_("Description"))
            self.builder.get_object("lblChangelog").set_text(_("Changelog"))

            self.builder.get_object("label_error_detail").set_text("")
            self.builder.get_object("hbox_error").hide()
            self.builder.get_object("scrolledwindow1").hide()
            self.builder.get_object("viewport_error").hide()
            self.builder.get_object("label_error_detail").hide()
            self.builder.get_object("main_image_error").hide()
            self.vpaned_main.set_position(self.prefs['dimensions_pane_position'])

            fileMenu = gtk.MenuItem(_("_File"))
            fileSubmenu = gtk.Menu()
            fileMenu.set_submenu(fileSubmenu)
            closeMenuItem = gtk.ImageMenuItem(gtk.STOCK_CLOSE)
            closeMenuItem.get_child().set_text(_("Close"))
            closeMenuItem.connect("activate", self.hide_window)
            fileSubmenu.append(closeMenuItem)

            editMenu = gtk.MenuItem(_("_Edit"))
            editSubmenu = gtk.Menu()
            editMenu.set_submenu(editSubmenu)
            prefsMenuItem = gtk.ImageMenuItem(gtk.STOCK_PREFERENCES)
            prefsMenuItem.get_child().set_text(_("Preferences"))
            prefsMenuItem.connect("activate", self.open_preferences)
            editSubmenu.append(prefsMenuItem)

            if os.path.exists("/usr/bin/software-properties-gtk") or os.path.exists("/usr/bin/software-properties-kde"):
                sourcesMenuItem = gtk.ImageMenuItem(gtk.STOCK_PREFERENCES)
                sourcesMenuItem.set_image(gtk.image_new_from_file(os.path.join(self.sharedir, 'icons/software-properties.png')))
                sourcesMenuItem.get_child().set_text(_("Software sources"))
                sourcesMenuItem.connect("activate", self.open_repositories)
                editSubmenu.append(sourcesMenuItem)

            viewMenu = gtk.MenuItem(_("_View"))
            viewSubmenu = gtk.Menu()
            viewMenu.set_submenu(viewSubmenu)
            historyMenuItem = gtk.ImageMenuItem(gtk.STOCK_INDEX)
            historyMenuItem.get_child().set_text(_("History of updates"))
            historyMenuItem.connect("activate", self.open_history)
            infoMenuItem = gtk.ImageMenuItem(gtk.STOCK_DIALOG_INFO)
            infoMenuItem.get_child().set_text(_("Log"))
            infoMenuItem.connect("activate", self.open_information)
            visibleColumnsMenuItem = gtk.MenuItem(gtk.STOCK_DIALOG_INFO)
            visibleColumnsMenuItem.get_child().set_text(_("Visible columns"))
            visibleColumnsMenu = gtk.Menu()
            visibleColumnsMenuItem.set_submenu(visibleColumnsMenu)

            packageColumnMenuItem = gtk.CheckMenuItem(_("Package"))
            packageColumnMenuItem.set_active(self.prefs["package_column_visible"])
            column_package.set_visible(self.prefs["package_column_visible"])
            packageColumnMenuItem.connect("toggled", self.setVisibleColumn, column_package, "package")
            visibleColumnsMenu.append(packageColumnMenuItem)

            oldVersionColumnMenuItem = gtk.CheckMenuItem(_("Old version"))
            oldVersionColumnMenuItem.set_active(self.prefs["old_version_column_visible"])
            column_old_version.set_visible(self.prefs["old_version_column_visible"])
            oldVersionColumnMenuItem.connect("toggled", self.setVisibleColumn, column_old_version, "old_version")
            visibleColumnsMenu.append(oldVersionColumnMenuItem)

            newVersionColumnMenuItem = gtk.CheckMenuItem(_("New version"))
            newVersionColumnMenuItem.set_active(self.prefs["new_version_column_visible"])
            column_new_version.set_visible(self.prefs["new_version_column_visible"])
            newVersionColumnMenuItem.connect("toggled", self.setVisibleColumn, column_new_version, "new_version")
            visibleColumnsMenu.append(newVersionColumnMenuItem)

            sizeColumnMenuItem = gtk.CheckMenuItem(_("Size"))
            sizeColumnMenuItem.set_active(self.prefs["size_column_visible"])
            column_size.set_visible(self.prefs["size_column_visible"])
            sizeColumnMenuItem.connect("toggled", self.setVisibleColumn, column_size, "size")
            visibleColumnsMenu.append(sizeColumnMenuItem)

            viewSubmenu.append(visibleColumnsMenuItem)
            viewSubmenu.append(historyMenuItem)
            viewSubmenu.append(infoMenuItem)

            helpMenu = gtk.MenuItem(_("_Help"))
            helpSubmenu = gtk.Menu()
            helpMenu.set_submenu(helpSubmenu)
            aboutMenuItem = gtk.ImageMenuItem(gtk.STOCK_ABOUT)
            aboutMenuItem.get_child().set_text(_("About"))
            aboutMenuItem.connect("activate", self.open_about)
            helpSubmenu.append(aboutMenuItem)

            #browser.connect("activate", browser_callback)
            #browser.show()
            self.builder.get_object("menubar_main").append(fileMenu)
            self.builder.get_object("menubar_main").append(editMenu)
            self.builder.get_object("menubar_main").append(viewMenu)
            self.builder.get_object("menubar_main").append(helpMenu)

            if len(sys.argv) > 1:
                showWindow = sys.argv[1]
                if (showWindow == "show"):
                    self.umWindow.show_all()
                    self.builder.get_object("label_error_detail").set_text("")
                    self.builder.get_object("hbox_error").hide()
                    self.builder.get_object("scrolledwindow1").hide()
                    self.builder.get_object("viewport_error").hide()
                    self.builder.get_object("label_error_detail").hide()
                    self.builder.get_object("main_image_error").hide()
                    self.vpaned_main.set_position(self.prefs['dimensions_pane_position'])
                    self.app_hidden = False

                    # Repaint before you continue, or else updatemanager in SolydX hangs
                    functions.repaintGui()

            if os.getuid() != 0:
                #test the network connection to delay updatemanager in case we're not yet connected
                self.log.write(_("Testing initial connection"), 'UM.main', 'info')
                try:
                    url = urllib2.urlopen('http://' + self.prefs["testdomain"])
                    url.read()
                    url.close()
                    self.log.write(_("Connection to the Internet successful (tried to read http://%(domain)s)") % { "domain": self.prefs["testdomain"] }, 'UM.main', 'info')
                except Exception, detail:
                    print detail
                    if os.system("ping " + self.prefs["ping_domain"] + " -c1 -q"):
                        self.log.write(_("No connection found (tried to read http://%(domain)s), and to ping %(ping)s - sleeping for %(delay)s seconds") % { "domain": self.prefs["testdomain"], "ping": self.prefs["ping_domain"], "delay": str(self.prefs["delay"]) }, 'UM.main', 'info')
                        time.sleep(self.prefs["delay"])
                    else:
                        self.log.write(_("Connection found - checking for updates..."), 'UM.main', 'info')

            if os.geteuid() == 0:
                self.umWindow.show()
            self.builder.get_object("notebook_details").set_current_page(0)
            refresh = RefreshThread(self.treeview_update, self.statusIcon, self.builder, self.prefs, self.log, self.newUpVersion)
            refresh.start()
            auto_refresh = AutomaticRefreshThread(self.treeview_update, self.statusIcon, self.builder, self.prefs, self.log, self.app_hidden)
            auto_refresh.start()

            gtk.main()

        except Exception, detail:
            print detail
            self.log.write(_("Exception occured in main thread: %(error)s") % { "error": str(details) }, 'UM.main', 'error')


if __name__ == '__main__':
    # Flush print when it's called
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)
    # Create an instance of our GTK application
    app = UM()
    args = sys.argv[1:]
    app.main(args)
