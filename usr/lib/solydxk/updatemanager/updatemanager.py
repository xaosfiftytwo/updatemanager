#!/usr/bin/env python

try:
    import os
    import commands
    import sys
    import string
    import gtk
    import gtk.glade
    import tempfile
    import threading
    import time
    import gettext
    import fnmatch
    import urllib2
    from config import Config
except Exception, detail:
    print detail
    pass

try:
    import pygtk
    pygtk.require("2.0")
except Exception, detail:
    print detail
    pass

from subprocess import Popen, PIPE

try:
    nrUpdMgr = commands.getoutput("ps -A | grep updatemanager | wc -l")
    if (nrUpdMgr != "0"):
        if (os.getuid() == 0):
            os.system("killall updatemanager")
        else:
            print "Another updatemanager is already running, exiting."
            sys.exit(1)
except Exception, detail:
    print detail

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
curdir = os.path.dirname(os.path.realpath(__file__))
sharedir = os.path.join(curdir.replace('/lib/', '/share/'))

# i18n
gettext.install("updatemanager", os.path.join(sharedir, 'locale'))

# i18n for menu item
menuName = _("Update Manager")
menuGenericName = _("Software Updates")
menuComment = _("Show and install available updates")

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

# Read from config file
cfgignored = os.path.join(curdir, 'updatemanager.ignored')
cfg = Config('updatemanager.conf')
repurl = cfg.getValue('UPDATEMANAGER', 'repurl')
repurldevsubdir = cfg.getValue('UPDATEMANAGER', 'repurldevsubdir')
repurldebian = cfg.getValue('UPDATEMANAGER', 'repurldebian')
repdebian = cfg.getValue('UPDATEMANAGER', 'repdebian')
authors = cfg.getValue('UPDATEMANAGER', 'authors').split(',')
testdomain = cfg.getValue('UPDATEMANAGER', 'testdomain')


class ChangelogRetriever(threading.Thread):
    def __init__(self, source_package, version, wTree):
        threading.Thread.__init__(self)
        self.source_package = source_package
        self.version = version
        self.wTree = wTree

    def run(self):
        gtk.gdk.threads_enter()
        self.wTree.get_widget("textview_changes").get_buffer().set_text(_("Downloading changelog..."))
        gtk.gdk.threads_leave()

        changelog = ""
        if ("solydxk" in self.version) or ("solydxk" in self.source_package):
            #Get the solydxk change file for amd64
            try:
                url = urllib2.urlopen("http://" + repurl + "/" + repurldevsubdir + "/" + self.source_package + "_" + self.version + "_amd64.changes", None, 30)
                source = url.read()
                url.close()
                changes = source.split("\n")
                for change in changes:
                    change = change.strip()
                    if change.startswith("*"):
                        changelog = changelog + change + "\n"
            except:
                try:
                    url = urllib2.urlopen("http://" + repurl + "/" + repurldevsubdir + "/" + self.source_package + "_" + self.version + "_i386.changes", None, 30)
                    source = url.read()
                    url.close()
                    changes = source.split("\n")
                    for change in changes:
                        change = change.strip()
                        if change.startswith("*"):
                            changelog = changelog + change + "\n"
                except:
                    changelog = _("No changelog available")
        else:
            try:
                source = commands.getoutput("aptitude changelog " + self.source_package)
                changes = source.split("urgency=")[1].split("\n")
                for change in changes:
                    change = change.strip()
                    if change.startswith("*"):
                        changelog = changelog + change + "\n"
            except Exception, detail:
                print detail
                changelog = _("No changelog available") + "\n" + _("Click on Edit->Software Sources and tick the 'Source code' option to enable access to the changelogs")

        gtk.gdk.threads_enter()
        self.wTree.get_widget("textview_changes").get_buffer().set_text(changelog)
        gtk.gdk.threads_leave()


class AutomaticRefreshThread(threading.Thread):
    def __init__(self, treeView, statusIcon, wTree):
        threading.Thread.__init__(self)
        self.treeView = treeView
        self.statusIcon = statusIcon
        self.wTree = wTree

    def run(self):
        global app_hidden
        global log
        try:
            while(True):
                prefs = read_configuration()
                timer = (prefs["timer_minutes"] * 60) + (prefs["timer_hours"] * 60 * 60) + (prefs["timer_days"] * 24 * 60 * 60)

                try:
                    log.writelines("++ Auto-refresh timer is going to sleep for " + str(prefs["timer_minutes"]) + " minutes, " + str(prefs["timer_hours"]) + " hours and " + str(prefs["timer_days"]) + " days\n")
                    log.flush()
                except:
                    pass    # cause it might be closed already
                timetosleep = int(timer)
                if (timetosleep == 0):
                    time.sleep(60)    # sleep 1 minute, don't mind the config we don't want an infinite loop to go nuts :)
                else:
                    time.sleep(timetosleep)
                    if app_hidden:
                        try:
                            log.writelines("++ updatemanager is in tray mode, performing auto-refresh\n")
                            log.flush()
                        except:
                            pass    # cause it might be closed already
                        # Refresh
                        refresh = RefreshThread(self.treeView, self.statusIcon, self.wTree)
                        refresh.start()
                    else:
                        try:
                            log.writelines("++ The updatemanager window is open, skipping auto-refresh\n")
                            log.flush()
                        except:
                            pass    # cause it might be closed already

        except Exception, detail:
            try:
                log.writelines("-- Exception occured in the auto-refresh thread.. so it's probably dead now: " + str(detail) + "\n")
                log.flush()
            except:
                pass    # cause it might be closed already


class InstallThread(threading.Thread):
    global icon_busy
    global icon_up2date
    global icon_updates
    global icon_error
    global icon_unknown
    global icon_apply

    def __init__(self, treeView, statusIcon, wTree):
        threading.Thread.__init__(self)
        self.treeView = treeView
        self.statusIcon = statusIcon
        self.wTree = wTree

    def run(self):
        global log
        try:
            log.writelines("++ Install requested by user\n")
            log.flush()
            gtk.gdk.threads_enter()
            self.wTree.get_widget("window1").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
            self.wTree.get_widget("window1").set_sensitive(False)
            installNeeded = False
            packages = []
            model = self.treeView.get_model()
            gtk.gdk.threads_leave()

            iter = model.get_iter_first()
            history = open("/var/log/updatemanager.history", "a")
            while (iter is not None):
                checked = model.get_value(iter, INDEX_UPGRADE)
                if (checked == "true"):
                    installNeeded = True
                    package = model.get_value(iter, INDEX_PACKAGE_NAME)
                    oldVersion = model.get_value(iter, INDEX_OLD_VERSION)
                    newVersion = model.get_value(iter, INDEX_NEW_VERSION)
                    history.write(commands.getoutput('date +"%Y.%m.%d %H:%M:%S"') + "\t" + package + "\t" + oldVersion + "\t" + newVersion + "\n")
                    packages.append(package)
                    log.writelines("++ Will install " + str(package) + "\n")
                    log.flush()
                iter = model.iter_next(iter)
            history.close()

            if installNeeded:

                proceed = True
                try:
                    pkgs = ' '.join(str(pkg) for pkg in packages)
                    warnings = commands.getoutput(curdir + "/checkWarnings.py %s" % pkgs)
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
                                #dialog.format_secondary_markup("<i>" + _("All available upgrades for this package will be ignored.") + "</i>")
                                dialog.set_icon_from_file(os.path.join(sharedir, "icons/base.svg"))
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
                                        iter = model.insert_before(None, None)
                                        model.set_value(iter, 0, pkg)
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
                                        iter = model.insert_before(None, None)
                                        model.set_value(iter, 0, pkg)
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
                    self.statusIcon.set_from_file(icon_apply)
                    self.statusIcon.set_tooltip(_("Installing updates"))
                    gtk.gdk.threads_leave()

                    log.writelines("++ Ready to launch synaptic\n")
                    log.flush()
                    cmd = ["sudo", "/usr/sbin/synaptic", "--hide-main-window",
                            "--non-interactive", "--parent-window-id", "%s" % self.wTree.get_widget("window1").window.xid]
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
                    comnd = Popen(' '.join(cmd), stdout=log, stderr=log, shell=True)
                    returnCode = comnd.wait()
                    log.writelines("++ Return code:" + str(returnCode) + "\n")
                    #sts = os.waitpid(comnd.pid, 0)
                    f.close()
                    log.writelines("++ Install finished\n")
                    log.flush()

                    gtk.gdk.threads_enter()
                    global app_hidden
                    app_hidden = True
                    self.wTree.get_widget("window1").hide()
                    gtk.gdk.threads_leave()

                    if ("updatemanager" in packages) or ("updatemanager" in packages):
                        # Restart
                        try:
                            log.writelines("++ updatemanager was updated, restarting it in root mode...\n")
                            log.flush()
                            log.close()
                        except:
                            pass    # cause we might have closed it already
                        os.system("gksudo --message \"" + _("Please enter your password to restart the update manager") + "\" " + curdir + "/updatemanager.py show &")
                    else:
                        # Refresh
                        gtk.gdk.threads_enter()
                        self.statusIcon.set_from_file(icon_busy)
                        self.statusIcon.set_tooltip(_("Checking for updates"))
                        self.wTree.get_widget("window1").window.set_cursor(None)
                        self.wTree.get_widget("window1").set_sensitive(True)
                        gtk.gdk.threads_leave()
                        refresh = RefreshThread(self.treeView, self.statusIcon, self.wTree)
                        refresh.start()
                else:
                    # Stop the blinking but don't refresh
                    gtk.gdk.threads_enter()
                    self.wTree.get_widget("window1").window.set_cursor(None)
                    self.wTree.get_widget("window1").set_sensitive(True)
                    gtk.gdk.threads_leave()
            else:
                # Stop the blinking but don't refresh
                gtk.gdk.threads_enter()
                self.wTree.get_widget("window1").window.set_cursor(None)
                self.wTree.get_widget("window1").set_sensitive(True)
                gtk.gdk.threads_leave()

        except Exception, detail:
            log.writelines("-- Exception occured in the install thread: " + str(detail) + "\n")
            log.flush()
            gtk.gdk.threads_enter()
            self.statusIcon.set_from_file(icon_error)
            self.statusIcon.set_tooltip(_("Could not install the security updates"))
            log.writelines("-- Could not install security updates\n")
            log.flush()
            #self.statusIcon.set_blinking(False)
            self.wTree.get_widget("window1").window.set_cursor(None)
            self.wTree.get_widget("window1").set_sensitive(True)
            gtk.gdk.threads_leave()


