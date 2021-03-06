# -*- coding: utf-8 -*-
# EditXT
# Copyright 2007-2013 Daniel Miller <millerdev@gmail.com>
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
from collections import Callable
from functools import wraps

import AppKit as ak
import Foundation as fn

import editxt
from editxt.command.parser import CommandParser, Options, VarArgs
from editxt.command.util import make_command_predicate
from editxt.controls.alert import Caller
from editxt.util import KVOProxy, WeakProperty

log = logging.getLogger(__name__)


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Text command system interface
"""
The primary interface for loading text commands into EditXT is a module-level
function that returns a list of command functions provided by the module:

def load_commands():
    return [decorated_text_command, ...]
"""


def command(func=None, name=None, title=None, hotkey=None,
            is_enabled=None, arg_parser=None, lookup_with_arg_parser=False):
    """Text command decorator

    Text command signature: `text_command(textview, sender, args)`
    Both `sender` and `args` will be `None` in some contexts.

    :param name: A name that can be typed in the command bar to invoke the
        command. Defaults to the decorated callable's `__name__`.
    :param title: The command title displayed in Text menu. Not in menu if None.
    :param hotkey: Preferred command hotkey tuple: `(<key char>, <key mask>)`.
        Ignored if title is None.
    :param is_enabled: A callable that returns a boolean value indicating if
        the command is enabled in the Text menu. Always enabled if None.
        Signature: `is_enabled(textview, sender)`.
    :param arg_parser: An object inplementing the `CommandParser` interface.
        Defaults to `CommandParser(VarArgs("args"))`.
    :param lookup_with_arg_parser: If True, use the `arg_parser.parse` to
        lookup the command. The parser should return None if it receives
        a text string that cannot be parsed.
    """
    if isinstance(name, str):
        name = name.split()
    def command_decorator(func):
        def parse(argstr):
            if argstr.startswith(func.name + " "):
                argstr = argstr[len(func.name) + 1:]
            return func.arg_parser.parse(argstr)
        def arg_string(options):
            argstr = func.arg_parser.arg_string(options)
            if argstr:
                if not func.lookup_with_arg_parser:
                    argstr = "{} {}".format(func.name, argstr)
                return argstr
            return func.name
        func.is_text_command = True
        func.name = name[0] if name else func.__name__
        func.names = name or [func.__name__]
        func.title = title
        func.hotkey = hotkey
        func.is_enabled = is_enabled or (lambda textview, sender: True)
        func.arg_parser = arg_parser or CommandParser(VarArgs("args"))
        func.lookup_with_arg_parser = lookup_with_arg_parser
        func.parse = parse
        func.arg_string = arg_string
        return func
    if func is None:
        return command_decorator
    return command_decorator(func)


def load_options(command, history):
    predicate = make_command_predicate(command)
    argstr = next(history.iter_matching(predicate), None)
    if argstr is not None:
        try:
            return command.parse(argstr)
        except Exception:
            log.warn("cannot load options: %s", argstr, exc_info=True)
    return command.arg_parser.default_options()


def save_options(options, command, history):
    history.append(command.arg_string(options))


class CommandError(Exception):
    """Command error

    For command errors that should be presented without a traceback.
    """

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Base classes for GUI command controllers


def objc_delegate(func):
    """A decorator for marking delegate methods"""
    func.objc_delegate = True
    return func


class CommandController(object):
    """Base window controller for text commands"""

    OPTIONS_FACTORY = Options       # A callable that creates default options.
                                    # If this is a function, it should accept
                                    # one arguemnt (`self`).
    #NIB_NAME = "NibFilename"       # Abstract attribute.
    #COMMAND = <command>            # Abstract attribute: command callable

    @classmethod
    def controller_class(cls, **members):
        try:
            return cls.__dict__['_controller_class']
        except KeyError:
            pass
        def make_delegate(method):
            if not method.__name__.endswith("_"):
                # HACK assume no arguments
                @wraps(method)
                def delegate(self):
                    return method(self.controller)
            else:
                # HACK assume delegate takes one argument
                @wraps(method)
                def delegate(self, arg):
                    return method(self.controller, arg)
            return delegate
        members.update({name: make_delegate(value)
            for base in reversed(cls.__mro__)
            for name, value in vars(base).items()
            if isinstance(value, Callable) and getattr(value, "objc_delegate", False)})
        Class = type(cls.__name__ + "GUI", (_BaseCommandController,), members)
        cls._controller_class = Class
        return Class

    def __init__(self):
        self.gui = self.controller_class().create(self, self.NIB_NAME)
        self.history = editxt.app.text_commander.history # HACK deep reach into global
        if hasattr(self.COMMAND, 'im_func'):
            self.command = self.COMMAND.__func__ # HACK
        else:
            self.command = self.COMMAND
        self.options = KVOProxy(self.OPTIONS_FACTORY())
        self.load_options()

    def load_options(self):
        for key, value in load_options(self.command, self.history):
            setattr(self.options, key, value)

    def save_options(self):
        save_options(self.options, self.command, self.history)


class SheetController(CommandController):
    """abstract window controller for sheet-based text command"""

    DELEGATE_METHODS = {"cancel_": "cancel"}

    def __init__(self, textview):
        self.textview = textview
        super(SheetController, self).__init__()

    def begin_sheet(self, sender):
        self.caller = Caller.alloc().init(self.sheet_did_end)
        ak.NSApp.beginSheet_modalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.gui.window(), self.textview.window(), self.caller,
            "alertDidEnd:returnCode:contextInfo:", 0)

    def sheet_did_end(self, code):
        self.gui.window().orderOut_(None)

    @objc_delegate
    def cancel_(self, sender):
        ak.NSApp.endSheet_returnCode_(self.gui.window(), 0)


class PanelController(CommandController):
    """abstract window controller for panel-based text command"""

    @classmethod
    def shared_controller(cls):
        try:
            return cls.__dict__["_shared_controller"]
        except KeyError:
            cls._shared_controller = ctl = cls()
        return ctl


class _BaseCommandController(ak.NSWindowController):

    controller = WeakProperty()

    @classmethod
    def create(cls, controller, nib_name):
        obj = cls.alloc().initWithWindowNibName_(nib_name)
        obj.controller = controller
        return obj

    def initWithWindowNibName_(self, name):
        self = super(_BaseCommandController, self).initWithWindowNibName_(name)
        self.setWindowFrameAutosaveName_(name)
        return self

    def options(self):
        return self.controller.options

    def setOptions_(self, value):
        self.controller.options = value
