#!/usr/bin/env python

try:
    import pygtk
    pygtk.require("2.0")
    import os
    import commands
    import string
    import gtk
    import gtk.glade
    import tempfile
    import threading
    import time
    import fnmatch
    import gettext
    import subprocess
    from execcmd import ExecCmd
except Exception, detail:
    print detail
    exit(1)

# i18n
gettext.install("updatemanager", "/usr/share/locale")

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

class AutomaticRefreshThread(threading.Thread):
    def __init__(self, treeView, statusIcon, builder, prefs, log, app_hidden):
        threading.Thread.__init__(self)
        self.treeView = treeView
        self.statusIcon = statusIcon
        self.builder = builder
        self.prefs = prefs
        self.log = log
        self.app_hidden = app_hidden

    def run(self):

        try:
            while(True):
                timer = (self.prefs["timer_minutes"] * 60) + (self.prefs["timer_hours"] * 60 * 60) + (self.prefs["timer_days"] * 24 * 60 * 60)

                try:
                    self.log.write("Auto-refresh timer is going to sleep for %(days)s days, %(hours)s hours, %(minutes)s minutes" % { "days": str(self.prefs["timer_days"]), "hours": str(self.prefs["timer_hours"]), "minutes": str(self.prefs["timer_minutes"]) }, 'AutomaticRefreshThread.run', 'debug')
                except:
                    pass    # cause it might be closed already
                timetosleep = int(timer)
                if (timetosleep == 0):
                    time.sleep(60)    # sleep 1 minute, don't mind the config we don't want an infinite loop to go nuts :)
                else:
                    time.sleep(timetosleep)
                    if self.app_hidden:
                        try:
                            self.log.write("Updatemanager is in tray mode, performing auto-refresh", "AutomaticRefreshThread.run", "debug")
                        except:
                            pass    # cause it might be closed already
                        # Refresh
                        refresh = RefreshThread(self.treeView, self.statusIcon, self.builder, self.prefs, self.log, self.app_hidden)
                        refresh.start()
                    else:
                        try:
                            self.log.write("The updatemanager window is open, skipping auto-refresh", "AutomaticRefreshThread.run", "debug")
                        except:
                            pass    # cause it might be closed already

        except Exception, detail:
            try:
                self.log.write(str(detail), "AutomaticRefreshThread.run", "exception")
                self.log.flush()
            except:
                pass    # cause it might be closed already