class RefreshThread(threading.Thread):
    global icon_busy
    global icon_up2date
    global icon_updates
    global icon_error
    global statusbar
    global context_id

    def __init__(self, treeview_update, statusIcon, wTree):
        threading.Thread.__init__(self)
        self.treeview_update = treeview_update
        self.statusIcon = statusIcon
        self.wTree = wTree

    def run(self):
        global log
        global app_hidden
        gtk.gdk.threads_enter()
        vpaned_position = wTree.get_widget("vpaned1").get_position()
        gtk.gdk.threads_leave()
        try:
            log.writelines("++ Starting refresh\n")
            log.flush()
            gtk.gdk.threads_enter()
            statusbar.push(context_id, _("Starting refresh..."))
            self.wTree.get_widget("window1").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
            self.wTree.get_widget("window1").set_sensitive(False)
            self.wTree.get_widget("label_error_detail").set_text("")
            self.wTree.get_widget("hbox_error").hide()
            self.wTree.get_widget("scrolledwindow1").hide()
            self.wTree.get_widget("viewport1").hide()
            self.wTree.get_widget("label_error_detail").hide()
            self.wTree.get_widget("image_error").hide()
            # Starts the blinking
            self.statusIcon.set_from_file(icon_busy)
            self.statusIcon.set_tooltip(_("Checking for updates"))
            wTree.get_widget("vpaned1").set_position(vpaned_position)
            #self.statusIcon.set_blinking(True)
            gtk.gdk.threads_leave()

            model = gtk.TreeStore(str, str, str, str, int, str, str, str)    # upgrade, pkgname, oldversion, newversion, size, strsize, description, sourcePackage)
            model.set_sort_column_id(1, gtk.SORT_ASCENDING)

            #prefs = read_configuration()

            # Check to see if no other APT process is running
            p1 = Popen(['ps', '-U', 'root', '-o', 'comm'], stdout=PIPE)
            p = p1.communicate()[0]
            running = False
            pslist = p.split('\n')
            for process in pslist:
                if process.strip() in ["dpkg", "apt-get", "synaptic", "update-manager", "adept", "adept-notifier"]:
                    running = True
                    break
            if running:
                gtk.gdk.threads_enter()
                self.statusIcon.set_from_file(icon_unknown)
                self.statusIcon.set_tooltip(_("Another application is using APT"))
                statusbar.push(context_id, _("Another application is using APT"))
                log.writelines("-- Another application is using APT\n")
                log.flush()
                #self.statusIcon.set_blinking(False)
                self.wTree.get_widget("window1").window.set_cursor(None)
                self.wTree.get_widget("window1").set_sensitive(True)
                gtk.gdk.threads_leave()
                return False

            gtk.gdk.threads_enter()
            statusbar.push(context_id, _("Finding the list of updates..."))
            wTree.get_widget("vpaned1").set_position(vpaned_position)
            gtk.gdk.threads_leave()
            if app_hidden:
                updates = commands.getoutput(curdir + "/checkAPT.py | grep \"###\"")
            else:
                updates = commands.getoutput(curdir + "/checkAPT.py --use-synaptic %s | grep \"###\"" % self.wTree.get_widget("window1").window.xid)

            # Look for updatemanager
            if ("UPDATE###updatemanager###" in updates) or ("UPDATE###updatemanager###" in updates):
                new_update = True
            else:
                new_update = False

            updates = string.split(updates, "\n")

            # Look at the packages one by one
            list_of_packages = ""
            num_updates = 0
            download_size = 0
            num_ignored = 0
            ignored_list = []
            if os.path.exists(cfgignored):
                blacklist_file = open(cfgignored, "r")
                for blacklist_line in blacklist_file:
                    ignored_list.append(blacklist_line.strip())
                blacklist_file.close()

            if (len(updates) is None):
                self.statusIcon.set_from_file(icon_up2date)
                self.statusIcon.set_tooltip(_("Your system is up to date"))
                statusbar.push(context_id, _("Your system is up to date"))
                log.writelines("++ System is up to date\n")
                log.flush()
            else:
                for pkg in updates:
                    values = string.split(pkg, "###")
                    if len(values) == 7:
                        status = values[0]
                        if (status == "ERROR"):
                            error_msg = commands.getoutput(os.path.join(curdir, "checkAPT.py"))
                            gtk.gdk.threads_enter()
                            self.statusIcon.set_from_file(icon_error)
                            self.statusIcon.set_tooltip(_("Could not refresh the list of packages"))
                            statusbar.push(context_id, _("Could not refresh the list of packages"))
                            log.writelines("-- Error in checkAPT.py, could not refresh the list of packages\n")
                            log.flush()
                            self.wTree.get_widget("label_error_detail").set_text(error_msg)
                            self.wTree.get_widget("label_error_detail").show()
                            self.wTree.get_widget("viewport1").show()
                            self.wTree.get_widget("scrolledwindow1").show()
                            self.wTree.get_widget("image_error").show()
                            self.wTree.get_widget("hbox_error").show()
                            #self.statusIcon.set_blinking(False)
                            self.wTree.get_widget("window1").window.set_cursor(None)
                            self.wTree.get_widget("window1").set_sensitive(True)
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

                        strSize = size_to_string(size)

                        if (new_update):
                            if (package == "updatemanager") or (package == "updatemanager"):
                                list_of_packages = list_of_packages + " " + package
                                iter = model.insert_before(None, None)
                                model.set_value(iter, INDEX_UPGRADE, "true")
                                model.row_changed(model.get_path(iter), iter)
                                model.set_value(iter, INDEX_PACKAGE_NAME, package)
                                model.set_value(iter, INDEX_OLD_VERSION, oldVersion)
                                model.set_value(iter, INDEX_NEW_VERSION, newVersion)
                                model.set_value(iter, INDEX_SIZE, size)
                                model.set_value(iter, INDEX_STR_SIZE, strSize)
                                model.set_value(iter, INDEX_DESCRIPTION, description)
                                model.set_value(iter, INDEX_SOURCE_PACKAGE, source_package)
                                num_updates = num_updates + 1
                        else:
                            list_of_packages = list_of_packages + " " + package
                            iter = model.insert_before(None, None)
                            model.set_value(iter, INDEX_UPGRADE, "true")
                            download_size = download_size + size
                            model.row_changed(model.get_path(iter), iter)
                            model.set_value(iter, INDEX_PACKAGE_NAME, package)
                            model.set_value(iter, INDEX_OLD_VERSION, oldVersion)
                            model.set_value(iter, INDEX_NEW_VERSION, newVersion)
                            model.set_value(iter, INDEX_SIZE, size)
                            model.set_value(iter, INDEX_STR_SIZE, strSize)
                            model.set_value(iter, INDEX_DESCRIPTION, description)
                            model.set_value(iter, INDEX_SOURCE_PACKAGE, source_package)
                            num_updates = num_updates + 1

                gtk.gdk.threads_enter()
                if (new_update):
                    self.statusString = _("A new version of the update manager is available")
                    self.statusIcon.set_from_file(icon_updates)
                    self.statusIcon.set_tooltip(self.statusString)
                    statusbar.push(context_id, self.statusString)
                    log.writelines("++ Found a new version of updatemanager\n")
                    log.flush()
                else:
                    if (num_updates > 0):
                        if (num_updates == 1):
                            if (num_ignored == 0):
                                self.statusString = _("1 recommended update available (%(size)s)") % {'size':size_to_string(download_size)}
                            elif (num_ignored == 1):
                                self.statusString = _("1 recommended update available (%(size)s), 1 ignored") % {'size':size_to_string(download_size)}
                            elif (num_ignored > 1):
                                self.statusString = _("1 recommended update available (%(size)s), %(ignored)d ignored") % {'size':size_to_string(download_size), 'ignored':num_ignored}
                        else:
                            if (num_ignored == 0):
                                self.statusString = _("%(recommended)d recommended updates available (%(size)s)") % {'recommended':num_updates, 'size':size_to_string(download_size)}
                            elif (num_ignored == 1):
                                self.statusString = _("%(recommended)d recommended updates available (%(size)s), 1 ignored") % {'recommended':num_updates, 'size':size_to_string(download_size)}
                            elif (num_ignored > 0):
                                self.statusString = _("%(recommended)d recommended updates available (%(size)s), %(ignored)d ignored") % {'recommended':num_updates, 'size':size_to_string(download_size), 'ignored':num_ignored}
                        self.statusIcon.set_from_file(icon_updates)
                        self.statusIcon.set_tooltip(self.statusString)
                        statusbar.push(context_id, self.statusString)
                        log.writelines("++ Found " + str(num_updates) + " recommended software updates\n")
                        log.flush()
                    else:
                        self.statusIcon.set_from_file(icon_up2date)
                        self.statusIcon.set_tooltip(_("Your system is up to date"))
                        statusbar.push(context_id, _("Your system is up to date"))
                        log.writelines("++ System is up to date\n")
                        log.flush()

            log.writelines("++ Refresh finished\n")
            log.flush()
            # Stop the blinking
            #self.statusIcon.set_blinking(False)
            self.wTree.get_widget("notebook_details").set_current_page(0)
            self.wTree.get_widget("window1").window.set_cursor(None)
            self.treeview_update.set_model(model)
            del model
            self.wTree.get_widget("window1").set_sensitive(True)
            wTree.get_widget("vpaned1").set_position(vpaned_position)
            gtk.gdk.threads_leave()

        except Exception, detail:
            print "-- Exception occured in the refresh thread: " + str(detail)
            log.writelines("-- Exception occured in the refresh thread: " + str(detail) + "\n")
            log.flush()
            gtk.gdk.threads_enter()
            self.statusIcon.set_from_file(icon_error)
            self.statusIcon.set_tooltip(_("Could not refresh the list of packages"))
            #self.statusIcon.set_blinking(False)
            self.wTree.get_widget("window1").window.set_cursor(None)
            self.wTree.get_widget("window1").set_sensitive(True)
            statusbar.push(context_id, _("Could not refresh the list of packages"))
            wTree.get_widget("vpaned1").set_position(vpaned_position)
            gtk.gdk.threads_leave()

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
                    except Exception, detail:
                        pass    # don't know why we get these..
        if (foundSomething):
            changes = self.checkDependencies(changes, cache)
        return changes


