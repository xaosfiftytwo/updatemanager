#! /usr/bin/env python3
#-*- coding: utf-8 -*-

#      Reference documentation: https://developer.gnome.org/vte/0.28/VteTerminal.html

# Imports
import os
from gi.repository import Vte, Gdk, GObject, Gtk, GLib
import threading
import re

# Need to initiate threads for Gtk
GObject.threads_init()


class TimerClass(GObject.GObject, threading.Thread):

    __gsignals__ = {
        'waiting-for-answer': (GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING,))
        }

    def __init__(self, line, maxWaitForAnswer):
        GObject.GObject.__init__(self)
        threading.Thread.__init__(self)
        self.event = threading.Event()
        self.timerCnt = 0
        self.line = line
        self.maxWaitForAnswer = maxWaitForAnswer

    def run(self):
        #self.event.clear()
        while not self.event.is_set():
            if self.timerCnt >= self.maxWaitForAnswer:
                self.timerCnt = 0
                self.emit('waiting-for-answer', self.line)
                self.event.set()
            self.timerCnt += 1
            self.event.wait(1)

    def stop(self):
        #print("stop timer")
        self.timerCnt = 0
        self.event.set()


class VirtualTerminal(Vte.Terminal):

    __gsignals__ = {
        'command-done': (GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_INT, GObject.TYPE_STRING,)),
        'line-added': (GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING,)),
        'waiting-for-answer': (GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING,))
        }

    def __init__(self, userInputAllowed=True, maxWaitForAnswer=0):
        # Set up terminal
        Vte.Terminal.__init__(self)

        #Popup Menu
        self.menu = Gtk.Menu()
        menu_item = Gtk.ImageMenuItem.new_from_stock("gtk-copy", None)
        menu_item.connect_after("activate", lambda w: self.copy_clipboard())
        self.menu.add(menu_item)
        self.menu.show_all()

        self.pid = None
        self.nid = None
        self.uid = os.geteuid()
        self.maxWaitForAnswer = maxWaitForAnswer
        self.timerCnt = 0
        self.threads = {}
        self.threadName = "timer"
        self.lastLine = ""
        self.skipTimer = False

        # Strings to skip starting the timer
        # ==================================
        # pos1 = position of search string:
        #        None = anywhere in the string
        #        Negative number = position from the end of the string
        # pos2 = string list to search for
        #        if a numerical position is given, the list can only contain 1 string
        self.skipOnString = [
                            [None, ["man-db"]],
                            [None, ["run-parts"]],
                            [-1, ["%"]],
                            [-3, ["..."]]
                            ]

        # Terminal settings
        self.set_scroll_on_output(True)
        self.set_scroll_on_keystroke(True)
        self.set_visible(True)
        self.set_encoding("UTF-8")
        self.set_scrollback_lines(-1)
        self.set_font_from_string("monospace 10")
        if not userInputAllowed:
            self.set_can_focus(False)

        self.connect('eof', self.on_command_done)
        self.connect('child-exited', self.on_command_done)
        self.connect('cursor-moved', self.on_contents_changed)
        self.connect('event', self.on_event)
        self.connect_after("popup-menu", self.on_popup_menu)
        self.connect("button-release-event", self.on_popup_menu)

    def setTerminalColors(self, foreground, background, palletList=[]):
        # Set colors (SolydXK terminal colors - use KColorChooser for hexadecimal values)
        # palletList = ['#4A4A4A', '#BD1919', '#118011', '#CE6800', '#1919BC', '#8D138D', '#139494', '#A7A7A7']
        palette = []
        for hexColor in palletList:
            palette.append(Gdk.color_parse(hexColor))
        # foreground, background, pallete
        self.set_colors(Gdk.color_parse(foreground), Gdk.color_parse(background), palette)

    def on_waiting_for_answer(self, obj, line):
        self.emit('waiting-for-answer', line)

    def on_contents_changed(self, terminal):
        if self.startTimer():
            # Start the timer
            #print(("> start wait for timer (#threads=%d)" % threading.active_count()))
            if self.threads:
                if self.threads[self.threadName].is_alive():
                    self.threads[self.threadName].stop()
                    del self.threads[self.threadName]
            t = TimerClass(self.lastLine, self.maxWaitForAnswer)
            t.connect('waiting-for-answer', self.on_waiting_for_answer)
            self.threads[self.threadName] = t
            t.daemon = True
            t.start()
        else:
            if self.threads:
                if self.threads[self.threadName].is_alive():
                    #print("> stop wait for timer")
                    self.threads[self.threadName].stop()
                    del self.threads[self.threadName]

    def startTimer(self):
        # Define variables
        isDebConf = False
        choiceCnt = 0

        try:
            # Get current visible text
            termText = self.get_text(None, None)[0].split('\n')

            # Loop through all the lines in the terminal text in reverse
            lastLineCnt = 0
            for line in reversed(termText):
                line = line.strip()

                # Only count non-empty lines
                if line != "":
                    lastLineCnt += 1

                # Skip if set by user
                if self.skipTimer:
                    #print("> skipTimer")
                    return False

                # Skip if maxWaitForAnswer is not set
                if self.maxWaitForAnswer == 0:
                    #print("> maxWaitForAnswer == 0: skip timer")
                    return False

                # Check the last line in the terminal
                if lastLineCnt == 1:
                    # Skip if line hasn't changed (this shouldn't be possible)
                    if line == self.lastLine:
                        #print("> line unchanged: skip timer")
                        return False
                    # Save the last line
                    self.lastLine = line
                    print((self.lastLine))
                    self.emit('line-added', self.lastLine)

                    # Check on progression output
                    # Difference in locale shows % downloaded in a different position
                    matchObj = re.search("\d{1,2}%", line)
                    if matchObj:
                        if matchObj.group(0) != "":
                            print("> progress indication found")
                            return False

                    # Skip on pre-defined strings
                    for strings in self.skipOnString:
                        cnt = 0
                        pos = strings[0]
                        for string in strings[1]:
                            if pos is None:
                                if string in self.lastLine:
                                    cnt += 1
                                    #print(("> %s found in %s (%d)" % (string, self.lastLine, cnt)))
                            else:
                                # There can only be one search string on a given position in the same line
                                if pos < 0:
                                    findString = self.lastLine[pos:(len(self.lastLine)+pos)+len(string)]
                                    if findString == string:
                                        print(("> str on pos %d = %s: skip timer" % (pos, findString)))
                                        return False
                                else:
                                    findString = self.lastLine[pos:pos + len(string)]
                                    if findString == string:
                                        print(("> str on pos %d = %s: skip timer" % (pos, findString)))
                                        return False
                        if cnt == len(strings[1]):
                            print("> strings found: skip timer")
                            return False

                # Skip on debconf menus that need user input
                if not isDebConf:
                    if '└' in line and '─────' in line and '┘' in line:
                        isDebConf = True
                else:
                    # User input
                    if "_____" in line:
                        print("> user input: skip timer")
                        return False
                    # User choice
                    if "[" in line and "]" in line:
                        choiceCnt += 1
                        if choiceCnt > 1:
                            print("> user choice: skip timer")
                            return False
                    # Multiple choice buttons
                    matchObj = re.search("<[a-zA-Z ]+> +<[a-zA-Z ]+>", line)
                    if matchObj:
                        if matchObj.group(0) != "":
                            print("> more than one button: skip timer")
                            return False

            # If you've come this far, you can start the timer
            return True

        except Exception as detail:
            # This is a best-effort attempt, fail graciously
            print(("Warning (VirtualTerminal.on_contents_changed): %s" % str(detail)))
            return False

    def executeCommand(self, command_string, id_name, skipTimer=False):
        self.skipTimer = skipTimer
        self.lastLine = ""

        '''executeCommand runs the command_string in the terminal. This
        function will only return when on_command_done has been triggered.'''
        if self.pid is not None:
            raise ValueError("Terminal already running a command")

        # cwd
        working_directory = ''

        env = os.environ.copy()
        env['TERM'] = "xterm"
        envv = ['%s=%s' % kv for kv in list(env.items())]

        if isinstance(command_string, (tuple, list)):
            argv = command_string
        else:
            argv = ['/bin/bash', '-c', 'clear;echo;echo;' + command_string]

        self.nid = id_name
        print(("Terminal execute command: %s" % command_string))
        self.pid = self.fork_command_full(Vte.PtyFlags.DEFAULT,
                                           working_directory,
                                           argv,
                                           envv,
                                           GLib.SpawnFlags.DO_NOT_REAP_CHILD,
                                           None,
                                           None)[1]

    def on_command_done(self, terminal):
        if self.threads:
            if self.threads[self.threadName].is_alive():
                self.threads[self.threadName].stop()
                del self.threads[self.threadName]
        self.emit('command-done', self.pid, self.nid)
        '''When called this function sets the pid to None, allowing
        the executeCommand function to exit'''
        self.pid = None

    def on_popup_menu(self, terminal, event=None):
        # Display contextual menu on right-click
        if event and self.get_has_selection():
            if event.type == Gdk.EventType.BUTTON_RELEASE and event.button == 3:
                return self.menu.popup(None, None, None, None, 3, 0)

    def on_event(self, terminal, event):
        if (event.type == Gdk.EventType.ENTER_NOTIFY):
            self.grab_focus()
