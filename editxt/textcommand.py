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
import sys
import traceback
from collections import defaultdict
from itertools import count

from AppKit import *
from Foundation import *

import editxt.constants as const
from editxt.command.parser import ArgumentError
from editxt.commands import load_commands, CommandError
from editxt.history import History
from editxt.util import WeakProperty

log = logging.getLogger(__name__)


class CommandBar(object):

    editor = WeakProperty()
    text_commander = WeakProperty()

    def __init__(self, editor, text_commander):
        self.editor = editor
        self.text_commander = text_commander
        self.history_view = None

    def activate(self):
        # abstract to a PyObjC-specific subclass when implementing other frontend
        view = self.editor.current_view
        if view is None:
            NSBeep()
            return
        view.scroll_view.commandView.activate(self)

    def execute(self, text):
        self.reset()
        if not text:
            return
        cmdstr, space, argstr = text.partition(" ")
        doc_view = self.editor.current_view
        if doc_view is None:
            NSBeep()
            return
        command = self.text_commander.lookup(cmdstr)
        if command is not None:
            try:
                args = command.arg_parser.parse(argstr)
            except Exception:
                msg = 'argument parse error: {}'.format(argstr)
                self.message(msg, exc_info=True)
                return
        else:
            argstr = text
            command, args = self.text_commander.lookup_full_command(argstr)
            if command is None:
                self.message('unknown command: {}'.format(argstr))
                return
        if args is None:
            self.message('invalid command arguments: {}'.format(argstr))
            return
        try:
            command(doc_view.text_view, self, args)
        except CommandError as err:
            self.message(err)
        except Exception:
            self.message('error in command: {}'.format(command), exc_info=True)
        else:
            self.text_commander.history.append(command.name, text)

    def _find_command(self, text):
        """Get a tuple (command, argument_string)

        :returns: A tuple ``(command, argument_string)``. ``command`` will be
        ``None`` if no matching command is found.
        """
        if not text:
            return None, text
        cmdstr, space, argstr = text.partition(" ")
        command = self.text_commander.lookup(cmdstr)
        if command is None:
            argstr = text
            command, a = self.text_commander.lookup_full_command(argstr, False)
        return command, argstr

    def get_placeholder(self, text):
        """Get arguments placeholder text"""
        command, argstr = self._find_command(text)
        if command is not None:
            placeholder = command.arg_parser.get_placeholder(argstr)
            if placeholder:
                if text and not argstr and not text.endswith(" "):
                    return " " + placeholder
                return placeholder
        return ""

    def get_completions(self, text):
        """Get completions for the word at the end of the given command string

        :param text: Command string.
        :returns: A tuple consisting of a list of potential completions
        and/or replacements for the word at the end of the command text,
        and the index of the item that should be selected (-1 for no
        selection).
        """
        if " " not in text:
            words = sorted(name
                for name in self.text_commander.commands
                if isinstance(name, basestring) and name.startswith(text))
            index = 0 if words else -1
        else:
            command, argstr = self._find_command(text)
            if command is not None:
                words = command.arg_parser.get_completions(argstr)
                index = (0 if words else -1)
            else:
                words, index = [], -1
        return words, index

    def should_insert_newline(self, text, index):
        """Return true if a newline can be inserted in text at index"""
        return False # TODO implement this

    def get_history(self, current_text, forward=False):
        if self.history_view is None:
            self.history_view = self.text_commander.history.view()
        return self.history_view.get(current_text, forward)

    def message(self, text, exc_info=None, **kw):
        if exc_info:
            if isinstance(exc_info, (int, bool)):
                exc_info = sys.exc_info()
            exc = "\n\n" + "".join(traceback.format_exception(*exc_info))
        else:
            exc = ""
        msg = "{}{}".format(text, exc)
        view = self.editor.current_view
        if view is None:
            log.info(text, exc_info=exc_info)
            NSBeep()
        else:
            view.scroll_view.commandView.message(self, msg, **kw)

    def reset(self):
        view, self.history_view = self.history_view, None
        if view is not None:
            self.text_commander.history.discard_view(view)