def force_refresh(widget, treeview, statusIcon, wTree):
    refresh = RefreshThread(treeview, statusIcon, wTree)
    refresh.start()


def clear(widget, treeView, statusbar, context_id):
    model = treeView.get_model()
    iter = model.get_iter_first()
    while (iter is not None):
        model.set_value(iter, INDEX_UPGRADE, "false")
        iter = model.iter_next(iter)
    statusbar.push(context_id, _("No updates selected"))


def select_all(widget, treeView, statusbar, context_id):
    model = treeView.get_model()
    iter = model.get_iter_first()
    while (iter is not None):
        model.set_value(iter, INDEX_UPGRADE, "true")
        iter = model.iter_next(iter)
    iter = model.get_iter_first()
    download_size = 0
    num_selected = 0
    while (iter is not None):
        checked = model.get_value(iter, INDEX_UPGRADE)
        if (checked == "true"):
            size = model.get_value(iter, INDEX_SIZE)
            download_size = download_size + size
            num_selected = num_selected + 1
        iter = model.iter_next(iter)
    if num_selected == 0:
        statusbar.push(context_id, _("No updates selected"))
    elif num_selected == 1:
        statusbar.push(context_id, _("%(selected)d update selected (%(size)s)") % {'selected':num_selected, 'size':size_to_string(download_size)})
    else:
        statusbar.push(context_id, _("%(selected)d updates selected (%(size)s)") % {'selected':num_selected, 'size':size_to_string(download_size)})


def install(widget, treeView, statusIcon, wTree):
    #Launch the install
    install = InstallThread(treeView, statusIcon, wTree)
    install.start()
    #Try to update the local update pack level
    try:
        import apt_pkg
        apt_pkg.init_config()
        apt_pkg.init_system()
        acquire = apt_pkg.Acquire()
        slist = apt_pkg.SourceList()
        slist.read_main_list()
        slist.get_indexes(acquire, True)
        lm_debian_repo_url = None
        for item in acquire.items:
            repo = item.desc_uri
            if repo.endswith('Packages.bz2') and ('/latest/dists/testing/' in repo or
               '/incoming/dists/testing/' in repo):
                lm_debian_repo_url = repo.partition('/dists/')[0]
                break
        if lm_debian_repo_url is not None:
            url = "%s/update-pack-info.txt" % lm_debian_repo_url
            import urllib2
            html = urllib2.urlopen(url)
            for line in html.readlines():
                elements = line.split("=")
                variable = elements[0].strip()
                value = elements[1].strip()
                if variable == "version":
                    os.system("echo %s > /var/log/updatemanager.packlevel" % value)
            html.close()
    except Exception, detail:
        print detail


def change_icon(widget, button, prefs_tree, treeview, statusIcon, wTree):
    global icon_busy
    global icon_up2date
    global icon_updates
    global icon_error
    global icon_unknown
    global icon_apply
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
            prefs_tree.get_widget("image_busy").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(filename, 24, 24))
            icon_busy = filename
        if (button == "up2date"):
            prefs_tree.get_widget("image_up2date").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(filename, 24, 24))
            icon_up2date = filename
        if (button == "updates"):
            prefs_tree.get_widget("image_updates").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(filename, 24, 24))
            icon_updates = filename
        if (button == "error"):
            prefs_tree.get_widget("image_error").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(filename, 24, 24))
            icon_error = filename
        if (button == "unknown"):
            prefs_tree.get_widget("image_unknown").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(filename, 24, 24))
            icon_unknown = filename
        if (button == "apply"):
            prefs_tree.get_widget("image_apply").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(filename, 24, 24))
            icon_apply = filename
    dialog.destroy()


def pref_apply(widget, prefs_tree, treeview, statusIcon, wTree):
    global icon_busy
    global icon_up2date
    global icon_updates
    global icon_error
    global icon_unknown
    global icon_apply

    #Write refresh config
    section = 'refresh'
    cfg.setValue(section, 'timer_minutes', str(int(prefs_tree.get_widget("timer_minutes").get_value())))
    cfg.setValue(section, 'timer_hours', str(int(prefs_tree.get_widget("timer_hours").get_value())))
    cfg.setValue(section, 'timer_days', str(int(prefs_tree.get_widget("timer_days").get_value())))

    #Write update config
    section = 'update'
    cfg.setValue(section, 'delay', str(int(prefs_tree.get_widget("spin_delay").get_value())))
    cfg.setValue(section, 'ping_domain', prefs_tree.get_widget("text_ping").get_value())
    cfg.setValue(section, 'dist_upgrade', prefs_tree.get_widget("checkbutton_dist_upgrade").get_value())

    #Write icons config
    section = 'update'
    cfg.setValue(section, 'busy', icon_busy)
    cfg.setValue(section, 'up2date', icon_up2date)
    cfg.setValue(section, 'updates', icon_updates)
    cfg.setValue(section, 'error', icon_error)
    cfg.setValue(section, 'unknown', icon_unknown)
    cfg.setValue(section, 'apply', icon_apply)

    #Write blacklisted packages
    ignored_list = open(cfgignored, "w")
    treeview_blacklist = prefs_tree.get_widget("treeview_blacklist")
    model = treeview_blacklist.get_model()
    iter = model.get_iter_first()
    while iter is not None:
        pkg = model.get_value(iter, 0)
        iter = model.iter_next(iter)
        ignored_list.writelines(pkg + "\n")
    ignored_list.close()

    prefs_tree.get_widget("window2").hide()
    refresh = RefreshThread(treeview, statusIcon, wTree)
    refresh.start()


