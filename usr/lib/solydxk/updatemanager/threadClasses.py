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
    from subprocess import Popen
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
        print ">>>> AutomaticRefreshThread"

    def run(self):

        try:
            while(True):
                timer = (self.prefs["timer_minutes"] * 60) + (self.prefs["timer_hours"] * 60 * 60) + (self.prefs["timer_days"] * 24 * 60 * 60)

                try:
                    self.log.writelines("++ Auto-refresh timer is going to sleep for " + str(self.prefs["timer_minutes"]) + " minutes, " + str(self.prefs["timer_hours"]) + " hours and " + str(self.prefs["timer_days"]) + " days\n")
                    self.log.flush()
                except:
                    pass    # cause it might be closed already
                timetosleep = int(timer)
                if (timetosleep == 0):
                    time.sleep(60)    # sleep 1 minute, don't mind the config we don't want an infinite loop to go nuts :)
                else:
                    time.sleep(timetosleep)
                    if self.app_hidden:
                        try:
                            self.log.writelines("++ updatemanager is in tray mode, performing auto-refresh\n")
                            self.log.flush()
                        except:
                            pass    # cause it might be closed already
                        # Refresh
                        refresh = RefreshThread(self.treeView, self.statusIcon, self.builder)
                        refresh.start()
                    else:
                        try:
                            self.log.writelines("++ The updatemanager window is open, skipping auto-refresh\n")
                            self.log.flush()
                        except:
                            pass    # cause it might be closed already

        except Exception, detail:
            try:
                self.log.writelines("-- Exception occured in the auto-refresh thread.. so it's probably dead now: " + str(detail) + "\n")
                self.log.flush()
            except:
                pass    # cause it might be closed already