class TextCommandController(object):

    def __init__(self, history):
        self.history = history
        self.tagger = count()
        self.commands = commands = {}
        self.commands_by_path = bypath = defaultdict(list)
        self.lookup_full_commands = []
        self.input_handlers = {}
        self.editems = editems = {}
#         ntc = menu.itemAtIndex_(1) # New Text Command menu item
#         ntc.setTarget_(self)
#         ntc.setAction_("newTextCommand:")
#         etc = menu.itemAtIndex_(2).submenu() # Edit Text Command menu
        #self.load_commands()

    def lookup(self, alias):
        return self.commands.get(alias)

    def lookup_full_command(self, command_text, full_parse=True):
        for command in self.lookup_full_commands:
            try:
                args = command.arg_parser.parse(command_text)
            except ArgumentError as err:
                if full_parse or not err.options:
                    continue
                args = err.options
            except Exception:
                log.warn('cannot parse command: %s', command_text, exc_info=True)
                continue
            if args is not None:
                return command, args
        return None, None

    def get_completions(self, text, index):
        # TODO implement this
        return []

    @classmethod
    def iter_command_modules(self):
        """Iterate text commands, yield (<command file path>, <command instance>)"""
        # load local (built-in) commands
        yield None, load_commands()

    def load_commands(self, menu):
        for path, reg in self.iter_command_modules():
            for command in reg.get("text_menu_commands", []):
                self.add_command(command, path, menu)
            self.input_handlers.update(reg.get("input_handlers", {}))

    def add_command(self, command, path, menu):
        if command.title is not None:
            command.__tag = tag = self.tagger.next()
            hotkey, keymask = self.validate_hotkey(command.hotkey)
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                command.title, "performTextCommand:", hotkey)
            item.setKeyEquivalentModifierMask_(keymask)
            item.setTag_(tag)
            # HACK tag will not be the correct index if an item is ever removed
            menu.insertItem_atIndex_(item, tag)
            self.commands[tag] = command
        if command.lookup_with_arg_parser:
            self.lookup_full_commands.insert(0, command)
        if command.names:
            for alias in command.names:
                if not isinstance(alias, basestring) or ' ' in alias:
                    log.warn('invalid command alias (%r) for %s loaded from %s',
                        alias, command, path)
                else:
                    self.commands[alias] = command

    def validate_hotkey(self, value):
        if value is not None:
            assert len(value) == 2, "invalid hotkey tuple: %r" % (value,)
            # TODO check if a hot key is already in use; ignore if it is
            return value
        return u"", 0

    def is_textview_command_enabled(self, textview, sender):
        command = self.commands.get(sender.tag())
        if command is not None:
            try:
                return command.is_enabled(textview, sender)
            except Exception:
                log.error("%s.is_enabled failed", type(command).__name__, exc_info=True)
        return False

    def do_textview_command(self, textview, sender):
        command = self.commands.get(sender.tag())
        if command is not None:
            try:
                command(textview, sender, None)
            except Exception:
                log.error("%s.execute failed", type(command).__name__, exc_info=True)

    def do_textview_command_by_selector(self, textview, selector):
        #log.debug(selector)
        callback = self.input_handlers.get(selector)
        if callback is not None:
            try:
                callback(textview, None, None)
                return True
            except Exception:
                log.error("%s failed", callback, exc_info=True)
        return False


class CommandHistory(History):

    def append(self, command_name, command_text):
        super(CommandHistory, self).append([command_name, command_text])

    def __iter__(self):
        for item in super(CommandHistory, self).__iter__():
            yield item[1]

    def __getitem__(self, index):
        item = super(CommandHistory, self).__getitem__(index)
        if item is not None:
            return item[1]
        return item

    def iter_by_name(self, name):
        """Iterate command history for the named command"""
        for hist in super(CommandHistory, self).__iter__():
            if not isinstance(hist, basestring): # HACK handle legacy history format
                name_, command = hist
                if name_ == name:
                    yield command