class InstallThread(threading.Thread):

    def __init__(self, treeView, statusIcon, builder, prefs, log, newUpVersion, upHistFile, rtobject=None):
        threading.Thread.__init__(self)
        self.treeView = treeView
        self.statusIcon = statusIcon
        self.builder = builder
        self.window = self.builder.get_object("umWindow")
        self.newUpVersion = newUpVersion
        self.upHistFile = upHistFile
        self.prefs = prefs
        self.log = log
        self.curdir = os.path.dirname(os.path.realpath(__file__))
        self.sharedir = os.path.join(self.curdir.replace('/lib/', '/share/'))
        self.ec = ExecCmd(rtobject, self.log.logPath)

    def run(self):
        try:
            self.log.write(_("Install requested by user - check packages to install"), "InstallThread.run", "info")
            self.setParent(False)
            installNeeded = False

            packages = []
            model = self.treeView.get_model()
            itr = model.get_iter_first()
            history = open("/var/log/updatemanager.history", "a")
            while (itr is not None):
                checked = model.get_value(itr, INDEX_UPGRADE)
                if (checked == "true"):
                    installNeeded = True
                    package = model.get_value(itr, INDEX_PACKAGE_NAME)
                    oldVersion = model.get_value(itr, INDEX_OLD_VERSION)
                    newVersion = model.get_value(itr, INDEX_NEW_VERSION)
                    history.write(commands.getoutput('date +"%Y.%m.%d %H:%M:%S"') + "\t" + package + "\t" + oldVersion + "\t" + newVersion + "\n")
                    packages.append(package)
                    self.log.write("Install package request: %(pck)s" % { "pck": str(package) }, "InstallThread.run", "debug")
                itr = model.iter_next(itr)
            history.close()

            if installNeeded:
                proceed = True
                try:
                    pkgs = ' '.join(str(pkg) for pkg in packages)
                    warnings = commands.getoutput(self.curdir + "/checkWarnings.py %s" % pkgs)
                    #print (curdir + "/checkWarnings.py %s" % pkgs)
                    warnings = warnings.split("###")
                    if len(warnings) == 2:
                        installations = warnings[0].split()
                        removals = warnings[1].split()
                        if len(installations) > 0 or len(removals) > 0:
                            gtk.gdk.threads_enter()
                            try:
                                dialog = gtk.MessageDialog(None, gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_WARNING, gtk.BUTTONS_OK_CANCEL, None)
                                dialog.set_title("")
                                dialog.set_markup("<b>" + _("This upgrade will trigger additional changes") + "</b>")
                                dialog.set_icon_from_file(self.prefs["icon_busy"])
                                dialog.set_default_size(640, 480)

                                if len(removals) > 0:
                                    # Removals
                                    label = gtk.Label()
                                    if len(removals) == 1:
                                        label.set_text(_("The following package will be removed:"))
                                    else:
                                        label.set_text(_("The following %d packages will be removed:") % len(removals))
                                    label.set_alignment(0, 0.5)
                                    scrolledWindow = gtk.ScrolledWindow()
                                    scrolledWindow.set_shadow_type(gtk.SHADOW_IN)
                                    scrolledWindow.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
                                    treeview = gtk.TreeView()
                                    column1 = gtk.TreeViewColumn("", gtk.CellRendererText(), text=0)
                                    column1.set_sort_column_id(0)
                                    column1.set_resizable(True)
                                    treeview.append_column(column1)
                                    treeview.set_headers_clickable(False)
                                    treeview.set_reorderable(False)
                                    treeview.set_headers_visible(False)
                                    model = gtk.TreeStore(str)
                                    removals.sort()
                                    for pkg in removals:
                                        itr = model.insert_before(None, None)
                                        model.set_value(itr, 0, pkg)
                                    treeview.set_model(model)
                                    treeview.show()
                                    scrolledWindow.add(treeview)
                                    dialog.vbox.add(label)
                                    dialog.vbox.add(scrolledWindow)

                                if len(installations) > 0:
                                    # Installations
                                    label = gtk.Label()
                                    if len(installations) == 1:
                                        label.set_text(_("The following package will be installed:"))
                                    else:
                                        label.set_text(_("The following %d packages will be installed:") % len(installations))
                                    label.set_alignment(0, 0.5)
                                    scrolledWindow = gtk.ScrolledWindow()
                                    scrolledWindow.set_shadow_type(gtk.SHADOW_IN)
                                    scrolledWindow.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
                                    treeview = gtk.TreeView()
                                    column1 = gtk.TreeViewColumn("", gtk.CellRendererText(), text=0)
                                    column1.set_sort_column_id(0)
                                    column1.set_resizable(True)
                                    treeview.append_column(column1)
                                    treeview.set_headers_clickable(False)
                                    treeview.set_reorderable(False)
                                    treeview.set_headers_visible(False)
                                    model = gtk.TreeStore(str)
                                    installations.sort()
                                    for pkg in installations:
                                        itr = model.insert_before(None, None)
                                        model.set_value(itr, 0, pkg)
                                    treeview.set_model(model)
                                    treeview.show()
                                    scrolledWindow.add(treeview)
                                    dialog.vbox.add(label)
                                    dialog.vbox.add(scrolledWindow)

                                dialog.show_all()
                                if dialog.run() == gtk.RESPONSE_OK:
                                    proceed = True
                                else:
                                    proceed = False
                                dialog.destroy()
                            except Exception, detail:
                                print detail
                            gtk.gdk.threads_leave()
                        else:
                            proceed = True
                except Exception, details:
                    print details

                if proceed:
                    gtk.gdk.threads_enter()
                    self.statusIcon.set_from_file(self.prefs["icon_apply"])
                    self.statusIcon.set_tooltip(_("Installing updates"))
                    gtk.gdk.threads_leave()

                    # Check for pre-install script and execute if it exists
                    if self.newUpVersion is not None:
                        preScript = os.path.join(self.curdir, self.newUpVersion + '.pre')
                        if os.path.exists(preScript):
                            cmd = "/bin/bash %s" % preScript
                            self.log.write(_("Pre-install script started: %(pre)s") % { "pre": preScript }, "InstallThread.run", "info")
                            self.ec.run(cmd)
                            self.log.write("Pre-install script finished: %(pre)s" % { "pre": preScript }, "InstallThread.run", "debug")

                    self.log.write(_("Launch Synaptic to start the upgrade"), "InstallThread.run", "info")
                    closeSynaptic = str(self.prefs["close_synaptic"]).lower()
                    if closeSynaptic != 'true' and closeSynaptic != 'false':
                        closeSynaptic = 'true'
                    cmd = ["sudo", "/usr/sbin/synaptic", "--hide-main-window",
                            "--non-interactive", "--parent-window-id", "%s" % self.window.window.xid]
                    cmd.append("-o")
                    cmd.append("Synaptic::closeZvt=%s" % closeSynaptic)
                    cmd.append("--progress-str")
                    cmd.append("\"" + _("Please wait, this can take some time") + "\"")
                    cmd.append("--finish-str")
                    cmd.append("\"" + _("Update is complete") + "\"")
                    f = tempfile.NamedTemporaryFile()
                    for pkg in packages:
                        f.write("%s\tinstall\n" % pkg)
                    cmd.append("--set-selections-file")
                    cmd.append("%s" % f.name)
                    f.flush()
                    self.log.write("Synaptic command = %(cmd)s" % { "cmd": ' '.join(cmd) }, "InstallThread.run", "debug")
                    self.ec.run(' '.join(cmd))
                    self.log.write(_("Synaptic has finished the upgrade"), "InstallThread.run", "info")
                    f.close()

                    # Check for post install script and execute if it exists
                    if self.newUpVersion is not None:
                        postScript = os.path.join(self.curdir, self.newUpVersion + '.post')
                        if os.path.exists(postScript):
                            cmd = "/bin/bash %s" % postScript
                            self.log.write(_("Post-install script started: %(post)s") % { "post": postScript }, "InstallThread.run", "info")
                            self.ec.run(cmd)
                            self.log.write("Post-install script finished: %(post)s" % { "post": postScript }, "InstallThread.run", "debug")

                        # Save new UP version
                        self.log.write(_("write new UP version %(newUpVersion)s to %(uphist)s/") % { "newUpVersion": self.newUpVersion, "uphist": self.upHistFile }, "InstallThread.run", "info")
                        upList = []
                        if os.path.exists(self.upHistFile):
                            with open(self.upHistFile) as fle:
                                upList  = fle.readlines()
                        cleanList = []
                        for version in upList:
                            version = version.strip()
                            version = version[len(version) - 10:]
                            if version not in cleanList and version != self.newUpVersion:
                                cleanList.append(version)
                        cleanList.append(self.newUpVersion)
                        with open(self.upHistFile, "w") as fle:
                            fle.write("\n".join(cleanList))

                    self.log.write(_("Installation finished"), "InstallThread.run", "info")

                    if ("updatemanager" in packages):
                        # Restart
                        try:
                            self.log.write(_("Updatemanager was updated, restarting it in root mode..."), 'InstallThread.run', 'info')
                        except:
                            pass    # cause we might have closed it already
                        os.system("gksudo --message \"" + _("Please enter your password to restart the update manager") + "\" " + self.curdir + "/updatemanager.py show &")
                    else:
                        # Refresh
                        msg = _("Checking for updates")
                        self.setParent(True, self.prefs["icon_busy"], msg)
                        self.log.write(msg, "InstallThread.run", "info")
                        refresh = RefreshThread(self.treeView, self.statusIcon, self.builder, self.prefs, self.log, True)
                        refresh.start()
                else:
                    # Stop the blinking but don't refresh
                    self.log.write(_("Installation aborted"), "InstallThread.run", "info")
                    self.setParent(True)
            else:
                # Stop the blinking but don't refresh
                self.log.write(_("No installation needed"), "InstallThread.run", "info")
                self.setParent(True)

        except Exception, detail:
            self.log.write(str(detail), "InstallThread.run", "exception")
            msg = _("Could not install the security updates")
            self.setParent(True, self.prefs["icon_error"], msg)
            self.log.write(msg, "InstallThread.run", "error")

    def setParent(self, enable, statusIcon=None, statusString=None):
        cur = None
        sensitive = True
        if not enable:
            cur = gtk.gdk.Cursor(gtk.gdk.WATCH)
            sensitive = False

        if statusIcon is not None:
            self.statusIcon.set_from_file(statusIcon)
        if statusString is not None:
            self.statusIcon.set_tooltip(statusString)

        gtk.gdk.threads_enter()
        self.window.window.set_cursor(cur)
        #self.window.set_sensitive(sensitive)
        self.builder.get_object("menubar_main").set_sensitive(sensitive)
        self.builder.get_object("toolbar_main").set_sensitive(sensitive)
        self.builder.get_object("vpaned_main").set_sensitive(sensitive)
        gtk.gdk.threads_leave()


