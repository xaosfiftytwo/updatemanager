#!/usr/bin/env python

try:
    import pygtk
    pygtk.require("2.0")
    import gtk
    import gtk.glade
    import threading
    import urllib2
    import commands
    import gettext
except Exception, detail:
    print detail
    pass

# i18n
gettext.install("updatemanager", "/usr/share/locale")

class ChangelogRetriever(threading.Thread):
    def __init__(self, source_package, version, builder, prefs):
        threading.Thread.__init__(self)
        self.source_package = source_package
        self.version = version
        self.builder = builder
        self.prefs = prefs
        print ">>> ChangelogRetriever"

    def run(self):
        gtk.gdk.threads_enter()
        self.builder.get_object("textview_changes").get_buffer().set_text(_("Downloading changelog..."))
        gtk.gdk.threads_leave()

        changelog = ""
        if ("solyd" in self.version) or ("solyd" in self.source_package):
            #Get the solyd change file for amd64
            try:
                url = urllib2.urlopen("http://" + self.prefs["repurl"] + "/" + self.prefs["repurldevsubdir"] + "/" + self.source_package + "_" + self.version + "_amd64.changes", None, 30)
                source = url.read()
                url.close()
                changes = source.split("\n")
                for change in changes:
                    change = change.strip()
                    if change.startswith("*"):
                        changelog = changelog + change + "\n"
            except:
                try:
                    url = urllib2.urlopen("http://" + self.prefs["repurl"] + "/" + self.prefs["repurldevsubdir"] + "/" + self.source_package + "_" + self.version + "_i386.changes", None, 30)
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
        self.builder.get_object("textview_changes").get_buffer().set_text(changelog)
        gtk.gdk.threads_leave()