def info_cancel(widget, prefs_tree):
    prefs_tree.get_widget("window3").hide()


def history_cancel(widget, tree):
    tree.get_widget("window4").hide()


def history_clear(widget, tree):
    os.system("rm -rf /var/log/updatemanager.history")
    model = gtk.TreeStore(str, str, str, str)
    tree.set_model(model)
    del model


def pref_cancel(widget, prefs_tree):
    prefs_tree.get_widget("window2").hide()


def read_configuration():
    global icon_busy
    global icon_up2date
    global icon_updates
    global icon_error
    global icon_unknown
    global icon_apply

    #Read refresh config
    try:
        section = 'refresh'
        prefs["timer_minutes"] = int(cfg.getValue(section, 'timer_minutes'))
        prefs["timer_hours"] = int(cfg.getValue(section, 'timer_hours'))
        prefs["timer_days"] = int(cfg.getValue(section, 'timer_days'))
    except:
        prefs["timer_minutes"] = 15
        prefs["timer_hours"] = 0
        prefs["timer_days"] = 0

    #Read update config
    try:
        section = 'update'
        prefs["delay"] = int(cfg.getValue(section, 'delay'))
        prefs["ping_domain"] = cfg.getValue(section, 'ping_domain')
        prefs["dist_upgrade"] = (cfg.getValue(section, 'dist_upgrade') == "True")
    except:
        prefs["delay"] = 30
        prefs["ping_domain"] = testdomain
        prefs["dist_upgrade"] = True

    #Read icons config
    try:
        section = 'icons'
        icon_busy = cfg.getValue(section, 'busy')
        icon_up2date = cfg.getValue(section, 'up2date')
        icon_updates = cfg.getValue(section, 'updates')
        icon_error = cfg.getValue(section, 'error')
        icon_unknown = cfg.getValue(section, 'unknown')
        icon_apply = cfg.getValue(section, 'apply')
    except:
        icon_busy = os.path.join(sharedir, "icons/base.svg")
        icon_up2date = os.path.join(sharedir, "icons/base-apply.svg")
        icon_updates = os.path.join(sharedir, "icons/base-info.svg")
        icon_error = os.path.join(sharedir, "icons/base-error2.svg")
        icon_unknown = os.path.join(sharedir, "icons/base.svg")
        icon_apply = os.path.join(sharedir, "icons/base-exec.svg")

    #Read columns config
    section = 'visible_columns'
    try:
        prefs["package_column_visible"] = (cfg.getValue(section, 'package') == "True")
    except:
        prefs["package_column_visible"] = True
    try:
        prefs["old_version_column_visible"] = (cfg.getValue(section, 'old_version') == "True")
    except:
        prefs["old_version_column_visible"] = True
    try:
        prefs["new_version_column_visible"] = (cfg.getValue(section, 'new_version') == "True")
    except:
        prefs["new_version_column_visible"] = True
    try:
        prefs["size_column_visible"] = (cfg.getValue(section, 'size') == "True")
    except:
        prefs["size_column_visible"] = True

    #Read window dimensions
    try:
        section = 'dimensions'
        prefs["dimensions_x"] = int(cfg.getValue(section, 'x'))
        prefs["dimensions_y"] = int(cfg.getValue(section, 'y'))
        prefs["dimensions_pane_position"] = int(cfg.getValue(section, 'pane_position'))
    except:
        prefs["dimensions_x"] = 790
        prefs["dimensions_y"] = 540
        prefs["dimensions_pane_position"] = 230

    #Read package blacklist
    try:
        section = 'packages'
        prefs["blacklisted_packages"] = cfg.getValue(section, 'blacklisted_packages')
    except:
        prefs["blacklisted_packages"] = []

    return prefs


def open_repositories(widget):
    if os.path.exists("/usr/bin/software-properties-gtk"):
        os.system("/usr/bin/software-properties-gtk &")
    elif os.path.exists("/usr/bin/software-properties-kde"):
        os.system("/usr/bin/software-properties-kde &")


def open_preferences(widget, treeview, statusIcon, wTree):
    global icon_busy
    global icon_up2date
    global icon_updates
    global icon_error
    global icon_unknown
    global icon_apply

    gladefile = os.path.join(sharedir, "updatemanager.glade")
    prefs_tree = gtk.glade.XML(gladefile, "window2")
    prefs_tree.get_widget("window2").set_title(_("Preferences") + " - " + _("Update Manager"))

    prefs_tree.get_widget("label36").set_text(_("Auto-Refresh"))
    prefs_tree.get_widget("label81").set_text(_("Refresh the list of updates every:"))
    prefs_tree.get_widget("label82").set_text("<i>" + _("Note: The list only gets refreshed while the update manager window is closed (system tray mode).") + "</i>")
    prefs_tree.get_widget("label82").set_use_markup(True)
    prefs_tree.get_widget("label83").set_text(_("Update Method"))
    prefs_tree.get_widget("label85").set_text(_("Icons"))
    prefs_tree.get_widget("label86").set_markup("<b>" + _("Icon") + "</b>")
    prefs_tree.get_widget("label87").set_markup("<b>" + _("Status") + "</b>")
    prefs_tree.get_widget("label95").set_markup("<b>" + _("New Icon") + "</b>")
    prefs_tree.get_widget("label88").set_text(_("Busy"))
    prefs_tree.get_widget("label89").set_text(_("System up-to-date"))
    prefs_tree.get_widget("label90").set_text(_("Updates available"))
    prefs_tree.get_widget("label99").set_text(_("Error"))
    prefs_tree.get_widget("label2").set_text(_("Unknown state"))
    prefs_tree.get_widget("label3").set_text(_("Applying updates"))
    prefs_tree.get_widget("label6").set_text(_("Startup delay (in seconds):"))
    prefs_tree.get_widget("label7").set_text(_("Internet check (domain name or IP address):"))
    prefs_tree.get_widget("label1").set_text(_("Ignored packages"))

    prefs_tree.get_widget("checkbutton_dist_upgrade").set_label(_("Include updates which require the installation or the removal of other packages"))

    prefs_tree.get_widget("window2").set_icon_from_file(os.path.join(sharedir, "icons/base.svg"))
    prefs_tree.get_widget("window2").show()
    prefs_tree.get_widget("pref_button_cancel").connect("clicked", pref_cancel, prefs_tree)
    prefs_tree.get_widget("pref_button_apply").connect("clicked", pref_apply, prefs_tree, treeview, statusIcon, wTree)

    prefs_tree.get_widget("button_icon_busy").connect("clicked", change_icon, "busy", prefs_tree, treeview, statusIcon, wTree)
    prefs_tree.get_widget("button_icon_up2date").connect("clicked", change_icon, "up2date", prefs_tree, treeview, statusIcon, wTree)
    prefs_tree.get_widget("button_icon_updates").connect("clicked", change_icon, "updates", prefs_tree, treeview, statusIcon, wTree)
    prefs_tree.get_widget("button_icon_error").connect("clicked", change_icon, "error", prefs_tree, treeview, statusIcon, wTree)
    prefs_tree.get_widget("button_icon_unknown").connect("clicked", change_icon, "unknown", prefs_tree, treeview, statusIcon, wTree)
    prefs_tree.get_widget("button_icon_apply").connect("clicked", change_icon, "apply", prefs_tree, treeview, statusIcon, wTree)

    prefs = read_configuration()

    prefs_tree.get_widget("timer_minutes_label").set_text(_("minutes"))
    prefs_tree.get_widget("timer_hours_label").set_text(_("hours"))
    prefs_tree.get_widget("timer_days_label").set_text(_("days"))
    prefs_tree.get_widget("timer_minutes").set_value(prefs["timer_minutes"])
    prefs_tree.get_widget("timer_hours").set_value(prefs["timer_hours"])
    prefs_tree.get_widget("timer_days").set_value(prefs["timer_days"])

    prefs_tree.get_widget("text_ping").set_text(prefs["ping_domain"])

    prefs_tree.get_widget("spin_delay").set_value(prefs["delay"])

    prefs_tree.get_widget("checkbutton_dist_upgrade").set_active(prefs["dist_upgrade"])

    prefs_tree.get_widget("image_busy").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(icon_busy, 24, 24))
    prefs_tree.get_widget("image_up2date").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(icon_up2date, 24, 24))
    prefs_tree.get_widget("image_updates").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(icon_updates, 24, 24))
    prefs_tree.get_widget("image_error").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(icon_error, 24, 24))
    prefs_tree.get_widget("image_unknown").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(icon_unknown, 24, 24))
    prefs_tree.get_widget("image_apply").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(icon_apply, 24, 24))

    # Blacklisted packages
    treeview_blacklist = prefs_tree.get_widget("treeview_blacklist")
    column1 = gtk.TreeViewColumn(_("Ignored packages"), gtk.CellRendererText(), text=0)
    column1.set_sort_column_id(0)
    column1.set_resizable(True)
    treeview_blacklist.append_column(column1)
    treeview_blacklist.set_headers_clickable(True)
    treeview_blacklist.set_reorderable(False)
    treeview_blacklist.show()

    model = gtk.TreeStore(str)
    model.set_sort_column_id(0, gtk.SORT_ASCENDING)
    treeview_blacklist.set_model(model)

    if os.path.exists(cfgignored):
        ignored_list = open(cfgignored, "r")
        for ignored_pkg in ignored_list:
            iter = model.insert_before(None, None)
            model.set_value(iter, 0, ignored_pkg.strip())
        del model
        ignored_list.close()

    prefs_tree.get_widget("toolbutton_add").connect("clicked", add_blacklisted_package, treeview_blacklist)
    prefs_tree.get_widget("toolbutton_remove").connect("clicked", remove_blacklisted_package, treeview_blacklist)