class RefreshThread(threading.Thread):

    def __init__(self, treeview_update, statusIcon, builder, prefs, log, app_hidden, newUpVersion=None):
        threading.Thread.__init__(self)
        self.treeview_update = treeview_update
        self.statusIcon = statusIcon
        self.builder = builder
        self.window = self.builder.get_object("umWindow")
        self.prefs = prefs
        self.log = log
        self.app_hidden = app_hidden
        self.newUpVersion = newUpVersion
        self.curdir = os.path.dirname(os.path.realpath(__file__))
        self.cfgignored = os.path.join(self.curdir, 'updatemanager.ignored')
        self.ec = ExecCmd()
        self.statusString = ""

    def run(self):
        gtk.gdk.threads_enter()
        vpaned_position = self.builder.get_object("vpaned_main").get_position()
        gtk.gdk.threads_leave()
        try:
            self.log.write(_("Starting refresh..."), "RefreshThread.run", "info")
            gtk.gdk.threads_enter()

            self.window.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
            self.window.set_sensitive(False)
            self.builder.get_object("label_error_detail").set_text("")
            self.builder.get_object("hbox_error").hide()
            self.builder.get_object("scrolledwindow1").hide()
            self.builder.get_object("viewport_error").hide()
            self.builder.get_object("label_error_detail").hide()
            self.builder.get_object("main_image_error").hide()
            # Starts the blinking
            self.statusIcon.set_from_file(self.prefs["icon_busy"])
            self.statusIcon.set_tooltip(_("Checking for updates"))
            self.builder.get_object("vpaned_main").set_position(vpaned_position)
            #self.statusIcon.set_blinking(True)
            gtk.gdk.threads_leave()

            model = gtk.TreeStore(str, str, str, str, int, str, str, str)    # upgrade, pkgname, oldversion, newversion, size, strsize, description, sourcePackage)
            model.set_sort_column_id(1, gtk.SORT_ASCENDING)

            # Check to see if no other APT process is running
            cmd = 'ps -U root -o comm'
            pslist = self.ec.run(cmd, False)
            running = False
            for process in pslist:
                if process.strip() in ["dpkg", "apt-get", "synaptic", "update-manager", "adept", "adept-notifier"]:
                    running = True
                    break
            if running:
                gtk.gdk.threads_enter()
                self.statusString = _("Another application is using APT")
                self.statusIcon.set_from_file(self.prefs["icon_unknown"])
                self.statusIcon.set_tooltip(self.statusString)
                self.log.write(self.statusString, "RefreshThread.run", "info")
                #self.statusIcon.set_blinking(False)
                self.window.window.set_cursor(None)
                self.window.set_sensitive(True)
                gtk.gdk.threads_leave()
                return False

            gtk.gdk.threads_enter()
            self.statusString = _("Finding the list of updates...")
            self.log.write(self.statusString, "RefreshThread.run", "info")
            self.builder.get_object("vpaned_main").set_position(vpaned_position)
            gtk.gdk.threads_leave()
            if self.app_hidden:
                updates = commands.getoutput(self.curdir + "/checkAPT.py | grep \"###\"")
            else:
                updates = commands.getoutput(self.curdir + "/checkAPT.py --use-synaptic %s | grep \"###\"" % self.window.window.xid)

            if "ERROR###" in updates:
                self.statusString = _("An error has occurred while updating the apt cache. Please, check your sources.list")
                self.log.write(self.statusString, "RefreshThread.run", "error")
                self.builder.get_object("notebook_details").set_current_page(0)
                self.window.window.set_cursor(None)
                self.window.set_sensitive(True)
                gtk.gdk.threads_leave()
            else:
                # Look for updatemanager
                if ("UPDATE###updatemanager###" in updates):
                    new_updatemanager = True
                else:
                    new_updatemanager = False

                updates = string.split(updates, "\n")

                # Look at the packages one by one
                list_of_packages = ""
                num_updates = 0
                download_size = 0
                num_ignored = 0
                ignored_list = []
                if os.path.exists(self.cfgignored):
                    blacklist_file = open(self.cfgignored, "r")
                    for blacklist_line in blacklist_file:
                        ignored_list.append(blacklist_line.strip())
                    blacklist_file.close()

                if (len(updates) is None):
                    self.statusIcon.set_from_file(self.prefs["icon_up2date"])
                    self.statusString = _("Your system is up to date")
                    self.statusIcon.set_tooltip(self.statusString)
                    self.log.write(self.statusString, "RefreshThread.run", "info")
                else:
                    for pkg in updates:
                        values = string.split(pkg, "###")
                        if len(values) == 7:
                            status = values[0]
                            if (status == "ERROR"):
                                error_msg = commands.getoutput(os.path.join(self.curdir, "checkAPT.py"))
                                gtk.gdk.threads_enter()
                                self.statusIcon.set_from_file(self.prefs["icon_error"])
                                self.statusString = _("Could not refresh the list of packages")
                                self.statusIcon.set_tooltip(self.statusString)
                                self.log.write(self.statusString, "RefreshThread.run", "info")
                                self.builder.get_object("label_error_detail").set_text(error_msg)
                                self.builder.get_object("label_error_detail").show()
                                self.builder.get_object("viewport1").show()
                                self.builder.get_object("scrolledwindow1").show()
                                self.builder.get_object("main_image_error").show()
                                self.builder.get_object("hbox_error").show()
                                #self.statusIcon.set_blinking(False)
                                self.window.window.set_cursor(None)
                                self.window.set_sensitive(True)
                                #statusbar.push(context_id, _(""))
                                gtk.gdk.threads_leave()
                                return False
                            package = values[1]
                            packageIsBlacklisted = False
                            for blacklist in ignored_list:
                                if fnmatch.fnmatch(package, blacklist):
                                    num_ignored = num_ignored + 1
                                    packageIsBlacklisted = True
                                    break

                            if packageIsBlacklisted:
                                continue

                            newVersion = values[2]
                            oldVersion = values[3]
                            size = int(values[4])
                            source_package = values[5]
                            description = values[6]

                            strSize = self.size_to_string(size)

                            if (new_updatemanager):
                                if (package == "updatemanager"):
                                    list_of_packages = list_of_packages + " " + package
                                    itr = model.insert_before(None, None)
                                    model.set_value(itr, INDEX_UPGRADE, "true")
                                    model.row_changed(model.get_path(itr), itr)
                                    model.set_value(itr, INDEX_PACKAGE_NAME, package)
                                    model.set_value(itr, INDEX_OLD_VERSION, oldVersion)
                                    model.set_value(itr, INDEX_NEW_VERSION, newVersion)
                                    model.set_value(itr, INDEX_SIZE, size)
                                    model.set_value(itr, INDEX_STR_SIZE, strSize)
                                    model.set_value(itr, INDEX_DESCRIPTION, description)
                                    model.set_value(itr, INDEX_SOURCE_PACKAGE, source_package)
                                    num_updates = num_updates + 1
                            else:
                                list_of_packages = list_of_packages + " " + package
                                itr = model.insert_before(None, None)
                                model.set_value(itr, INDEX_UPGRADE, "true")
                                download_size = download_size + size
                                model.row_changed(model.get_path(itr), itr)
                                model.set_value(itr, INDEX_PACKAGE_NAME, package)
                                model.set_value(itr, INDEX_OLD_VERSION, oldVersion)
                                model.set_value(itr, INDEX_NEW_VERSION, newVersion)
                                model.set_value(itr, INDEX_SIZE, size)
                                model.set_value(itr, INDEX_STR_SIZE, strSize)
                                model.set_value(itr, INDEX_DESCRIPTION, description)
                                model.set_value(itr, INDEX_SOURCE_PACKAGE, source_package)
                                num_updates = num_updates + 1

                    gtk.gdk.threads_enter()

                    if (new_updatemanager):
                        self.statusString = _("A new version of the update manager is available")
                        self.statusIcon.set_from_file(self.prefs["icon_updates"])
                        self.statusIcon.set_tooltip(self.statusString)
                        self.log.write(self.statusString, "RefreshThread.run", "info")
                    else:
                        if self.newUpVersion is not None:
                            self.statusString = _("A new update pack is available (version: %s)" % self.newUpVersion)
                            self.statusIcon.set_from_file(self.prefs["icon_updates"])
                            self.statusIcon.set_tooltip(self.statusString)
                            self.log.write(self.statusString, "RefreshThread.run", "info")
                        elif (num_updates > 0):
                            if (num_updates == 1):
                                if (num_ignored == 0):
                                    self.statusString = _("1 recommended update available (%(size)s)") % {'size': self.size_to_string(download_size)}
                                elif (num_ignored == 1):
                                    self.statusString = _("1 recommended update available (%(size)s), 1 ignored") % {'size': self.size_to_string(download_size)}
                                elif (num_ignored > 1):
                                    self.statusString = _("1 recommended update available (%(size)s), %(ignored)d ignored") % {'size': self.size_to_string(download_size), 'ignored': num_ignored}
                            else:
                                if (num_ignored == 0):
                                    self.statusString = _("%(recommended)d recommended updates available (%(size)s)") % {'recommended': num_updates, 'size': self.size_to_string(download_size)}
                                elif (num_ignored == 1):
                                    self.statusString = _("%(recommended)d recommended updates available (%(size)s), 1 ignored") % {'recommended': num_updates, 'size': self.size_to_string(download_size)}
                                elif (num_ignored > 0):
                                    self.statusString = _("%(recommended)d recommended updates available (%(size)s), %(ignored)d ignored") % {'recommended': num_updates, 'size': self.size_to_string(download_size), 'ignored': num_ignored}
                            self.statusIcon.set_from_file(self.prefs["icon_updates"])
                            self.statusIcon.set_tooltip(self.statusString)
                            self.log.write(self.statusString, "RefreshThread.run", "info")
                        else:
                            self.statusString = _("Your system is up to date")
                            self.statusIcon.set_from_file(self.prefs["icon_up2date"])
                            self.statusIcon.set_tooltip(self.statusString)
                            self.log.write(self.statusString, "RefreshThread.run", "info")

                self.log.write(_("Refresh finished"), "RefreshThread.run", "info")
                # Stop the blinking
                #self.statusIcon.set_blinking(False)
                self.builder.get_object("notebook_details").set_current_page(0)
                self.window.window.set_cursor(None)
                self.treeview_update.set_model(model)
                del model
                self.window.set_sensitive(True)
                self.builder.get_object("vpaned_main").set_position(vpaned_position)
                gtk.gdk.threads_leave()


        except Exception, detail:
            gtk.gdk.threads_enter()
            msg = _("Could not refresh the list of packages")
            self.statusIcon.set_from_file(self.prefs["icon_error"])
            self.statusIcon.set_tooltip(msg)
            self.log.write("%s: %s" % (msg, detail), "RefreshThread.run", "exception")
            #self.statusIcon.set_blinking(False)
            self.window.window.set_cursor(None)
            self.window.set_sensitive(True)
            self.builder.get_object("vpaned_main").set_position(vpaned_position)
            gtk.gdk.threads_leave()

    def size_to_string(self, size):
        strSize = str(size) + _("B")
        if (size >= 1024):
            strSize = str(size / 1024) + _("KB")
        if (size >= (1024 * 1024)):
            strSize = str(size / (1024 * 1024)) + _("MB")
        if (size >= (1024 * 1024 * 1024)):
            strSize = str(size / (1024 * 1024 * 1024)) + _("GB")
        return strSize

    def checkDependencies(self, changes, cache):
        foundSomething = False
        for pkg in changes:
            for dep in pkg.candidateDependencies:
                for o in dep.or_dependencies:
                    try:
                        if cache[o.name].isUpgradable:
                            pkgFound = False
                            for pkg2 in changes:
                                if o.name == pkg2.name:
                                    pkgFound = True
                            if not pkgFound:
                                newPkg = cache[o.name]
                                changes.append(newPkg)
                                foundSomething = True
                    except Exception:
                        pass    # don't know why we get these..
        if (foundSomething):
            changes = self.checkDependencies(changes, cache)
        return changes

class CustomException(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message
