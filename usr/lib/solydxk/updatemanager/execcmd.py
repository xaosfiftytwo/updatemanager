#!/usr/bin/env python

try:
    import sys
    import subprocess
    import re
except Exception, detail:
    print detail
    exit(1)

# Class to execute a command and return the output in an array
class ExecCmd(object):

    def __init__(self, rtobject=None, outputFile=None):
        self.rtobject = rtobject
        if self.rtobject:
            self.typeString = self.getTypeString(self.rtobject)
        self.outputFile = outputFile

    def run(self, cmd, realTime=True, defaultMessage=''):
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        lstOut = []
        while True:
            # Strip the line, also from null spaces (strip() only strips white spaces)
            line = p.stdout.readline().strip().strip("\0")
            if line == '' and p.poll() is not None:
                break

            if line != '':
                lstOut.append(line)
                if realTime:
                    sys.stdout.flush()
                    if self.rtobject:
                        self.rtobjectWrite(line)
                    if self.outputFile is not None:
                        with open(self.outputFile, "a") as fle:
                            fle.write("%s\n" % line)

        return lstOut

    # Return messge to given object
    def rtobjectWrite(self, message):
        if self.rtobject is not None and self.typeString != '':
            if self.typeString == 'gtk.Label':
                self.rtobject.set_text(message)
            elif self.typeString == 'gtk.Statusbar':
                self.pushMessage(self.rtobject, message)
            else:
                # For obvious reasons: do not log this...
                print 'Return object type not implemented: %s' % self.typeString

    # Return the type string of a object
    def getTypeString(self, object):
        tpString = ''
        tp = str(type(object))
        matchObj = re.search("'(.*)'", tp)
        if matchObj:
            tpString = matchObj.group(1)
        return tpString

    def pushMessage(self, statusbar, message, contextString='message'):
        context = statusbar.get_context_id(contextString)
        statusbar.push(context, message)