def add_blacklisted_package(widget, treeview_blacklist):
    dialog = gtk.MessageDialog(None, gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_QUESTION, gtk.BUTTONS_OK, None)
    dialog.set_markup("<b>" + _("Please enter a package name:") + "</b>")
    dialog.set_title(_("Ignore a package"))
    dialog.set_icon_from_file(os.path.join(sharedir, 'icons/base.svg'))
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
        model = treeview_blacklist.get_model()
        iter = model.insert_before(None, None)
        model.set_value(iter, 0, pkg)


def remove_blacklisted_package(widget, treeview_blacklist):
    selection = treeview_blacklist.get_selection()
    (model, iter) = selection.get_selected()
    if (iter is not None):
        #pkg = model.get_value(iter, 0)
        model.remove(iter)


def open_history(widget):
    #Set the Glade file
    gladefile = os.path.join(sharedir, "updatemanager.glade")
    wTree = gtk.glade.XML(gladefile, "window4")
    treeview_update = wTree.get_widget("treeview_history")
    wTree.get_widget("window4").set_icon_from_file(os.path.join(sharedir, 'icons/base.svg'))

    wTree.get_widget("window4").set_title(_("History of updates") + " - " + _("Update Manager"))

    # the treeview
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

    treeview_update.append_column(column_date)
    treeview_update.append_column(column_package_name)
    treeview_update.append_column(column_old_version)
    treeview_update.append_column(column_new_version)

    treeview_update.set_headers_clickable(True)
    treeview_update.set_reorderable(False)
    treeview_update.set_search_column(INDEX_HISTORY_PACKAGE_NAME)
    treeview_update.set_enable_search(True)
    treeview_update.show()

    model = gtk.TreeStore(str, str, str, str)    # (date, packageName, oldVersion, newVersion)
    if (os.path.exists("/var/log/updatemanager.history")):
        updates = commands.getoutput("cat /var/log/updatemanager.history")
        updates = string.split(updates, "\n")
        for pkg in updates:
            values = string.split(pkg, "\t")
            if len(values) == 4:
                date = values[0]
                package = values[1]
                oldVersion = values[2]
                newVersion = values[3]

                iter = model.insert_before(None, None)
                model.set_value(iter, INDEX_HISTORY_DATE, date)
                model.row_changed(model.get_path(iter), iter)
                model.set_value(iter, INDEX_HISTORY_PACKAGE_NAME, package)
                model.set_value(iter, INDEX_HISTORY_OLD_VERSION, oldVersion)
                model.set_value(iter, INDEX_HISTORY_NEW_VERSION, newVersion)

    treeview_update.set_model(model)
    del model
    wTree.get_widget("button_close").connect("clicked", history_cancel, wTree)
    wTree.get_widget("button_clear").connect("clicked", history_clear, treeview_update)


