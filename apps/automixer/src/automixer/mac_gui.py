"""Native AppKit shell for single-file Automixer jobs (Apple Silicon).

Imported only by the GUI entry point, never the portable CLI.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from automixer.desktop_controller import (
    COMMANDS,
    Controller,
    progress_percent,
    shortcut_text,
)

APP_NAME = 'Automixer'
BUNDLE_ID = 'com.sulopuis.automixer'


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--file-worker':
        from automixer.file_worker import main as worker_main
        sys.argv.pop(1)
        return worker_main()
    if sys.platform != 'darwin':
        raise RuntimeError('The native Automixer window requires macOS')
    import AppKit as A
    import objc
    from Foundation import NSObject, NSThread

    from automixer.folder_events import MacFolderEvents

    class Delegate(NSObject):
        def applicationDidFinishLaunching_(self, _notification):
            self.language = 'fi' if str(A.NSLocale.preferredLanguages()[0]).startswith('fi') else 'en'
            self.pending_paths = getattr(self, 'pending_paths', [])
            self.watcher = None
            self.state_dir = Path.home() / 'Library' / 'Application Support' / APP_NAME
            self.controller = Controller(self.state_dir, on_event=self.event)
            self.window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                A.NSMakeRect(0, 0, 920, 620),
                A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable | A.NSWindowStyleMaskMiniaturizable,
                A.NSBackingStoreBuffered, False,
            )
            self.window.setTitle_(APP_NAME)
            self.window.setDelegate_(self)
            self.window.center()
            view = self.window.contentView()
            self.tabs = A.NSSegmentedControl.alloc().initWithFrame_(A.NSMakeRect(310, 554, 300, 30))
            self.tabs.setSegmentCount_(2)
            self.tabs.setLabel_forSegment_(self.text('Files', 'Tiedostot'), 0)
            self.tabs.setLabel_forSegment_(self.text('Folder', 'Kansio'), 1)
            self.tabs.setSelectedSegment_(0)
            self.tabs.setTarget_(self)
            self.tabs.setAction_('tabChanged:')
            view.addSubview_(self.tabs)
            self.drop = DropView.alloc().initWithFrame_(A.NSMakeRect(46, 278, 828, 248))
            self.drop.owner = self
            self.drop.registerForDraggedTypes_([A.NSPasteboardTypeFileURL])
            view.addSubview_(self.drop)
            self.level = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(A.NSMakeRect(385, 314, 150, 28), False)
            self.level.addItemsWithTitles_(['-16 LUFS', '-14 LUFS', '-18 LUFS', '-20 LUFS', '-23 LUFS'])
            self.level.setTarget_(self)
            self.level.setAction_('levelChanged:')
            view.addSubview_(self.level)
            self.name = A.NSTextField.labelWithString_('')
            self.name.setFrame_(A.NSMakeRect(90, 210, 690, 24))
            view.addSubview_(self.name)
            self.progress = A.NSProgressIndicator.alloc().initWithFrame_(A.NSMakeRect(90, 187, 690, 8))
            self.progress.setMinValue_(0)
            self.progress.setMaxValue_(100)
            view.addSubview_(self.progress)
            self.status = A.NSTextField.labelWithString_('')
            self.status.setFrame_(A.NSMakeRect(90, 154, 690, 20))
            view.addSubview_(self.status)
            self.buttons = {}
            for ident, title, x, y in [('add', '+', 46, 208), ('cancel', '■', 808, 178), ('start', '▶', 798, 36)]:
                button = A.NSButton.buttonWithTitle_target_action_(title, self, 'command:')
                button.setIdentifier_(ident)
                button.setToolTip_(next(self.title(c) for c in COMMANDS if c.id == ident))
                button.setFrame_(A.NSMakeRect(x, y, 76 if ident == 'start' else 40, 32))
                view.addSubview_(button)
                self.buttons[ident] = button
            self.installMenu()
            self.window.makeKeyAndOrderFront_(None)
            A.NSApp.activateIgnoringOtherApps_(True)
            self.addPaths(self.pending_paths)
            if '--smoke' not in sys.argv:
                self.performSelector_withObject_afterDelay_('showUpgrade:', None, .3)
            if '--smoke' in sys.argv:
                self.performSelector_withObject_afterDelay_('smoke:', None, 1.0)
            for arg in [] if '--smoke' in sys.argv else sys.argv[1:]:
                if not arg.startswith('-'):
                    self.addPaths([arg])

        @objc.python_method
        def text(self, en, fi):
            return fi if self.language == 'fi' else en

        @objc.python_method
        def title(self, command):
            return command.title_fi if self.language == 'fi' else command.title_en

        @objc.python_method
        def installMenu(self):
            bar = A.NSMenu.alloc().init()
            for menu_id in ['Automixer', 'File', 'Process', 'Help']:
                top = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    {'File': self.text('File', 'Tiedosto'), 'Process': self.text('Process', 'Käsittely'),
                     'Help': self.text('Help', 'Ohje')}.get(menu_id, menu_id), None, '')
                menu = A.NSMenu.alloc().init()
                for command in COMMANDS:
                    if command.menu != menu_id:
                        continue
                    item = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(self.title(command), 'command:', command.key)
                    item.setTarget_(self)
                    item.setRepresentedObject_(command.id)
                    menu.addItem_(item)
                top.setSubmenu_(menu)
                bar.addItem_(top)
            A.NSApp.setMainMenu_(bar)

        def command_(self, sender):
            ident = sender.representedObject() if hasattr(sender, 'representedObject') else sender.identifier()
            if ident in {'add', 'folder'}:
                panel = A.NSOpenPanel.openPanel()
                panel.setCanChooseDirectories_(ident == 'folder')
                panel.setCanChooseFiles_(ident == 'add')
                panel.setAllowsMultipleSelection_(ident == 'add')
                if panel.runModal() == A.NSModalResponseOK:
                    self.addPaths([url.path() for url in panel.URLs()])
            elif ident == 'start':
                try:
                    mode = 'folder' if self.tabs.selectedSegment() == 1 else 'files'
                    self.controller.start(mode=mode)
                    if mode == 'folder':
                        if self.watcher is not None:
                            self.watcher.close()
                        self.watcher = MacFolderEvents(
                            self.controller.folder, self.controller.scan,
                            on_error=lambda exc: self.event({'source': str(self.controller.folder), 'state': 'failed', 'error': str(exc)}),
                        )
                except Exception as exc:
                    self.status.setStringValue_(str(exc))
            elif ident == 'cancel':
                if self.watcher is not None:
                    self.watcher.close()
                    self.watcher = None
                self.controller.cancel()
            elif ident == 'reveal':
                if self.controller.outputs:
                    url = A.NSURL.fileURLWithPath_(list(self.controller.outputs.values())[-1])
                    A.NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_([url])
            elif ident == 'changes':
                self.showChanges()
            elif ident == 'shortcuts':
                alert = A.NSAlert.alloc().init()
                alert.setMessageText_(self.text('Keyboard Shortcuts', 'Pikanäppäimet'))
                alert.setInformativeText_(shortcut_text(self.language))
                alert.runModal()
            elif ident == 'quit':
                A.NSApp.terminate_(None)

        @objc.python_method
        def addPaths(self, paths):
            self.controller.add_paths(paths)
            if self.controller.folder and not self.controller.files:
                self.tabs.setSelectedSegment_(1)
                self.name.setStringValue_(self.controller.folder.name)
            elif self.controller.files:
                self.name.setStringValue_(self.controller.files[-1].name)

        def tabChanged_(self, sender):
            self.name.setStringValue_(self.controller.folder.name if sender.selectedSegment() == 1 and self.controller.folder else self.controller.files[-1].name if self.controller.files else '')

        def levelChanged_(self, sender):
            self.controller.target_lufs = float(sender.titleOfSelectedItem().split()[0])

        @objc.python_method
        def event(self, event):
            self.performSelectorOnMainThread_withObject_waitUntilDone_('receiveEvent:', json.dumps(event), False)

        def receiveEvent_(self, raw):
            event = json.loads(str(raw))
            self.name.setStringValue_(Path(event['source']).name)
            state = event['state']
            self.status.setStringValue_(event.get('error', '') if state == 'failed' else '')
            if state == 'running':
                self.progress.setIndeterminate_(True)
                self.progress.startAnimation_(None)
            if state == 'progress':
                percent = progress_percent(event.get('line', ''))
                if percent is not None:
                    self.progress.stopAnimation_(None)
                    self.progress.setIndeterminate_(False)
                    self.progress.setDoubleValue_(percent)
            if state in {'done', 'failed', 'cancelled'}:
                self.progress.stopAnimation_(None)
                self.progress.setIndeterminate_(False)
                self.progress.setDoubleValue_(100 if state == 'done' else 0)

        def showUpgrade_(self, _unused):
            from automixer import __version__
            seen = self.state_dir / 'seen-version'
            try:
                previous = seen.read_text(encoding='utf-8')
            except FileNotFoundError:
                previous = None
            if previous is not None and previous != __version__:
                self.showChanges()
            self.state_dir.mkdir(parents=True, exist_ok=True)
            seen.write_text(__version__, encoding='utf-8')

        @objc.python_method
        def showChanges(self):
            alert = A.NSAlert.alloc().init()
            alert.setMessageText_(self.text("What's New", 'Uutta tässä versiossa'))
            alert.setInformativeText_(self.text(
                'Single-file and watched-folder audio processing. Files are referenced, not copied. Existing outputs are never replaced.',
                'Yksittäisten tiedostojen ja seuratun kansion äänen käsittely. Tiedostoihin viitataan, niitä ei kopioida. Olemassa olevia tuloksia ei korvata.',
            ))
            alert.runModal()

        def smoke_(self, _unused):
            import os
            view = self.window.contentView()
            bitmap = view.bitmapImageRepForCachingDisplayInRect_(view.bounds())
            view.cacheDisplayInRect_toBitmapImageRep_(view.bounds(), bitmap)
            data = bitmap.representationUsingType_properties_(A.NSBitmapImageFileTypePNG, {})
            path = os.environ.get('AUTOMIXER_SMOKE_PNG', '/tmp/automixer-smoke.png')
            if not data.writeToFile_atomically_(path, True):
                raise RuntimeError('Could not save smoke screenshot')
            self.controller.close()
            A.NSApp.stop_(None)

        def application_openFiles_(self, app, paths):
            if hasattr(self, 'controller'):
                self.addPaths(paths)
            else:
                self.pending_paths = list(paths)
            app.replyToOpenOrPrint_(A.NSApplicationDelegateReplySuccess)

        def applicationShouldTerminate_(self, _app):
            # Do not block AppKit while a child unwinds and sends its last event.
            threading.Thread(target=self.finish, daemon=True).start()
            return A.NSTerminateLater

        @objc.python_method
        def finish(self):
            if self.watcher is not None:
                self.watcher.close()
            self.controller.close()
            self.performSelectorOnMainThread_withObject_waitUntilDone_('finished:', None, False)

        def finished_(self, _unused):
            A.NSApp.replyToApplicationShouldTerminate_(True)

        def windowShouldClose_(self, _window):
            A.NSApp.terminate_(None)
            return False

    class DropView(A.NSView):
        def drawRect_(self, _rect):
            A.NSColor.controlAccentColor().set()
            path = A.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(self.bounds(), 18, 18)
            path.setLineWidth_(3)
            path.stroke()
            attrs = {A.NSFontAttributeName: A.NSFont.systemFontOfSize_(64), A.NSForegroundColorAttributeName: A.NSColor.controlAccentColor()}
            A.NSString.stringWithString_('↓').drawAtPoint_withAttributes_(A.NSMakePoint(390, 120), attrs)

        def draggingEntered_(self, _sender):
            return A.NSDragOperationCopy

        def performDragOperation_(self, sender):
            urls = sender.draggingPasteboard().readObjectsForClasses_options_([A.NSURL], {A.NSPasteboardURLReadingFileURLsOnlyKey: True}) or []
            self.owner.addPaths([url.path() for url in urls])
            return bool(urls)

    assert NSThread.isMainThread()
    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyRegular)
    delegate = Delegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
