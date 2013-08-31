# -*- coding: utf-8 -*-
# EditXT
# Copyright 2007-2012 Daniel Miller <millerdev@gmail.com>
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
from editxt.command.base import command, PanelController
from editxt.command.parser import Choice, Regex, RegexPattern, CommandParser, Options
from editxt.util import KVOProxy, KVOLink

log = logging.getLogger(__name__)


ACTION_FIND_SELECTED_TEXT = 101
ACTION_FIND_SELECTED_TEXT_REVERSE = 102

SELECTION_REQUIRED_ACTIONS = set([
    ACTION_FIND_SELECTED_TEXT,
    ACTION_FIND_SELECTED_TEXT_REVERSE,
])

FORWARD = "FORWARD"
BACKWARD = "BACKWARD"
WRAPTOKEN = "WRAPTOKEN"


@command(arg_parser=CommandParser(
    Regex('pattern', replace=True, default=(RegexPattern(u""), u"")),
    Choice(('find-next next', 'find_next'),
        ('find-previous previous', 'find_previous'),
        ('replace-one one', 'replace_one'),
        ('replace-all all', 'replace_all'),
        ('replace-in-selection in-selection selection', 'replace_all_in_selection'),
        name='action'),
    Choice('regex literal-text word', name='search_type'),
    Choice(('wrap', True), ('no-wrap', False), name='wrap_around'),
), lookup_with_arg_parser=True)
def find(textview, sender, args):
    assert args is not None, sender
    action = args.__dict__.pop('action')
    search_type = args.__dict__.pop('search_type')
    find, replace = args.__dict__.pop('pattern')
    opts = FindOptions(**args.__dict__)
    opts.find_text = find
    opts.replace_text = replace or ""
    opts.ignore_case = bool(find.flags & re.IGNORECASE)
    opts.match_entire_word = (search_type == 'word')
    opts.regular_expression = (search_type == "regex")
    finder = Finder(lambda:textview, opts)
    getattr(finder, action)(sender)


def toggle_boolean(depname):
    def make_property(func):
        name = func.__name__
        def fget(self):
            try:
                return self.__dict__[name]
            except KeyError:
                raise AttributeError(name)
        def fset(self, value):
            self.__dict__[name] = value
            if value:
                self.__dict__[depname] = False
        return property(fget, fset)
    return make_property

def mutable_array_property(name):
    def fget(self):
        try:
            return self.__dict__[name]
        except KeyError:
            raise AttributeError(name)
    def fset(self, value):
        try:
            array = self.__dict__[name]
        except KeyError:
            self.__dict__[name] = NSMutableArray.arrayWithArray_(value)
        else:
            # FIX problem here: KVO notifications not sent
            array.setArray_(value)
    return property(fget, fset)


class FindOptions(Options):

    DEFAULTS = dict(
        #find_text = u"",
        replace_text = u"",
        recent_finds = (),
        recent_replaces = (),
        regular_expression = False,
        match_entire_word = False,
        ignore_case = True,
        wrap_around = True,
    )

    dependent_key_paths = {
        "match_entire_word": ["regular_expression"],
        "regular_expression": ["match_entire_word"],
    }

    recent_finds = mutable_array_property("recent_finds")
    recent_replaces = mutable_array_property("recent_replaces")

    @toggle_boolean("match_entire_word")
    def regular_expression(): pass

    @toggle_boolean("regular_expression")
    def match_entire_word(): pass