def open_pack_info(widget):
    #Set the Glade file
    gladefile = os.path.join(sharedir, "updatemanager.glade")
    wTree = gtk.glade.XML(gladefile, "window_pack_info")
    wTree.get_widget("window_pack_info").set_icon_from_file(os.path.join(sharedir, 'icons/base.svg'))
    wTree.get_widget("window_pack_info").set_title(_("Update Pack Info") + " - " + _("Update Manager"))

    #i18n
    wTree.get_widget("label_system_configuration").set_text(_("Your system configuration:"))
    wTree.get_widget("label_update_pack_available").set_text(_("Current Update Pack available:"))
    wTree.get_widget("label_update_pack_installed").set_text(_("Latest Update Pack used by this system:"))

    # Check APT configuration
    config_str = "<span color='red'><b>" + _("Could not identify your APT sources") + "</b></span>"
    latest_update_pack = _("N/A")
    installed_update_pack = _("N/A")
    lm_debian_repo_url = None

    try:
        if (os.path.exists("/var/log/updatemanager.packlevel")):
            installed_update_pack = commands.getoutput("cat /var/log/updatemanager.packlevel")

        import apt_pkg
        apt_pkg.init_config()
        apt_pkg.init_system()
        acquire = apt_pkg.Acquire()
        slist = apt_pkg.SourceList()
        slist.read_main_list()
        slist.get_indexes(acquire, True)

        # There's 3 valid configurations (for main repo, multimedia and security):
        #
        #      1. Not recommended, fully rolling: Debian Testing, multimedia, security
        #      2. Recommended, Latest update packs: LM_Latest, LM_Latest_Multimedia, LM_Latest_Security
        #      3. For testers, Incoming update packs: LM_Incoming, LM_Incoming_Multimedia, LM_Incoming_Security

        # Which repo do the sources use for the main archive?
        main_points_to_debian = False
        main_points_to_latest = False
        main_points_to_incoming = False
        main_points_to_lm = False

        # Which repo do the sources use for multimedia?
        multimedia_points_to_debian = False
        multimedia_points_to_latest = False
        multimedia_points_to_incoming = False

        # Which repo do the sources use for security?
        security_points_to_debian = False
        security_points_to_latest = False
        security_points_to_incoming = False

        lm_is_here = False    # Is the repo itself present?

        for item in acquire.items:
            repo = item.desc_uri
            if repo.endswith('Packages.bz2'):
                #Check LM
                if '/dists/debian/upstream/' in repo:
                    lm_is_here = True
                #Check main archive
                elif '/latest/dists/testing/' in repo:
                    main_points_to_latest = True
                    main_points_to_lm = True
                    lm_debian_repo_url = "http://" + repurldebian + "/latest"
                elif '/incoming/dists/testing/' in repo:
                    main_points_to_incoming = True
                    main_points_to_lm = True
                    lm_debian_repo_url = "http://" + repurldebian + "/incoming"
                elif 'debian.org/debian/dists' in repo and '//ftp.' in repo:
                    main_points_to_debian = True
                #Check multimedia
                elif '/latest/multimedia/dists/testing/' in repo:
                    multimedia_points_to_latest = True
                elif '/incoming/multimedia/dists/testing/' in repo:
                    multimedia_points_to_incoming = True
                elif 'debian-multimedia.org' in repo:
                    multimedia_points_to_debian = True
                #Check security
                elif '/latest/security/dists/testing/' in repo:
                    security_points_to_latest = True
                elif '/incoming/security/dists/testing/' in repo:
                    security_points_to_incoming = True
                elif 'security.debian.org' in repo:
                    security_points_to_debian = True

        if main_points_to_debian and main_points_to_lm:
            #Conflict between DEBIAN and LM_DEBIAN
            config_str = _("Your system is pointing to " + repdebian + " and " + repurldebian) + "\n" + _("These repositories conflict with each others")
            wTree.get_widget("image_system_config").set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
        elif main_points_to_incoming and main_points_to_latest:
            #Conflict between LM_DEBIAN_INCOMING and LM_DEBIAN_LATEST
            config_str = _("Your system is pointing to " + repurldebian + "/latest and " + repurldebian + "/incoming") + "\n" + _("These repositories conflict with each others")
            wTree.get_widget("image_system_config").set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
        elif not lm_is_here:
            #Missing LM
            config_str = _("Your system is not pointing to the SolydXK repositories") + "\n" + _("Add \"deb http://" + repurl + "/ debian main upstream import \" to your APT sources")
            wTree.get_widget("image_system_config").set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
        elif not (main_points_to_lm or main_points_to_debian):
            #Missing DEBIAN or LM_DEBIAN
            config_str = _("Your system is not pointing to any Debian repository") + "\n" + _("Add \"deb http://" + repurldebian + "/latest testing main contrib non-free\" to your APT sources")
            wTree.get_widget("image_system_config").set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
        else:
            if main_points_to_debian:
                config_str = _("Your system is pointing directly to Debian") + "\n" + _("This is only recommended for experienced users")
                wTree.get_widget("image_system_config").set_from_stock(gtk.STOCK_DIALOG_WARNING, gtk.ICON_SIZE_SMALL_TOOLBAR)
            elif main_points_to_incoming:
                if multimedia_points_to_debian:
                    config_str = _("Your system is pointing directly at debian-multimedia.org") + "\n" + _("Replace \"deb http://debian-multimedia.org testing main non-free\" with \"deb http://" + repurldebian + "/incoming/multimedia testing main non-free\" in your APT sources")
                    wTree.get_widget("image_system_config").set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
                elif security_points_to_debian:
                    config_str = _("Your system is pointing directly at security.debian.org") + "\n" + _("Replace \"deb http://security.debian.org testing/updates main contrib non-free\" with \"deb http://" + repurldebian + "/incoming/security testing/updates main contrib non-free\" in your APT sources")
                    wTree.get_widget("image_system_config").set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
                elif (multimedia_points_to_latest or security_points_to_latest):
                    config_str = _("Some of your repositories point to Latest, others point to Incoming") + "\n" + _("Please check your APT sources.")
                    wTree.get_widget("image_system_config").set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
                else:
                    config_str = _("Your system is pointing to the \"SolydXK Debian Incoming\" repository") + "\n" + _("This is only recommend for experienced users")
                    wTree.get_widget("image_system_config").set_from_stock(gtk.STOCK_DIALOG_WARNING, gtk.ICON_SIZE_SMALL_TOOLBAR)
            elif main_points_to_latest:
                if multimedia_points_to_debian:
                    config_str = _("Your system is pointing directly at debian-multimedia.org") + "\n" + _("Replace \"deb http://debian-multimedia.org testing main non-free\" with \"deb http://" + repurldebian + "/latest/multimedia testing main non-free\" in your APT sources")
                    wTree.get_widget("image_system_config").set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
                elif security_points_to_debian:
                    config_str = _("Your system is pointing directly at security.debian.org") + "\n" + _("Replace \"deb http://security.debian.org testing/updates main contrib non-free\" with \"deb http://" + repurldebian + "/latest/security testing/updates main contrib non-free\" in your APT sources")
                    wTree.get_widget("image_system_config").set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
                elif (multimedia_points_to_incoming or security_points_to_incoming):
                    config_str = _("Some of your repositories point to Latest, others point to Incoming") + "\n" + _("Please check your APT sources.")
                    wTree.get_widget("image_system_config").set_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_SMALL_TOOLBAR)
                else:
                    config_str = _("Your system is pointing to the \"SolydXK Debian Latest\" repository")
                    wTree.get_widget("image_system_config").set_from_stock(gtk.STOCK_DIALOG_INFO, gtk.ICON_SIZE_SMALL_TOOLBAR)
    except Exception, detail:
        print detail

    if lm_debian_repo_url is not None:
        url = "%s/update-pack-info.txt" % lm_debian_repo_url
        import urllib2
        html = urllib2.urlopen(url)
        for line in html.readlines():
            elements = line.split("=")
            variable = elements[0].strip()
            value = elements[1].strip()
            if variable == "version":
                latest_update_pack = value
        html.close()

        import webkit
        browser = webkit.WebView()
        wTree.get_widget("scrolled_pack_info").add(browser)
        browser.connect("button-press-event", lambda w, e: e.button == 3)
        url = "%s/update-pack.html" % lm_debian_repo_url
        browser.open(url)
        browser.show()

    wTree.get_widget("label_system_configuration_value").set_markup("<b>%s</b>" % config_str)
    wTree.get_widget("label_update_pack_available_value").set_markup("<b>%s</b>" % latest_update_pack)
    wTree.get_widget("label_update_pack_installed_value").set_markup("<b>%s</b>" % installed_update_pack)

    wTree.get_widget("button_close").connect("clicked", close_pack_info, wTree)
    wTree.get_widget("window_pack_info").show()


def close_pack_info(widget, tree):
    tree.get_widget("window_pack_info").hide()


def open_information(widget):
    global logFile
    global mode
    global pid

    gladefile = os.path.join(sharedir, "updatemanager.glade")
    prefs_tree = gtk.glade.XML(gladefile, "window3")
    prefs_tree.get_widget("window3").set_title(_("Information") + " - " + _("Update Manager"))
    prefs_tree.get_widget("window3").set_icon_from_file(os.path.join(sharedir, 'icons/base.svg'))
    prefs_tree.get_widget("close_button").connect("clicked", info_cancel, prefs_tree)
    prefs_tree.get_widget("label1").set_text(_("Information"))
    prefs_tree.get_widget("label2").set_text(_("Log file"))
    prefs_tree.get_widget("label3").set_text(_("Permissions:"))
    prefs_tree.get_widget("label4").set_text(_("Process ID:"))
    prefs_tree.get_widget("label5").set_text(_("Log file:"))

    prefs_tree.get_widget("mode_label").set_text(str(mode))
    prefs_tree.get_widget("processid_label").set_text(str(pid))
    prefs_tree.get_widget("log_filename").set_text(str(logFile))
    txtbuffer = gtk.TextBuffer()
    txtbuffer.set_text(commands.getoutput("cat " + logFile))
    prefs_tree.get_widget("log_textview").set_buffer(txtbuffer)


def open_about(widget):
    dlg = gtk.AboutDialog()
    dlg.set_title(_("About") + " - " + _("Update Manager"))
    dlg.set_program_name("updatemanager")
    dlg.set_comments(_("Update Manager"))
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

    dlg.set_authors(authors)
    dlg.set_icon_from_file(os.path.join(sharedir, 'icons/base.svg'))
    dlg.set_logo(gtk.gdk.pixbuf_new_from_file(os.path.join(sharedir, 'icons/base.svg')))

    def close(w, res):
        if res == gtk.RESPONSE_CANCEL:
            w.hide()
    dlg.connect("response", close)
    dlg.show()


def quit_cb(widget, window, vpaned, data=None):
    global log
    if data:
        data.set_visible(False)
    try:
        log.writelines("++ Exiting - requested by user\n")
        log.flush()
        log.close()
        save_window_size(window, vpaned)
    except:
        pass    # cause log might already been closed
    # Whatever works best heh :)
    pid = os.getpid()
    os.system("kill -9 %s &" % pid)
    #gtk.main_quit()
    #sys.exit(0)


def info_cb(widget, data=None):
    global log
    global logFile
    if data:
        data.set_visible(False)
    try:
        log.flush()
        os.system("gedit " + logFile)
    except:
        pass


def popup_menu_cb(widget, button, time, data=None):
    if button == 3:
        if data:
            data.show_all()
            data.popup(None, None, None, 3, time)
    pass


def close_window(window, event, vpaned):
    global app_hidden
    window.hide()
    save_window_size(window, vpaned)
    app_hidden = True
    return True


def hide_window(widget, window):
    global app_hidden
    window.hide()
    app_hidden = True


def activate_icon_cb(widget, data, wTree):
    global app_hidden
    if app_hidden:
            # check credentials
        if os.getuid() != 0:
            try:
                log.writelines("++ Launching updatemanager in root mode...\n")
                log.flush()
                log.close()
            except:
                pass    # cause we might have closed it already
            os.system("gksudo --message \"" + _("Please enter your password to start the update manager") + "\" " + curdir + "/updatemanager.py show &")
        else:
            wTree.get_widget("window1").show()
            app_hidden = False
    else:
        wTree.get_widget("window1").hide()
        app_hidden = True
        save_window_size(wTree.get_widget("window1"), wTree.get_widget("vpaned1"))


