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
from math import ceil

import AppKit as ak
import Foundation as fn
from objc import Category

from editxt.controls.cells import HoverButtonCell
from editxt.util import representedObject

log = logging.getLogger(__name__)


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# NSTreeControllers and NSOutlineView categories

class NSTreeController(Category(ak.NSTreeController)):
    """Category to make ak.NSTreeController more useable

    Based on extension by Wil Shipley
    http://www.wilshipley.com/blog/2006/04/pimp-my-code-part-10-whining-about.html

    See also:
    http://jonathandann.wordpress.com/2008/04/06/using-nstreecontroller/
    http://www.cocoabuilder.com/archive/message/cocoa/2008/5/18/207078
    """

    def setSelectedObject_(self, obj):
        self.setSelectedObjects_([obj])

    def setSelectedObjects_(self, objects):
        paths = [self.indexPathForObject_(obj) for obj in objects]
        self.setSelectionIndexPaths_(paths)

    def objectAtArrangedIndexPath_(self, path):
        return self.arrangedObjects().objectAtIndexPath_(path)

    def nodeAtArrangedIndexPath_(self, path):
        return self.arrangedObjects().nodeAtIndexPath_(path)

    def nodeForObject_(self, obj):
        return self.nodeAtArrangedIndexPath_(self.indexPathForObject_(obj))

    def indexPathForObject_(self, obj):
        return self._indexPathFromIndexPath_inChildren_toObject_(None, self.content(), obj)

    def _indexPathFromIndexPath_inChildren_toObject_(self, basePath, children, obj):
        for childIndex, child in enumerate(children):
            lkp = self.leafKeyPath()
            if lkp and child.valueForKeyPath_(lkp):
                childsChildren = []
            else:
                ckp = self.countKeyPath()
                if ckp:
                    childCount = child.valueForKeyPath_(ckp).unsignedIntValue()
                if ckp and not childCount:
                    childsChildren = []
                else:
                    childsChildren = child.valueForKeyPath_(self.childrenKeyPath())
            if obj is child or childsChildren:
                if basePath is None:
                    path = fn.NSIndexPath.indexPathWithIndex_(childIndex)
                else:
                    path = basePath.indexPathByAddingIndex_(childIndex)
                if obj is child:
                    return path
                if childsChildren:
                    path = self._indexPathFromIndexPath_inChildren_toObject_(path, childsChildren, obj)
                    if path is not None:
                        return path
        return None

class NSOutlineView(Category(ak.NSOutlineView)):
    """Category to improve usability of ak.NSOutlineView

    Originally based on extension by Wil Shipley
    http://www.wilshipley.com/blog/2006/04/pimp-my-code-part-10-whining-about.html

    See also:
    http://jonathandann.wordpress.com/2008/04/06/using-nstreecontroller/
    http://www.cocoabuilder.com/archive/message/cocoa/2008/5/18/207078
    """

    def realItemForOpaqueItem_(self, item):
        return representedObject(item)

    def iterVisibleObjects(self):
        """Iterate (row, visible object) pairs"""
        for row in range(self.numberOfRows()):
            item = self.itemAtRow_(row)
            yield row, representedObject(item)


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# HoverButtonCell-aware OutlineView

