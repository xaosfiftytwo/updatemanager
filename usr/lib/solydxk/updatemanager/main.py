#! /usr/bin/env python3 -OO

# Make sure the right Gtk version is loaded
import gi
gi.require_version('Gtk', '3.0')

import sys
sys.path.insert(1, '/usr/lib/solydxk/updatemanager')
import os
import gettext
import argparse
from gi.repository import Gtk
from os.path import join, abspath, dirname, exists
from umglobal import UmGlobal
from dialogs import WarningDialog, ErrorDialog

# i18n: http://docs.python.org/2/library/gettext.html
gettext.install("updatemanager", "/usr/share/locale")
_ = gettext.gettext

umglobal = UmGlobal(False)
scriptDir = abspath(dirname(__file__))
filesDir = join(scriptDir, "files")


# Clear update history
def clearUpHistory():
    histFile = join(filesDir, "updatemanager.hist")
    resetLine = None
    if exists(histFile):
        with open(histFile, 'r') as f:
            for line in reversed(f.readlines()):
                if "upd=" in line:
                    resetLine = "upd=2000.01.01\n"
                    break
        if resetLine is not None:
            print(("> Clear update history file"))
            with open(histFile, 'w') as f:
                f.write(resetLine)


def isRunningLive():
    liveDirs = ['/live', '/lib/live/mount', '/rofs']
    for ld in liveDirs:
        if os.path.exists(ld):
            return True
    return False


def uncaught_excepthook(*args):
    sys.__excepthook__(*args)
    if __debug__:
        from pprint import pprint
        from types import BuiltinFunctionType, ClassType, ModuleType, TypeType
        tb = sys.last_traceback
        while tb.tb_next: tb = tb.tb_next
        print(('\nDumping locals() ...'))
        pprint({k:v for k,v in tb.tb_frame.f_locals.items()
                    if not k.startswith('_') and
                       not isinstance(v, (BuiltinFunctionType,
                                          ClassType, ModuleType, TypeType))})
        if sys.stdin.isatty() and (sys.stdout.isatty() or sys.stderr.isatty()):
            try:
                import ipdb as pdb  # try to import the IPython debugger
            except ImportError:
                import pdb as pdb
            print(('\nStarting interactive debug prompt ...'))
            pdb.pm()
    else:
        import traceback
        details = '\n'.join(traceback.format_exception(*args)).replace('<', '').replace('>', '')
        title = _('Unexpected error')
        msg = _('Updatemanager has failed with the following unexpected error. Please submit a bug report!')
        ErrorDialog(title, "<b>%s</b>" % msg, "<tt>%s</tt>" % details, None, True, 'update-manager')

    sys.exit(1)

sys.excepthook = uncaught_excepthook


# Get the launcher if not root
launcher = ""
if os.geteuid() > 0:
    msg = _('Please enter your password')
    launcher = "gksudo --message \"<b>%s</b>\"" % msg
    if os.path.exists('/usr/bin/kdesudo'):
        launcher = "kdesudo -n -i 'update-manager' -d --comment \"<b>%s</b>\"" % msg

# Handle arguments
parser = argparse.ArgumentParser(description='SolydXK Update Manager')
parser.add_argument('-c','--conf', action="store_true", help='Re-create configuration file')
parser.add_argument('-p','--pref', action="store_true", help='Show the preference window')
parser.add_argument('-q','--quick', action="store_true", help='Quick upgrade')
parser.add_argument('-t','--tray', action="store_true", help='Load the tray icon only')
parser.add_argument('-f','--force', action="store_true", help='Force start in a live environment')
parser.add_argument('-u','--clear-upd', action="store_true", help='Clear Update Pack history')
parser.add_argument('-r','--reload', action="store_true", help='')

args = parser.parse_args()

arguments = []
if args.conf:
    conf = join(filesDir, "updatemanager.conf")
    if exists(conf):
        cmd = "rm -f {}".format(conf)
        if launcher != "":
            cmd = "{0} '{1}'".format(launcher, cmd)
        print(cmd)
        os.system(cmd)

if args.reload:
    arguments.append("-r")
if args.clear_upd:
    clearUpHistory()
if args.quick:
    arguments.append("-q")

# Finish arguments string
arguments.append("&")

msg = _("Update Manager cannot be started in a live environment\n"
        "You can use the --force argument to start UM in a live environment")

if args.pref:
    if isRunningLive() and not args.force:
        WarningDialog(umglobal.title, msg, None, None, True, 'update-manager')
    else:
        if umglobal.isProcessRunning("updatemanagerpref.py"):
            print(("updatemanagerpref.py already running - exiting"))
        else:
            cmd = "python3 {0}/updatemanagerpref.py {1}".format(scriptDir, " ".join(arguments))
            if launcher != "":
                cmd = "{0} '{1}'".format(launcher, cmd)
            print(cmd)
            os.system(cmd)
else:
    if not isRunningLive() and not args.force:
        if umglobal.isProcessRunning("updatemanagertray.py"):
            print(("updatemanagertray.py already running - exiting"))
        else:
            cmd = "python3 {0}/updatemanagertray.py {1}".format(scriptDir, " ".join(arguments))
            print(cmd)
            os.system(cmd)
    if not args.tray:
        if isRunningLive() and not args.force:
            WarningDialog(umglobal.title, msg, None, None, True, 'update-manager')
        else:
            if umglobal.isProcessRunning("updatemanager.py"):
                print(("updatemanager.py already running - exiting"))
            else:
                cmd = "python3 {0}/updatemanager.py {1}".format(scriptDir, " ".join(arguments))
                if launcher != "":
                    cmd = "{0} '{1}'".format(launcher, cmd)
                print(cmd)
                os.system(cmd)
