import AppKit
import NhsxKit
import NhsxViewer
import UniformTypeIdentifiers

/// `NHSX Viewer` — Hindenburgin istunto auki ilman Hindenburgia.
///
/// Avaa `.nhsx`, näe raidat ja alueet, kuule miksaus. Sama näkymä
/// (`NhsxViewer.SessionView`) on myös Quick Look -laajennuksessa, joten
/// Finderin välilyönti näyttää täsmälleen saman kuin sovellus.
///
/// Järjestys on tämä päin tarkoituksella: **katselin on tuote ja laajennus
/// on sen toinen pinta**, ei toisin päin. Laajennus tarvitsee isännän
/// joka tapauksessa (macOS ei asenna `.appex`iä yksin), ja isäntä joka ei
/// tee mitään on isäntä jota kukaan ei avaa — eikä laajennus rekisteröidy
/// ennen kuin sovellus on avattu kerran.
@main
final class AppDelegate: NSObject, NSApplicationDelegate {

    private var windows: [ViewerWindowController] = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        if windows.isEmpty { showWelcome() }
    }

    // MARK: - Tiedostojen avaus

    func application(_ sender: NSApplication, openFile path: String) -> Bool {
        open(path: path)
        return true
    }

    func application(_ sender: NSApplication, openFiles paths: [String]) {
        for path in paths { open(path: path) }
        sender.reply(toOpenOrPrint: .success)
    }

    private func open(path: String) {
        let controller = ViewerWindowController()
        controller.load(path: path)
        controller.showWindow(nil)
        windows.append(controller)
        // Tervetulotekstin ikkuna väistyy heti kun on oikeaa sisältöä.
        windows.removeAll { $0.isWelcome && $0.window?.isVisible != true }
    }

    @objc private func openDocument(_ sender: Any?) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        if let type = UTType(filenameExtension: "nhsx") {
            panel.allowedContentTypes = [type]
        }
        guard panel.runModal() == .OK else { return }
        for url in panel.urls { open(path: url.path) }
    }

    private func showWelcome() {
        let controller = ViewerWindowController(welcome: true)
        controller.showWindow(nil)
        windows.append(controller)
    }

    // MARK: - Valikko

    /// Valikko rakennetaan käsin, koska projektissa ei ole nibiä.
    ///
    /// Ilman **Avaa**-riviä sovellus voisi avata tiedostoja vain Finderistä,
    /// ja ilman **Sulje**- ja **Lopeta**-rivejä ikkunaa ei saisi kiinni
    /// näppäimistöltä — macOS ei anna näitä ilmaiseksi.
    private func buildMenu() {
        let main = NSMenu()

        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Tietoja: NHSX Viewer",
                        action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Lopeta", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)

        let fileItem = NSMenuItem()
        let fileMenu = NSMenu(title: "Arkisto")
        let open = NSMenuItem(title: "Avaa…", action: #selector(openDocument(_:)), keyEquivalent: "o")
        open.target = self
        fileMenu.addItem(open)
        fileMenu.addItem(withTitle: "Sulje", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        fileItem.submenu = fileMenu
        main.addItem(fileItem)

        NSApplication.shared.mainMenu = main
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

/// Yksi ikkuna, yksi istunto.
final class ViewerWindowController: NSWindowController {

    private let view = SessionView(frame: NSRect(x: 0, y: 0, width: 760, height: 460))
    let isWelcome: Bool

    init(welcome: Bool = false) {
        isWelcome = welcome
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 760, height: 460),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = welcome ? "NHSX Viewer" : ""
        window.center()
        super.init(window: window)
        window.delegate = self
        window.contentView = welcome ? Self.welcomeView() : view
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("ei storyboardeja") }

    func load(path: String) {
        window?.title = (path as NSString).lastPathComponent
        window?.representedFilename = path
        do {
            try view.show(sessionAt: path)
        } catch {
            view.show(error: error)
        }
    }

    private static func welcomeView() -> NSView {
        let text = NSTextField(wrappingLabelWithString: """
            NHSX Viewer

            Avaa .nhsx-istunto (Arkisto → Avaa…, tai vedä tiedosto tähän \
            ikkunaan): näet raidat ja alueet ja voit kuunnella miksauksen.

            Sama näkymä on Finderin esikatselussa: valitse .nhsx ja paina \
            välilyöntiä. Esikatselu rekisteröityy kun tämä sovellus on \
            Ohjelmat-kansiossa ja avattu kerran.

            Näkymä lukee alueiden paikat, vaimennukset, tasot, häivytykset ja \
            panoroinnin. Se ei aja taajuuskorjausta, kompressointia eikä \
            Hindenburgin ääniprofiileja, joten se ei kuulosta Hindenburgin \
            toistolta silloin kun niitä on käytetty.

            Kun istunnosta tarvitaan tiedosto, nhsx-render kirjoittaa siitä \
            WAVin.
            """)
        text.font = .systemFont(ofSize: 13)
        let padded = DropView()
        text.translatesAutoresizingMaskIntoConstraints = false
        padded.addSubview(text)
        NSLayoutConstraint.activate([
            text.leadingAnchor.constraint(equalTo: padded.leadingAnchor, constant: 28),
            text.trailingAnchor.constraint(equalTo: padded.trailingAnchor, constant: -28),
            text.topAnchor.constraint(equalTo: padded.topAnchor, constant: 28),
        ])
        return padded
    }
}

extension ViewerWindowController: NSWindowDelegate {
    /// Ikkunan sulkeminen pysäyttää toiston. Ilman tätä ääni jatkuisi
    /// ikkunasta joka ei ole enää näkyvissä.
    func windowWillClose(_ notification: Notification) {
        view.stop()
    }
}

/// Vedä ja pudota. Tervetuloikkuna ottaa `.nhsx`:n vastaan, koska se on
/// ensimmäinen asia jota ihminen yrittää.
final class DropView: NSView {
    override func awakeFromNib() { super.awakeFromNib() }

    override init(frame: NSRect) {
        super.init(frame: frame)
        registerForDraggedTypes([.fileURL])
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("ei storyboardeja") }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        paths(from: sender).isEmpty ? [] : .copy
    }

    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        let found = paths(from: sender)
        guard !found.isEmpty else { return false }
        NSApplication.shared.delegate?.application?(NSApplication.shared, openFiles: found)
        return true
    }

    private func paths(from sender: NSDraggingInfo) -> [String] {
        let urls = sender.draggingPasteboard.readObjects(
            forClasses: [NSURL.self], options: nil) as? [URL] ?? []
        return urls.filter { $0.pathExtension.lowercased() == "nhsx" }.map(\.path)
    }
}