def save_window_size(window, vpaned):
    section = 'dimensions'
    cfg.setValue(section, 'x', window.get_size()[0])
    cfg.setValue(section, 'y', window.get_size()[1])
    cfg.setValue(section, 'pane_position', vpaned.get_position())


def display_selected_package(selection, wTree):
    wTree.get_widget("textview_description").get_buffer().set_text("")
    wTree.get_widget("textview_changes").get_buffer().set_text("")
    (model, iter) = selection.get_selected()
    if (iter is not None):
        #selected_package = model.get_value(iter, INDEX_PACKAGE_NAME)
        description_txt = model.get_value(iter, INDEX_DESCRIPTION)
        wTree.get_widget("notebook_details").set_current_page(0)
        wTree.get_widget("textview_description").get_buffer().set_text(description_txt)


def switch_page(notebook, page, page_num, Wtree, treeView):
    selection = treeView.get_selection()
    (model, iter) = selection.get_selected()
    if (iter is not None):
        selected_package = model.get_value(iter, INDEX_PACKAGE_NAME)
        description_txt = model.get_value(iter, INDEX_DESCRIPTION)
        if (page_num == 0):
            # Description tab
            wTree.get_widget("textview_description").get_buffer().set_text(description_txt)
        if (page_num == 1):
            # Changelog tab
            version = model.get_value(iter, INDEX_NEW_VERSION)
            retriever = ChangelogRetriever(selected_package, version, wTree)
            retriever.start()


def celldatafunction_checkbox(column, cell, model, iter):
    cell.set_property("activatable", True)
    checked = model.get_value(iter, INDEX_UPGRADE)
    if (checked == "true"):
        cell.set_property("active", True)
    else:
        cell.set_property("active", False)


def toggled(renderer, path, treeview, statusbar, context_id):
    model = treeview.get_model()
    iter = model.get_iter(path)
    if (iter is not None):
        checked = model.get_value(iter, INDEX_UPGRADE)
        if (checked == "true"):
            model.set_value(iter, INDEX_UPGRADE, "false")
        else:
            model.set_value(iter, INDEX_UPGRADE, "true")

    iter = model.get_iter_first()
    download_size = 0
    num_selected = 0
    while (iter is not None):
        checked = model.get_value(iter, INDEX_UPGRADE)
        if (checked == "true"):
            size = model.get_value(iter, INDEX_SIZE)
            download_size = download_size + size
            num_selected = num_selected + 1
        iter = model.iter_next(iter)
    if num_selected == 0:
        statusbar.push(context_id, _("No updates selected"))
    elif num_selected == 1:
        statusbar.push(context_id, _("%(selected)d update selected (%(size)s)") % {'selected':num_selected, 'size':size_to_string(download_size)})
    else:
        statusbar.push(context_id, _("%(selected)d updates selected (%(size)s)") % {'selected':num_selected, 'size':size_to_string(download_size)})


def size_to_string(size):
    strSize = str(size) + _("B")
    if (size >= 1024):
        strSize = str(size / 1024) + _("KB")
    if (size >= (1024 * 1024)):
        strSize = str(size / (1024 * 1024)) + _("MB")
    if (size >= (1024 * 1024 * 1024)):
        strSize = str(size / (1024 * 1024 * 1024)) + _("GB")
    return strSize


def setVisibleColumn(checkmenuitem, column, configName):
    section = 'visible_columns'
    cfg.setValue(section, configName, checkmenuitem.get_active())
    column.set_visible(checkmenuitem.get_active())


def menuPopup(widget, event, treeview_update, statusIcon, wTree):
    if event.button == 3:
        (model, iter) = widget.get_selection().get_selected()
        if (iter is not None):
            selected_package = model.get_value(iter, INDEX_PACKAGE_NAME)
            menu = gtk.Menu()
            menuItem = gtk.MenuItem(_("Ignore updates for this package"))
            menuItem.connect("activate", add_to_ignore_list, treeview_update, selected_package, statusIcon, wTree)
            menu.append(menuItem)
            menu.show_all()
            menu.popup(None, None, None, 3, 0)


def add_to_ignore_list(widget, treeview_update, pkg, statusIcon, wTree):
    os.system("echo \"%s\" >> %s" % (pkg, cfgignored))
    force_refresh(widget, treeview_update, statusIcon, wTree)

global app_hiden
global log
global logFile
global mode
global pid
global statusbar
global context_id

app_hidden = True

gtk.gdk.threads_init()

#parentPid = "0"
#if len(sys.argv) > 2:
#    parentPid = sys.argv[2]
#    if (parentPid != "0"):
#        os.system("kill -9 " + parentPid)

#

# prepare the log
pid = os.getpid()
logdir = "/tmp/updatemanager/"

if not os.path.exists(logdir):
    os.system("mkdir -p " + logdir)
    os.system("chmod a+rwx " + logdir)

if os.getuid() == 0:
    os.system("chmod a+rwx " + logdir)
    mode = "root"
else:
    mode = "user"

#logFile = logdir + "/" + parentPid + "_" + str(pid) + ".log"
#log = open(logFile, "w")
log = tempfile.NamedTemporaryFile(prefix=logdir, delete=False)
logFile = log.name
try:
    os.system("chmod a+rw %s" % log.name)
except Exception, detail:
    print detail

log.writelines("++ Launching updatemanager in " + mode + " mode\n")
log.flush()