class Finder(object):

    def __init__(self, find_target, options):
        self.find_target = find_target
        self.opts = options
        self.recently_found_range = None

    def find_next(self, sender):
        self.find(FORWARD)

    def find_previous(self, sender):
        self.find(BACKWARD)

    def replace_one(self, sender):
        target = self.find_target()
        if target is not None:
            options = self.opts
            rtext = options.replace_text
            if options.regular_expression and self.recently_found_range is not None:
                rtext = self.recently_found_range.expand(rtext)
            range = target.selectedRange()
            if target.shouldChangeTextInRange_replacementString_(range, rtext):
                target.textStorage().replaceCharactersInRange_withString_(range, rtext)
                target.didChangeText()
                target.setNeedsDisplay_(True)
                return
        NSBeep()

    def replace_all(self, sender):
        self._replace_all()

    def replace_all_in_selection(self, sender):
        self._replace_all(in_selection=True)

    def mark_occurrences(self, ftext, regex=False, color=None):
        """Mark occurrences of ftext in target

        This method always clears all existing text marks, and marks
        nothing if the given `ftext` is an empty string.

        :ftext: A string of text to find/mark.
        :regex: Boolean value indicating if ftext is a regular expression.
        :color: Color used to mark ranges. Yellow (#FEFF6B) by default.
        :returns: Number of marked occurrences.
        """
        target = self.find_target()
        last_mark = getattr(target, '_Finder__last_mark', (None, 0))
        if last_mark[0] == ftext:
            return last_mark[1]
        if color is None:
            from editxt import app # HACK global resource
            color = app.config["highlight_selected_text.color"]
        ts = target.textStorage()
        ts.beginEditing()
        try:
            full_range = NSMakeRange(0, ts.length())
            ts.removeAttribute_range_(NSBackgroundColorAttributeName, full_range)

            # HACK for some reason marks are not always completely removed:
            # - Select text with many occurrences in syntax-highlighted
            #   document. There should be at least one occurrence of text
            #   above the selection, outside of its syntax highlight region.
            # - Type a character, effectively causing a syntax update as well
            #   as a selection change.
            # - Notice that some of the previously marked words are not cleared,
            #   but they will be cleared on scroll/redraw.
            target.setNeedsDisplay_(True)

            if not ftext:
                target._Finder__last_mark = (ftext, 0)
                return 0
            text = target.string()
            options = self.opts
            original_ftext = ftext
            if regex and options.regular_expression:
                finditer = self.regexfinditer
            elif options.match_entire_word:
                ftext = u"\\b" + re.escape(ftext) + u"\\b"
                finditer = self.regexfinditer
            else:
                finditer = self.simplefinditer
            count = 0
            attr = NSBackgroundColorAttributeName
            mark_range = ts.addAttribute_value_range_
            for found in finditer(text, ftext, full_range, FORWARD, False):
                mark_range(attr, color, found.range)
                count += 1
            target._Finder__last_mark = (original_ftext, count)
            return count
        finally:
            ts.endEditing()

    def find(self, direction):
        target = self.find_target()
        ftext = self.opts.find_text
        if target is not None and ftext:
            text = target.string()
            selection = target.selectedRange()
            range = self._find(text, ftext, selection, direction)
            if range is not None:
                target.setSelectedRange_(range)
                target.scrollRangeToVisible_(range)
                return
        NSBeep()

    def _find(self, text, ftext, selection, direction):
        """Return the range of the found text or None if not found"""
        options = self.opts
        if options.regular_expression:
            finditer = self.regexfinditer
        elif options.match_entire_word:
            ftext = u"\\b" + re.escape(ftext) + u"\\b"
            finditer = self.regexfinditer
        else:
            finditer = self.simplefinditer
        range = NSMakeRange(selection.location, 0)
        for i, found in enumerate(finditer(text, ftext, range, direction, True)):
            if found is WRAPTOKEN:
                # TODO show wrap overlay
                continue
            range = found.range
            if i == 0 and range == selection:
                # this is the first match and we found the selected text
                continue # find next
            self.recently_found_range = found
            return range
        return None

    def _replace_all(self, in_selection=False):
        target = self.find_target()
        ftext = self.opts.find_text
        range = None if target is None else target.selectedRange()
        if target is None or not ftext or (in_selection and range.length == 0):
            NSBeep()
            return
        text = target.string()
        options = self.opts
        if not in_selection:
            if options.wrap_around:
                range = NSMakeRange(0, 0)
            else:
                # Replace all to the end of the file. Logically there should be
                # another option: replace all (backward) to the beginning of the
                # file, but there's no way to do that with the interface.
                range = NSMakeRange(range.location, len(text) - range.location)
        if options.regular_expression:
            finditer = self.regexfinditer
        elif options.match_entire_word:
            ftext = u"\\b" + re.escape(ftext) + u"\\b"
            finditer = self.regexfinditer
        else:
            finditer = self.simplefinditer
        rtext = options.replace_text
        range0 = None
        rtexts = []
        for found in finditer(text, ftext, range, FORWARD, False):
            range = found.range
            if range0 is None:
                range0 = range
            else:
                rtexts.append(text[sum(range1):range.location])
            range1 = range
            rtexts.append(found.expand(rtext))
        if range0 is not None:
            start = range0.location
            range = NSMakeRange(start, sum(range1) - start)
            value = "".join(rtexts)
            if target.shouldChangeTextInRange_replacementString_(range, value):
                target.textStorage().replaceCharactersInRange_withString_(range, value)
                target.didChangeText()
                target.setNeedsDisplay_(True)
                return
        NSBeep()

    def simplefinditer(self, text, ftext, range,
                       direction=FORWARD, yield_on_wrap=True):
        """Yields FoundRanges of text that match ftext

        if yield_on_wrap evaluates to True and wrap_around search option is set
        then WRAPTOKEN is yielded when the search wraps around the beginning/end
        of the file
        """
        opts = 0
        options = self.opts
        if options.ignore_case:
            opts |= NSCaseInsensitiveSearch
        forwardSearch = (direction == FORWARD)
        if forwardSearch:
            startindex = index = range.location
        else:
            startindex = index = range.location + range.length
            opts |= NSBackwardsSearch
        if range.length == 0:
            if options.wrap_around:
                range = NSMakeRange(0, text.length())
            elif forwardSearch:
                range = NSMakeRange(startindex, text.length() - startindex)
            else:
                range = NSMakeRange(0, startindex)
        endindex = range.location + range.length
        wrapped = False
        while True:
            if forwardSearch:
                if wrapped:
                    if index >= startindex:
                        break # searched to or beyond where we started
                    else:
                        frange = NSRange(index, startindex - index)
                else:
                    frange = NSRange(index, endindex - index)
            else:
                if wrapped:
                    if index <= startindex:
                        break # searched to or beyond where we started
                    else:
                        frange = NSRange(startindex, index - startindex)
                else:
                    frange = NSRange(range.location, index - range.location)
            found = text.rangeOfString_options_range_(ftext, opts, frange)
            if found and found.length > 0 and found.location < endindex:
                yield FoundRange(found)
                index = found.location + (found.length if forwardSearch else 0)
            elif options.wrap_around and not wrapped:
                if yield_on_wrap:
                    yield WRAPTOKEN
                index = range.location if forwardSearch else endindex
                wrapped = True
            else:
                break

    def regexfinditer(self, text, ftext, range, direction, yield_on_wrap):
        """Yields FoundRanges of text matched by ftext (a regular expression)

        if yield_on_wrap evaluates to True and wrapAround search option is set
        then WRAPTOKEN is yielded when the search wraps around the beginning/end
        of the file.
        """
        flags = re.UNICODE | re.MULTILINE
        options = self.opts
        if options.ignore_case:
            flags |= re.IGNORECASE
        try:
            regex = re.compile(ftext, flags)
        except re.error, err:
            NSBeep()
            log.error("cannot compile regex %r : %s", ftext, err)
        else:
            backward = (direction == BACKWARD)
            wrapped = False
            endindex = range.location + range.length
            while True:
                if range.length > 0:
                    itr = regex.finditer(text, range.location, endindex)
                elif (wrapped and backward) or (not wrapped and not backward):
                    itr = regex.finditer(text, range.location)
                else:
                    itr = regex.finditer(text, 0, range.location)
                if backward:
                    itr = reversed(list(itr))
                for match in itr:
                    s = match.start()
                    e = match.end()
                    #log.debug("searching for %r found %r at (%s, %s)", ftext, match.group(), s, e)
                    yield FoundRange(NSMakeRange(s, e - s), match)
                if options.wrap_around and not wrapped and range.length == 0:
                    if yield_on_wrap:
                        yield WRAPTOKEN
                    wrapped = True
                else:
                    break