class OutlineView(ak.NSOutlineView):

    def initWithCoder_(self, coder):
        self = super(OutlineView, self).initWithCoder_(coder)
        self.configureTracking()
        return self

    def initWithFrame_(self, frame):
        self = super(OutlineView, self).initWithFrame_(frame)
        self.configureTracking()
        return self

    def reloadData(self):
        # based on Jonathan Dann's ESOutlineView
        super(OutlineView, self).reloadData()
        for row in reversed(range(self.numberOfRows())):
            item = self.itemAtRow_(row)
            obj = representedObject(item)
            if getattr(obj, "expanded", False):
                self.expandItem_(item)
    def awakeFromNib(self):
        self.configureTracking()

    def configureTracking(self):
        self._trackMouseEvents = True
        self.trackingTag = -1
        self.mouseRow = -1
        self.mouseCol = -1
        self.resetCursorRects()

    def dealloc(self):
        if self.trackingTag != -1:
            self.removeTrackingRect_(self.trackingTag)
            self.trackingTag = -1
        super(OutlineView, self).dealloc()

    def trackMouseEvents(self):
        return self._trackMouseEvents

    def setTrackMouseEvents_(self, value):
        self._trackMouseEvents = value
        self.resetCursorRects()

    def viewWillMoveToSuperview_(self, view):
        if self.trackingTag != -1:
            # remove old tracking rects when we change superviews
            self.removeTrackingRect_(self.trackingTag)
            self.trackingTag = -1
            self.window().remove_mouse_moved_responder(self)
        super(OutlineView, self).viewWillMoveToSuperview_(view)

    def viewDidMoveToSuperview(self):
        super(OutlineView, self).viewDidMoveToSuperview()
        self.resetCursorRects()

    def viewWillMoveToWindow_(self, window):
        if self.trackingTag != -1:
            self.removeTrackingRect_(self.trackingTag)
            self.trackingTag = -1
            self.window().remove_mouse_moved_responder(self)
        super(OutlineView, self).viewWillMoveToWindow_(window)

    def viewDidMoveToWindow(self):
        super(OutlineView, self).viewDidMoveToWindow()
        self.resetCursorRects()

    def frameDidChange_(self, notification):
        self.resetCursorRects()

    def _mouseInside(self):
        if self.window() is not None and self.superview() is not None:
            mloc = self.window().mouseLocationOutsideOfEventStream()
            mloc = self.superview().convertPoint_fromView_(mloc, None)
            return self.hitTest_(mloc) is not None
        return False

    def resetCursorRects(self):
        # stop any existing tracking
        if self.trackingTag != -1:
            self.removeTrackingRect_(self.trackingTag)
            self.trackingTag = -1
            self.window().remove_mouse_moved_responder(self)

        # Add a tracking rect if our superview and window are ready
        if self.trackMouseEvents() and self.window() is not None:
            inside = self._mouseInside()
            self.trackingTag = self.addTrackingRect_owner_userData_assumeInside_(
                self.bounds(), self, 0, inside)
            if inside:
                self.mouseEntered_(None)

    def mouseEntered_(self, event):
        self.window().add_mouse_moved_responder(self)
        super(OutlineView, self).mouseEntered_(event)

    def mouseExited_(self, event):
        if not self._mouseInside():
            self.window().remove_mouse_moved_responder(self)
            self.mouseMoved_(event)
        super(OutlineView, self).mouseExited_(event)

    def exitPreviousCell(self):
        if self.mouseRow != -1 and self.mouseCol != -1:
            col = self.tableColumns().objectAtIndex_(self.mouseCol)
            cell = col.dataCell()
            #self.delegate().tableView_willDisplayCell_forTableColumn_row_(self, cell, col, self.mouseRow)

            if isinstance(cell, HoverButtonCell):
                frame = self.frameOfCellAtColumn_row_(self.mouseCol, self.mouseRow)
                if cell.mouseExitedInvalidatesForFrame_(frame):
                    #cell.drawWithFrame_inView_(frame, self)
                    self.setNeedsDisplayInRect_(frame)
            self.mouseRow = -1
            self.mouseCol = -1

    def mouseDown_(self, event):
        cevent = event
        emask = ak.NSLeftMouseDraggedMask | ak.NSLeftMouseUpMask
        future = fn.NSDate.distantFuture()
        while True:
            etype = cevent.type()
            point = self.convertPoint_fromView_(
                cevent.locationInWindow(), self.window().contentView())
            row = self.rowAtPoint_(point)
            col = self.columnAtPoint_(point)

            if row < 0 or col < 0:
                break # defer to standard mouseDown
            else:
                column = self.tableColumns().objectAtIndex_(col)
                cell = column.dataCell()

                if not isinstance(cell, HoverButtonCell):
                    break # defer to standard mouseDown

                # update cell according to the delegate
                #self.delegate().tableView_willDisplayCell_forTableColumn_row_(
                #    self, cell, column, row)
                cellFrame = self.frameOfCellAtColumn_row_(col, row)

            redraw = False
            finished = False
            if etype == ak.NSLeftMouseDown:
                finished, redraw = cell.trackMouseAtPoint_invalidatesForFrame_redraw_(
                    point, cellFrame, redraw)
                finished = not finished
            elif etype == ak.NSLeftMouseDragged:
                finished, redraw = cell.continueTrackingMouseAtPoint_invalidatesForFrame_redraw_(
                    point, cellFrame, redraw)
                finished = not finished
            elif etype == ak.NSLeftMouseUp:
                redraw = cell.mouseUpAtPoint_invalidatesForFrame_(point, cellFrame)
                finished = True
            else:
                #raise NSException("Invalid event type: %s" % etype)
                log.error("Invalid event type: %s", etype)
                break

            if redraw:
                #cell.drawWithFrame_inView_(cellFrame, self)
                self.setNeedsDisplayInRect_(cellFrame)

            if finished: break

            cevent = self.window().nextEventMatchingMask_untilDate_inMode_dequeue_(
                emask, future, ak.NSEventTrackingRunLoopMode, True)
            if cevent is None:
                break

        # if no events were processed, call the table view implemenation
        if cevent is event: super(OutlineView, self).mouseDown_(event)

    def mouseMoved_(self, event):
        point = self.convertPoint_fromView_(
            event.locationInWindow(), self.window().contentView())
        row = self.rowAtPoint_(point)
        col = self.columnAtPoint_(point)

        cellChange = self.mouseRow != row or self.mouseCol != col
        if cellChange: self.exitPreviousCell()

        if row >= 0 and col >= 0:
            column = self.tableColumns().objectAtIndex_(col)
            cell = column.dataCell()
            if isinstance(cell, HoverButtonCell):
                frame = self.frameOfCellAtColumn_row_(col, row)
                redraw = False

                # update the cell according to the delegate
                #self.delegate().tableView_willDisplayCell_forTableColumn_row_(self, cell, column, row)

                # process mouse entered if needed
                if cellChange:
                    redraw = cell.mouseEnteredInvalidatesForFrame_(frame)

                # adjusting because these numbers appear to be off slightly
                redraw = cell.mouseMoveToPoint_invalidatesForFrame_(point, frame) or redraw

                if redraw:
                    #cell.drawWithFrame_inView_(frame, self)
                    self.setNeedsDisplayInRect_(frame)

        self.mouseRow = row
        self.mouseCol = col
        # calling super would cause an infinite loop
        # since we're not registered as the first responder
