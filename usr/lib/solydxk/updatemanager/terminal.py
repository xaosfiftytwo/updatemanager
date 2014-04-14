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
        'waiting-for-answer': (GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING, GObject.TYPE_INT, GObject.TYPE_INT,))
        }

    def __init__(self, line, col, row, maxWaitForAnswer):
        GObject.GObject.__init__(self)
        threading.Thread.__init__(self)
        self.event = threading.Event()
        self.timerCnt = 0
        self.line = line
        self.col = col
        self.row = row
        self.maxWaitForAnswer = maxWaitForAnswer

    def run(self):
        #self.event.clear()
        while not self.event.is_set():
            if self.timerCnt >= self.maxWaitForAnswer:
                self.timerCnt = 0
                #print((">> emit waiting-for-answer: line=%s, col=%d, row=%d" % (self.line, self.col, self.row)))
                self.emit('waiting-for-answer', self.line, self.col, self.row)
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
        'line-added': (GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING, GObject.TYPE_INT, GObject.TYPE_INT,)),
        'waiting-for-answer': (GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING, GObject.TYPE_INT, GObject.TYPE_INT,))
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
        self.column = 0
        self.row = 0
        self.lastLine = ""
        self.last_row_logged = 0
        self.maxWaitForAnswer = maxWaitForAnswer
        self.timerCnt = 0
        self.checkRow = 0
        self.threads = {}
        self.skipTimerCommands = []
        self.skipTimerOnString = [
                                 ["man-db"],
                                 ["run-parts"]
                                 ]
        self.skipTimer = False

        # Terminal settings
        self.backgroundColor = "#FFFFFF"
        self.set_scroll_on_output(True)
        self.set_scroll_on_keystroke(True)
        self.set_visible(True)
        self.set_encoding("UTF-8")
        self.set_scrollback_lines(-1)
        self.set_font_from_string("monospace 10")
        if not userInputAllowed:
            self.set_can_focus(False)

        # Set colors (SolydXK terminal colors - use KColorChooser for hexadecimal values)
        hexColors = ['#4A4A4A',
                    '#BD1919',
                    '#118011',
                    '#CE6800',
                    '#1919BC',
                    '#8D138D',
                    '#139494',
                    '#A7A7A7']

        palette = []
        for hexColor in hexColors:
            palette.append(Gdk.color_parse(hexColor))
        # foreground, background, pallete
        self.set_colors(Gdk.color_parse('#000000'), Gdk.color_parse(self.backgroundColor), palette)

        self.connect('eof', self.on_command_done)
        self.connect('child-exited', self.on_command_done)
        self.connect('cursor-moved', self.on_contents_changed)
        self.connect('event', self.on_event)
        self.connect_after("popup-menu", self.on_popup_menu)
        self.connect("button-release-event", self.on_popup_menu)

    def on_waiting_for_answer(self, obj, line, col, row):
        self.emit('waiting-for-answer', line, col, row)

    def on_contents_changed(self, terminal):
        # Gets the last line printed to the terminal
        # On wheezy the python3, and vte libraries are rather buggy,
        # and get_cursor_position or  get_text_range will fail
        # even after recompiling those libraries from testing for wheezy
        try:
            self.backgroundColor = "#FFFFFF"
            self.set_color_background(Gdk.color_parse(self.backgroundColor))

            self.column, self.row = self.get_cursor_position()
            #print((self.column, self.row, self.last_row_logged))
            if self.last_row_logged != self.row:
                off = self.row - self.last_row_logged
                if off < 0:
                    off = 0

                #print(("++ 1 - self.column:%d, self.row:%d, self.last_row_logged:%d, off:%d" % (self.column, self.row, self.last_row_logged, off)))

                # Next line throws error: NotImplementedError: <gi.CallbackInfo object (SelectionFunc) at 0x0x7f5a0f319440>
                #text = self.get_text_range(row - off, 0, row - 1, -1, Vte.SelectionFunc(column, row), self.capture_text)

                text = self.get_text_range(self.row - off, 0, self.row, -1, None, None)
                #print(("++ 2 - text = %s" % str(text)))
                if text is not None:
                    lst = text[0].split('\n')
                    #print(("++ 3 - lst = %s" % str(lst)))
                    for line in lst:
                        line = line.rstrip()
                        #print(("++ 4 - line = %s" % str(line)))
                        chkLine = line.strip()
                        if chkLine != "":
                            self.lastLine = line
                            #print(("++ 5 - lastLine = %s" % str(self.lastLine)))

                        # Start the timer to check if user input is needed
                        if self.doStartTimer():
                            #print(("++ 6 - start timer - %d, %s" % (self.column, chkLine)))
                            name = 'timer'
                            if self.threads:
                                if self.threads[name].is_alive():
                                    self.threads[name].stop()
                                    del self.threads[name]
                            t = TimerClass(self.lastLine, self.column, self.row, self.maxWaitForAnswer)
                            t.connect('waiting-for-answer', self.on_waiting_for_answer)
                            self.threads[name] = t
                            t.daemon = True
                            t.start()

                        if chkLine != "":
                            self.emit('line-added', line, self.column, self.row)

                    self.last_row_logged = self.row
        except Exception as detail:
            # This is a best-effort attempt, fail graciously
            print(("Error (VirtualTerminal.on_contents_changed): %s" % str(detail)))

    def doStartTimer(self):
        #print(">> doStartTimer 1")
        if not self.skipTimer and self.maxWaitForAnswer > 0:
            #print(">> doStartTimer 2")
            if self.column > 0:
                #print(">> doStartTimer 3")
                for strings in self.skipTimerOnString:
                    cnt = 0
                    for string in strings:
                        #print((">> doStartTimer 4 > string = %s, lastLine = %s" % (string, self.lastLine)))
                        if string in self.lastLine:
                            cnt += 1
                    if cnt == len(strings):
                        #print(">> doStartTimer 5: do NOT start timer")
                        return False

                # Check if we're looking at a debconf menu
                debconf = self.checkDebConf()
                if debconf == "debconfchoice":
                    print(">> Debconf choice menu: wait for user to make a selection")
                    self.backgroundColor = "#1919BC"
                    self.set_color_background(Gdk.color_parse(self.backgroundColor))
                    return False
                elif debconf == "debconfok":
                    if self.column == 0:
                        print(">> Debconf menu OK: tab to OK button")
                        cmd = "\t"
                        self.feed_child(cmd, len(cmd))
                    else:
                        print(">> Debconf menu OK")
                    self.backgroundColor = "#1919BC"
                    self.set_color_background(Gdk.color_parse(self.backgroundColor))
                    return True
                elif debconf == "debconfyesno":
                    print(">> Debconf menu: more than one choice")
                    self.backgroundColor = "#1919BC"
                    self.set_color_background(Gdk.color_parse(self.backgroundColor))
                    return True
                else:
                    #print(">> doStartTimer 6: start timer")
                    self.backgroundColor = "#FFFFFF"
                    return True
        #print(">> doStartTimer 7: do NOT start timer")
        return False

    # Check if we're waiting for a user choice: never feed an automated answer
    def checkDebConf(self):
        termText = self.get_text(None, None)[0]
        matchObj = re.search("│ +(\[ +\])", termText)
        if matchObj:
            if matchObj.group(1) != "":
                return "debconfchoice"
        matchObj = re.search("│ +(<[a-zA-Z]*> +<[a-zA-Z]*>)", termText)
        if matchObj:
            if matchObj.group(1) != "":
                return "debconfyesno"
        matchObj = re.search("│ +(<[a-zA-Z]*>)", termText)
        if matchObj:
            if matchObj.group(1) != "":
                return "debconfok"
        return ""

    def executeCommand(self, command_string, id_name, maxWaitForAnswer=None):
        self.skipTimer = False
        if maxWaitForAnswer is not None:
            self.maxWaitForAnswer = maxWaitForAnswer
        if self.maxWaitForAnswer is not None:
            for cmd in self.skipTimerCommands:
                if cmd in command_string:
                    self.skipTimer = True

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
        name = 'timer'
        if self.threads:
            if self.threads[name].is_alive():
                self.threads[name].stop()
                del self.threads[name]
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