try:
    global icon_busy
    global icon_up2date
    global icon_updates
    global icon_error
    global icon_unknown
    global icon_apply

    prefs = read_configuration()

    statusIcon = gtk.StatusIcon()
    statusIcon.set_from_file(icon_busy)
    statusIcon.set_tooltip(_("Checking for updates"))
    statusIcon.set_visible(True)

    #Set the Glade file
    gladefile = os.path.join(sharedir, "updatemanager.glade")
    wTree = gtk.glade.XML(gladefile, "window1")
    wTree.get_widget("window1").set_title(_("Update Manager"))
    wTree.get_widget("window1").set_default_size(prefs['dimensions_x'], prefs['dimensions_y'])
    wTree.get_widget("vpaned1").set_position(prefs['dimensions_pane_position'])

    statusbar = wTree.get_widget("statusbar")
    context_id = statusbar.get_context_id("updatemanager")

    vbox = wTree.get_widget("vbox_main")
    treeview_update = wTree.get_widget("treeview_update")
    wTree.get_widget("window1").set_icon_from_file(os.path.join(sharedir, 'icons/base.svg'))

    # Get the window socket (needed for synaptic later on)

    if os.getuid() != 0:
        # If we're not in root mode do that (don't know why it's needed.. very weird)
        socket = gtk.Socket()
        vbox.pack_start(socket, True, True, 0)
        socket.show()
        window_id = repr(socket.get_id())

    # the treeview
    cr = gtk.CellRendererToggle()
    cr.connect("toggled", toggled, treeview_update, statusbar, context_id)
    column_upgrade = gtk.TreeViewColumn(_("Upgrade"), cr)
    column_upgrade.set_cell_data_func(cr, celldatafunction_checkbox)
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

    treeview_update.append_column(column_upgrade)
    treeview_update.append_column(column_package)
    treeview_update.append_column(column_old_version)
    treeview_update.append_column(column_new_version)
    treeview_update.append_column(column_size)
    treeview_update.set_headers_clickable(True)
    treeview_update.set_reorderable(False)
    treeview_update.show()

    treeview_update.connect("button-release-event", menuPopup, treeview_update, statusIcon, wTree)

    model = gtk.TreeStore(str, str, str, str, int, str, str, str)    # upgrade, pkgname, oldversion, newversion, size, strsize, description, sourcePackage)
    model.set_sort_column_id(INDEX_PACKAGE_NAME, gtk.SORT_ASCENDING)
    treeview_update.set_model(model)
    del model

    selection = treeview_update.get_selection()
    selection.connect("changed", display_selected_package, wTree)
    wTree.get_widget("notebook_details").connect("switch-page", switch_page, wTree, treeview_update)
    wTree.get_widget("window1").connect("delete_event", close_window, wTree.get_widget("vpaned1"))
    wTree.get_widget("tool_apply").connect("clicked", install, treeview_update, statusIcon, wTree)
    wTree.get_widget("tool_clear").connect("clicked", clear, treeview_update, statusbar, context_id)
    wTree.get_widget("tool_select_all").connect("clicked", select_all, treeview_update, statusbar, context_id)
    wTree.get_widget("tool_refresh").connect("clicked", force_refresh, treeview_update, statusIcon, wTree)
    wTree.get_widget("tool_pack_info").connect("clicked", open_pack_info)

    menu = gtk.Menu()
    menuItem3 = gtk.ImageMenuItem(gtk.STOCK_REFRESH)
    menuItem3.connect('activate', force_refresh, treeview_update, statusIcon, wTree)
    menu.append(menuItem3)
    menuItem2 = gtk.ImageMenuItem(gtk.STOCK_DIALOG_INFO)
    menuItem2.connect('activate', open_information)
    menu.append(menuItem2)
    if os.getuid() == 0:
        menuItem4 = gtk.ImageMenuItem(gtk.STOCK_PREFERENCES)
        menuItem4.connect('activate', open_preferences, treeview_update, statusIcon, wTree)
        menu.append(menuItem4)
    menuItem = gtk.ImageMenuItem(gtk.STOCK_QUIT)
    menuItem.connect('activate', quit_cb, wTree.get_widget("window1"), wTree.get_widget("vpaned1"), statusIcon)
    menu.append(menuItem)

    statusIcon.connect('activate', activate_icon_cb, None, wTree)
    statusIcon.connect('popup-menu', popup_menu_cb, menu)

    # Set text for all visible widgets (because of i18n)
    wTree.get_widget("tool_pack_info").set_label(_("Update Pack Info"))
    wTree.get_widget("tool_apply").set_label(_("Install Updates"))
    wTree.get_widget("tool_refresh").set_label(_("Refresh"))
    wTree.get_widget("tool_select_all").set_label(_("Select All"))
    wTree.get_widget("tool_clear").set_label(_("Clear"))
    wTree.get_widget("label9").set_text(_("Description"))
    wTree.get_widget("label8").set_text(_("Changelog"))

    wTree.get_widget("label_error_detail").set_text("")
    wTree.get_widget("hbox_error").hide()
    wTree.get_widget("scrolledwindow1").hide()
    wTree.get_widget("viewport1").hide()
    wTree.get_widget("label_error_detail").hide()
    wTree.get_widget("image_error").hide()
    wTree.get_widget("vpaned1").set_position(prefs['dimensions_pane_position'])

    fileMenu = gtk.MenuItem(_("_File"))
    fileSubmenu = gtk.Menu()
    fileMenu.set_submenu(fileSubmenu)
    closeMenuItem = gtk.ImageMenuItem(gtk.STOCK_CLOSE)
    closeMenuItem.get_child().set_text(_("Close"))
    closeMenuItem.connect("activate", hide_window, wTree.get_widget("window1"))
    fileSubmenu.append(closeMenuItem)

    editMenu = gtk.MenuItem(_("_Edit"))
    editSubmenu = gtk.Menu()
    editMenu.set_submenu(editSubmenu)
    prefsMenuItem = gtk.ImageMenuItem(gtk.STOCK_PREFERENCES)
    prefsMenuItem.get_child().set_text(_("Preferences"))
    prefsMenuItem.connect("activate", open_preferences, treeview_update, statusIcon, wTree)
    editSubmenu.append(prefsMenuItem)
    if os.path.exists("/usr/bin/software-properties-gtk") or os.path.exists("/usr/bin/software-properties-kde"):
        sourcesMenuItem = gtk.ImageMenuItem(gtk.STOCK_PREFERENCES)
        sourcesMenuItem.set_image(gtk.image_new_from_file(os.path.join(sharedir, 'icons/software-properties.png')))
        sourcesMenuItem.get_child().set_text(_("Software sources"))
        sourcesMenuItem.connect("activate", open_repositories)
        editSubmenu.append(sourcesMenuItem)

    viewMenu = gtk.MenuItem(_("_View"))
    viewSubmenu = gtk.Menu()
    viewMenu.set_submenu(viewSubmenu)
    historyMenuItem = gtk.ImageMenuItem(gtk.STOCK_INDEX)
    historyMenuItem.get_child().set_text(_("History of updates"))
    historyMenuItem.connect("activate", open_history)
    infoMenuItem = gtk.ImageMenuItem(gtk.STOCK_DIALOG_INFO)
    infoMenuItem.get_child().set_text(_("Information"))
    infoMenuItem.connect("activate", open_information)
    visibleColumnsMenuItem = gtk.MenuItem(gtk.STOCK_DIALOG_INFO)
    visibleColumnsMenuItem.get_child().set_text(_("Visible columns"))
    visibleColumnsMenu = gtk.Menu()
    visibleColumnsMenuItem.set_submenu(visibleColumnsMenu)

    packageColumnMenuItem = gtk.CheckMenuItem(_("Package"))
    packageColumnMenuItem.set_active(prefs["package_column_visible"])
    column_package.set_visible(prefs["package_column_visible"])
    packageColumnMenuItem.connect("toggled", setVisibleColumn, column_package, "package")
    visibleColumnsMenu.append(packageColumnMenuItem)

    oldVersionColumnMenuItem = gtk.CheckMenuItem(_("Old version"))
    oldVersionColumnMenuItem.set_active(prefs["old_version_column_visible"])
    column_old_version.set_visible(prefs["old_version_column_visible"])
    oldVersionColumnMenuItem.connect("toggled", setVisibleColumn, column_old_version, "old_version")
    visibleColumnsMenu.append(oldVersionColumnMenuItem)

    newVersionColumnMenuItem = gtk.CheckMenuItem(_("New version"))
    newVersionColumnMenuItem.set_active(prefs["new_version_column_visible"])
    column_new_version.set_visible(prefs["new_version_column_visible"])
    newVersionColumnMenuItem.connect("toggled", setVisibleColumn, column_new_version, "new_version")
    visibleColumnsMenu.append(newVersionColumnMenuItem)

    sizeColumnMenuItem = gtk.CheckMenuItem(_("Size"))
    sizeColumnMenuItem.set_active(prefs["size_column_visible"])
    column_size.set_visible(prefs["size_column_visible"])
    sizeColumnMenuItem.connect("toggled", setVisibleColumn, column_size, "size")
    visibleColumnsMenu.append(sizeColumnMenuItem)

    viewSubmenu.append(visibleColumnsMenuItem)
    viewSubmenu.append(historyMenuItem)
    viewSubmenu.append(infoMenuItem)

    helpMenu = gtk.MenuItem(_("_Help"))
    helpSubmenu = gtk.Menu()
    helpMenu.set_submenu(helpSubmenu)
    aboutMenuItem = gtk.ImageMenuItem(gtk.STOCK_ABOUT)
    aboutMenuItem.get_child().set_text(_("About"))
    aboutMenuItem.connect("activate", open_about)
    helpSubmenu.append(aboutMenuItem)

    #browser.connect("activate", browser_callback)
    #browser.show()
    wTree.get_widget("menubar1").append(fileMenu)
    wTree.get_widget("menubar1").append(editMenu)
    wTree.get_widget("menubar1").append(viewMenu)
    wTree.get_widget("menubar1").append(helpMenu)

    if len(sys.argv) > 1:
        showWindow = sys.argv[1]
        if (showWindow == "show"):
            wTree.get_widget("window1").show_all()
            wTree.get_widget("label_error_detail").set_text("")
            wTree.get_widget("hbox_error").hide()
            wTree.get_widget("scrolledwindow1").hide()
            wTree.get_widget("viewport1").hide()
            wTree.get_widget("label_error_detail").hide()
            wTree.get_widget("image_error").hide()
            wTree.get_widget("vpaned1").set_position(prefs['dimensions_pane_position'])
            app_hidden = False

    if os.getuid() != 0:
        #test the network connection to delay updatemanager in case we're not yet connected
        log.writelines("++ Testing initial connection\n")
        log.flush()
        try:
            from urllib import urlopen
            url = urlopen('http://' + testdomain)
            url.read()
            url.close()
            log.writelines("++ Connection to the Internet successful (tried to read http://www.google.com)\n")
            log.flush()
        except Exception, detail:
            print detail
            if os.system("ping " + prefs["ping_domain"] + " -c1 -q"):
                log.writelines("-- No connection found (tried to read http://www.google.com and to ping " + prefs["ping_domain"] + ") - sleeping for " + str(prefs["delay"]) + " seconds\n")
                log.flush()
                time.sleep(prefs["delay"])
            else:
                log.writelines("++ Connection found - checking for updates\n")
                log.flush()

    wTree.get_widget("notebook_details").set_current_page(0)

    refresh = RefreshThread(treeview_update, statusIcon, wTree)
    refresh.start()

    auto_refresh = AutomaticRefreshThread(treeview_update, statusIcon, wTree)
    auto_refresh.start()
    gtk.main()

except Exception, detail:
    print detail
    log.writelines("-- Exception occured in main thread: " + str(detail) + "\n")
    log.flush()
    log.close()