class InstallThread(threading.Thread):

    def __init__(self, treeView, statusIcon, builder, prefs, log, newUpVersion, rtobject=None):
        threading.Thread.__init__(self)
        self.treeView = treeView
        self.statusIcon = statusIcon
        self.builder = builder
        self.window = self.builder.get_object("umWindow")
        self.newUpVersion = newUpVersion
        self.prefs = prefs
        self.log = log
        self.curdir = os.path.dirname(os.path.realpath(__file__))
        self.sharedir = os.path.join(self.curdir.replace('/lib/', '/share/'))
        self.ec = ExecCmd(rtobject)
        print ">>>> InstallThread"

    def run(self):

        try:
            self.log.writelines("++ Install requested by user\n")
            self.log.flush()
            gtk.gdk.threads_enter()
            self.window.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
            self.window.set_sensitive(False)
            installNeeded = False
            packages = []
            model = self.treeView.get_model()
            gtk.gdk.threads_leave()

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
                    self.log.writelines("++ Will install " + str(package) + "\n")
                    self.log.flush()
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
                                dialog.log.set_title("")
                                dialog.log.set_markup("<b>" + _("This upgrade will trigger additional changes") + "</b>")
                                #dialog.log.format_secondary_markup("<i>" + _("All available upgrades for this package will be ignored.") + "</i>")
                                dialog.log.set_icon_from_file(self.prefs["icon_busy"])
                                dialog.log.set_default_size(640, 480)

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
                                    dialog.log.vbox.add(label)
                                    dialog.log.vbox.add(scrolledWindow)

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
                            cmd = ". %s" % preScript
                            retList = self.ec.run(cmd)
                            #comnd = Popen(' ' + preScript, stdout=self.log, stderr=self.log, shell=True)
                            #returnCode = comnd.wait()
                            self.log.writelines("++ Pre-install script finished\n")

                    self.log.writelines("++ Ready to launch synaptic\n")
                    self.log.flush()
                    cmd = ["sudo", "/usr/sbin/synaptic", "--hide-main-window",
                            "--non-interactive", "--parent-window-id", "%s" % self.window.window.xid]
                    cmd.append("-o")
                    cmd.append("Synaptic::closeZvt=true")
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
                    comnd = Popen(' '.join(cmd), stdout=self.log, stderr=self.log, shell=True)
                    returnCode = comnd.wait()
                    self.log.writelines("++ Return code:" + str(returnCode) + "\n")
                    #sts = os.waitpid(comnd.pid, 0)
                    f.close()

                    # Check for post install script and execute if it exists
                    if self.newUpVersion is not None:
                        postScript = os.path.join(self.curdir, self.newUpVersion + '.post')
                        if os.path.exists(postScript):
                            cmd = ". %s" % postScript
                            retList = self.ec.run(cmd)
                            #comnd = Popen(' ' + postScript, stdout=self.log, stderr=self.log, shell=True)
                            #returnCode = comnd.wait()
                            self.log.writelines("++ Post-install script finished\n")

                    self.log.writelines("++ Install finished\n")
                    self.log.flush()

                    gtk.gdk.threads_enter()

                    self.window.hide()
                    gtk.gdk.threads_leave()

                    if ("updatemanager" in packages):
                        # Restart
                        try:
                            self.log.writelines("++ updatemanager was updated, restarting it in root mode...\n")
                            self.log.flush()
                            self.log.close()
                        except:
                            pass    # cause we might have closed it already
                        os.system("gksudo --message \"" + _("Please enter your password to restart the update manager") + "\" " + self.curdir + "/updatemanager.py show &")
                    else:
                        # Refresh
                        gtk.gdk.threads_enter()
                        self.statusIcon.set_from_file(self.prefs["icon_busy"])
                        self.statusIcon.set_tooltip(_("Checking for updates"))
                        self.window.window.set_cursor(None)
                        self.window.set_sensitive(True)
                        gtk.gdk.threads_leave()
                        refresh = RefreshThread(self.treeView, self.statusIcon, self.builder, self.prefs, self.log, True)
                        refresh.start()
                else:
                    # Stop the blinking but don't refresh
                    gtk.gdk.threads_enter()
                    self.window.window.set_cursor(None)
                    self.window.set_sensitive(True)
                    gtk.gdk.threads_leave()
            else:
                # Stop the blinking but don't refresh
                gtk.gdk.threads_enter()
                self.window.window.set_cursor(None)
                self.window.set_sensitive(True)
                gtk.gdk.threads_leave()

        except Exception, detail:
            self.log.writelines("-- Exception occured in the install thread: " + str(detail) + "\n")
            self.log.flush()
            gtk.gdk.threads_enter()
            self.statusIcon.set_from_file(self.prefs["icon_error"])
            self.statusIcon.set_tooltip(_("Could not install the security updates"))
            self.log.writelines("-- Could not install security updates\n")
            self.log.flush()
            #self.statusIcon.set_blinking(False)
            self.window.window.set_cursor(None)
            self.window.set_sensitive(True)
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
        print ">>>> RefreshThread"

    def run(self):

        gtk.gdk.threads_enter()
        vpaned_position = self.builder.get_object("vpaned_main").get_position()
        gtk.gdk.threads_leave()
        try:
            self.log.writelines("++ Starting refresh\n")
            self.log.flush()
            gtk.gdk.threads_enter()

            statusbar = self.builder.get_object("statusbar")
            context_id = statusbar.get_context_id("updatemanager")

            statusbar.push(context_id, _("Starting refresh..."))
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

            #self.prefs = read_configuration()

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
                self.statusIcon.set_from_file(self.prefs["icon_unknown"])
                self.statusIcon.set_tooltip(_("Another application is using APT"))
                statusbar.push(context_id, _("Another application is using APT"))
                self.log.writelines("-- Another application is using APT\n")
                self.log.flush()
                #self.statusIcon.set_blinking(False)
                self.window.window.set_cursor(None)
                self.window.set_sensitive(True)
                gtk.gdk.threads_leave()
                return False

            gtk.gdk.threads_enter()
            statusbar.push(context_id, _("Finding the list of updates..."))
            self.builder.get_object("vpaned_main").set_position(vpaned_position)
            gtk.gdk.threads_leave()
            if self.app_hidden:
                updates = commands.getoutput(self.curdir + "/checkAPT.py | grep \"###\"")
            else:
                updates = commands.getoutput(self.curdir + "/checkAPT.py --use-synaptic %s | grep \"###\"" % self.window.window.xid)

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
                self.statusIcon.set_tooltip(_("Your system is up to date"))
                statusbar.push(context_id, _("Your system is up to date"))
                self.log.writelines("++ System is up to date\n")
                self.log.flush()
            else:
                for pkg in updates:
                    values = string.split(pkg, "###")
                    if len(values) == 7:
                        status = values[0]
                        if (status == "ERROR"):
                            error_msg = commands.getoutput(os.path.join(self.curdir, "checkAPT.py"))
                            gtk.gdk.threads_enter()
                            self.statusIcon.set_from_file(self.prefs["icon_error"])
                            self.statusIcon.set_tooltip(_("Could not refresh the list of packages"))
                            statusbar.push(context_id, _("Could not refresh the list of packages"))
                            self.log.writelines("-- Error in checkAPT.py, could not refresh the list of packages\n")
                            self.log.flush()
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
                    statusbar.push(context_id, self.statusString)
                    self.log.writelines("++ Found a new version of updatemanager\n")
                    self.log.flush()
                else:
                    if self.newUpVersion is not None:
                        self.statusString = _("A new update pack is available (version: %s)" % self.newUpVersion)
                        self.statusIcon.set_from_file(self.prefs["icon_updates"])
                        self.statusIcon.set_tooltip(self.statusString)
                        statusbar.push(context_id, self.statusString)
                        self.log.writelines("++ %s\n" % self.statusString)
                        self.log.flush()
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
                        statusbar.push(context_id, self.statusString)
                        self.log.writelines("++ Found " + str(num_updates) + " recommended software updates\n")
                        self.log.flush()
                    else:
                        self.statusIcon.set_from_file(self.prefs["icon_up2date"])
                        self.statusIcon.set_tooltip(_("Your system is up to date"))
                        statusbar.push(context_id, _("Your system is up to date"))
                        self.log.writelines("++ System is up to date\n")
                        self.log.flush()

            self.log.writelines("++ Refresh finished\n")
            self.log.flush()
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
            print "-- Exception occured in the refresh thread: " + str(detail)
            self.log.writelines("-- Exception occured in the refresh thread: " + str(detail) + "\n")
            self.log.flush()
            gtk.gdk.threads_enter()
            self.statusIcon.set_from_file(self.prefs["icon_error"])
            self.statusIcon.set_tooltip(_("Could not refresh the list of packages"))
            #self.statusIcon.set_blinking(False)
            self.window.window.set_cursor(None)
            self.window.set_sensitive(True)
            statusbar.push(context_id, _("Could not refresh the list of packages"))
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
