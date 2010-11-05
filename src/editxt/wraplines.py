# -*- coding: utf-8 -*-
# EditXT
# Copyright (c) 2007-2010 Daniel Miller <millerdev@gmail.com>
#
# This file is part of EditXT, a programmer's text editor for Mac OS X,
# which can be found at http://editxt.org/.
#
# EditXT is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# EditXT is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EditXT.  If not, see <http://www.gnu.org/licenses/>.
import logging
import objc
import os
import re
import time

from AppKit import *
from Foundation import *

import editxt.constants as const
from editxt.commandbase import SheetController
from editxt.textcommand import iterlines

log = logging.getLogger("editxt.wraplines")

WHITESPACE = re.compile(r"[ \t]*")

class WrapLinesController(SheetController):
    """Window controller for sort lines text command"""

    NIB_NAME = u"WrapLines"
    OPTIONS_DEFAULTS = dict(
        wrap_column=80,
        indent=True,
    )

    def wrap_(self, sender):
        wrap_selected_lines(self.textview, self.opts)
        self.save_options()
        self.cancel_(sender)

def wrap_selected_lines(textview, options):
    text = textview.string()
    sel = text.lineRangeForRange_(textview.selectedRange())
    eol = textview.doc_view.document.eol
    lines = iterlines(text, sel)
    output = eol.join(wraplines(lines, options, textview))
    if textview.shouldChangeTextInRange_replacementString_(sel, output):
        textview.textStorage().replaceCharactersInRange_withString_(sel, output)
        textview.didChangeText()
        textview.setSelectedRange_((sel[0], len(output)))

def wraplines(lines, options, textview):
    lines = iter(lines)
    width = options.wrap_column
    if options.indent:
        token = re.escape(textview.doc_view.document.comment_token)
        if token:
            regexp = re.compile(r"^[ \t]*(?:%s *)?" % token)
        else:
            regexp = WHITESPACE
    else:
        regexp = WHITESPACE
    indent = u""
    leading = None
    while True:
        while True:
            frag = lines.next().rstrip()
            if frag:
                break
            yield u""
        if leading is None:
            leading = regexp.match(frag).group()
        frag = regexp.sub(u"", frag, 1)
        if leading:
            firstlen = width - len(leading)
            if firstlen < 1:
                firstlen = 1
            line, frag = get_line(frag, lines, firstlen, regexp)
            yield leading + line
            if options.indent:
                width = firstlen
                indent = leading
        while frag is not None:
            line, frag = get_line(frag, lines, width, regexp)
            yield indent + line if line else line
        if line:
            yield u""

def get_line(frag, lines, width, regexp, ws=u" \t"):
    while True:
        while len(frag) < width:
            try:
                nextline = lines.next()
            except StopIteration:
                return frag, None
            nextline = regexp.sub(u"", nextline, 1)
            if not nextline:
                return frag, None
            frag = frag + u" " + nextline if frag else nextline
        if len(frag) == width:
            return frag, u""
        for i in xrange(width, 0, -1):
            if frag[i] in ws:
                break
        else:
            fraglen = len(frag)
            i = width + 1
            while i < fraglen and frag[i] not in ws:
                i += 1
        line, frag = frag[:i].rstrip(), frag[i:].lstrip()
        if len(line) + len(WHITESPACE.split(frag, 1)[0]) < width:
            frag = line + u" " + frag
            continue
        return line, frag