class FindController(PanelController):
    """Window controller for find panel"""

    NIB_NAME = u"FindPanel"
    OPTIONS_KEY = const.FIND_PANEL_OPTIONS_KEY
    OPTIONS_FACTORY = FindOptions

    find_text = objc.IBOutlet()
    replace_text = objc.IBOutlet()
    status_label = objc.IBOutlet()

    def initWithWindowNibName_(self, name):
        self = super(FindController, self).initWithWindowNibName_(name)
        self.finder = Finder(self.find_target, self.opts)
        self.action_registry = {
            NSFindPanelActionShowFindPanel: self.show_find_panel,
            NSFindPanelActionNext: self.find_next,
            NSFindPanelActionPrevious: self.find_previous,
            NSFindPanelActionReplace: self.replace_one,
            NSFindPanelActionReplaceAll: self.replace_all,
            NSFindPanelActionReplaceAndFind: self.replace_and_find_next,
            NSFindPanelActionReplaceAllInSelection: self.replace_all_in_selection,
            NSFindPanelActionSetFindString: self.set_find_text_with_selection,
            ACTION_FIND_SELECTED_TEXT: self.find_selected_text,
            ACTION_FIND_SELECTED_TEXT_REVERSE: self.find_selected_text_reverse,
        }
        #self.opts = opts = KVOProxy(FindOptions())
        return self

    def windowDidLoad(self):
        self.window().setLevel_(NSFloatingWindowLevel)
        target = self.find_target()
        if target is not None:
            font = target.doc_view.document.default_text_attributes()[NSFontAttributeName]
            for field in (self.find_text, self.replace_text):
                field.setFont_(font)

    # Menu actions ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def validate_action(self, tag):
        if tag in self.action_registry:
            target = self.find_target()
            if target is not None:
                if tag in SELECTION_REQUIRED_ACTIONS:
                    return target.selectedRange().length > 0
                return True
        return False

    def perform_action(self, sender):
        default = lambda s: log.info("unknown action: %s", s.tag())
        self.action_registry.get(sender.tag(), default)(sender)

    def show_find_panel(self, sender):
        #self.load_options() # restore state
        self.showWindow_(self)
        #self.find_text.setStringValue_(self.opts.find_text) # HACK should not have to do this
        self.find_text.selectText_(sender)

    def find_next(self, sender):
        return self.finder.find_next(sender)

    def find_previous(self, sender):
        return self.finder.find_previous(sender)

    def replace_one(self, sender):
        return self.finder.replace_one(sender)

    def replace_all(self, sender):
        return self.finder.replace_all(sender)

    def replace_all_in_selection(self, sender):
        return self.finder.replace_all_in_selection(sender)

    def find_selected_text(self, sender):
        self.set_find_text_with_selection(sender)
        if self.save_options():
            self.finder.find_next(sender)

    def find_selected_text_reverse(self, sender):
        self.set_find_text_with_selection(sender)
        if self.save_options():
            self.finder.find_previous(sender)

    def replace_and_find_next(self, sender):
        self.finder.replace_one(sender)
        self.finder.find_next(sender)

    def set_find_text_with_selection(self, sender):
        target = self.find_target()
        if target is not None:
            range = target.selectedRange()
            if range.length > 0:
                text = target.string().substringWithRange_(range)
                if self.opts.regular_expression:
                    text = re.escape(text)
                self.opts.find_text = text

    # Panel actions ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def panelFindNext_(self, sender):
        if self.save_options():
            self.window().orderOut_(sender)
            self.finder.find_next(sender)

    def panelFindPrevious_(self, sender):
        if self.save_options():
            self.window().orderOut_(sender)
            self.finder.find_previous(sender)

    def panelReplace_(self, sender):
        if self.save_options():
            self.window().orderOut_(sender)
            self.finder.replace_one(sender)

    def panelReplaceAll_(self, sender):
        if self.save_options():
            self.window().orderOut_(sender)
            self.finder.replace_all(sender)

    def panelReplaceAllInSelection_(self, sender):
        if self.save_options():
            self.window().orderOut_(sender)
            self.finder.replace_all_in_selection(sender)

    def panelCountFindText_(self, sender):
        if self.validate_expression():
            self.count_occurrences(
                self.opts.find_text, self.opts.regular_expression)

    def panelCountReplaceText_(self, sender):
        if self.validate_expression():
            self.count_occurrences(self.opts.replace_text, False)

    def panelMarkAll_(self, sender):
        if self.save_options():
            raise NotImplementedError()

    def recentFindSelected_(self, sender):
        # TODO make this support undo so the change can be easily reverted
        self.opts.find_text = sender.selectedItem().title()

    def recentReplaceSelected_(self, sender):
        # TODO make this support undo so the change can be easily reverted
        self.opts.replace_text = sender.selectedItem().title()

    def regexHelp_(self, sender):
        # TODO possibly open a sheet with a short description of how regular
        # expressions are used here, including notes about the default flags
        # that are set (MULTILINE | UNICODE) and the syntax that should be used.
        url = NSURL.URLWithString_(const.REGEX_HELP_URL)
        NSWorkspace.sharedWorkspace().openURL_(url)

    # Utility methods ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def find_target(self):
        from editxt import app
        try:
            editor = app.iter_editors().next()
        except StopIteration:
            pass
        else:
            docview = editor.current_view
            if docview is not None:
                return docview.text_view
        return None

    def count_occurrences(self, ftext, regex):
        target = self.find_target()
        if target is not None and ftext:
            count = self.finder.mark_occurrences(ftext, regex)
            if count:
                self.flash_status_text(u"%i occurrences" % count)
            else:
                self.flash_status_text(u"Not found")
        else:
            NSBeep()

    def flash_status_text(self, text):
        self.stop_flashing_status()
        self.status_flasher = StatusFlasher.alloc().init(self.status_label, text)

    def stop_flashing_status(self):
        flasher = getattr(self, "status_flasher", None)
        if flasher is not None:
            flasher.stop()

    # Window delegate implementation ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def windowWillClose_(self, window):
        self.stop_flashing_status()

    # Find Options implementation ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def validate_expression(self):
        if self.opts.regular_expression and self.find_text is not None:
            ftext = self.find_text.stringValue()
            flags = re.UNICODE | re.MULTILINE
            if self.opts.ignore_case:
                flags |= re.IGNORECASE
            try:
                regex = re.compile(ftext, flags)
            except re.error, err:
                NSBeep()
                # Note: if the find dialog type is NSPanel (instead of NSWindow)
                # the focus will switch back to the main document window rather
                # than to the find dialog, which is not what we want. Therefore
                # we set the Custom Class of the find dialog to NSWindow.
                NSBeginAlertSheet(
                    u"Cannot Compile Regular Expression",
                    u"OK", None, None,
                    self.window(), None, None, None, 0,
                    u"Error: %s" % (err,),
                );
                return False
        return True

    def load_options(self):
        pboard = NSPasteboard.pasteboardWithName_(NSFindPboard)
        if pboard.availableTypeFromArray_([NSStringPboardType]):
            self.opts.find_text = pboard.stringForType_(NSStringPboardType)
        else:
            self.opts.find_text = u""
        super(FindController, self).load_options()

    def save_options(self):
        if not self.validate_expression():
            return False
        def rebuild(opts, listname, newitem):
            if len(newitem) < 1000:
                newitems = [newitem]
                for item in getattr(opts, listname):
                    if item != newitem:
                        newitems.append(item)
                setattr(opts, listname, newitems[:10])
        opts = self.opts
        if opts.find_text:
            pboard = NSPasteboard.pasteboardWithName_(NSFindPboard)
            pboard.declareTypes_owner_([NSStringPboardType], None)
            pboard.setString_forType_(opts.find_text, NSStringPboardType)
            rebuild(opts, "recent_finds", opts.find_text)
        if opts.replace_text:
            rebuild(opts, "recent_replaces", opts.replace_text)
        super(FindController, self).save_options()
        return True


class StatusFlasher(NSObject):

    timing = (0.2, 0.2, 0.2, 5)

    @objc.namedSelector("init:text:")
    def init(self, label, text):
        def runner():
            label.setHidden_(True)
            label.setStringValue_(text)
            for t in self.timing:
                 yield t
                 label.setHidden_(not label.isHidden())
            self.stop()
        self = super(StatusFlasher, self).init()
        self.label = label
        self.runner = runner()
        self.doEvent()
        return self

    def doEvent(self):
        if self.runner is not None:
            try:
                t = self.runner.next()
            except StopIteration:
                return
            self.performSelector_withObject_afterDelay_("doEvent", self, t)

    def stop(self):
        if self.runner is not None:
            self.label.setStringValue_(u"")
            self.label.setHidden_(False)
        self.runner = None


class FoundRange(object):

    def __init__(self, range, rematch=None):
        self.range = range
        self.rematch = rematch

    def expand(self, text):
        if self.rematch is not None:
            try:
                text = self.rematch.expand(text)
            except Exception:
                log.error("error expanding replace expression", exc_info=True)
        return text