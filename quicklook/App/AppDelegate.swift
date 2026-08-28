import AppKit

/// Isäntäsovellus.
///
/// Tämä ei tee juuri mitään, ja se on tarkoitus. macOS:n Quick Look
/// -laajennus **ei ole asennettavissa yksin**: se on paketti sovelluksen
/// sisällä (`…app/Contents/PlugIns/…appex`), ja järjestelmä löytää sen vain
/// sitä kautta. Tämän sovelluksen tehtävä on siis olla olemassa
/// Ohjelmat-kansiossa, jotta laajennus on olemassa.
///
/// Ikkuna kertoo sen mitä käyttäjän on tiedettävä: että esikatselu toimii
/// Finderissä välilyönnillä, ja mistä saa työkalun joka renderöi istunnon
/// tiedostoksi.
@main
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let text = NSTextField(wrappingLabelWithString: """
            NHSX Quick Look

            Valitse Finderissä .nhsx-tiedosto ja paina välilyöntiä: näet \
            istunnon raidat ja alueet, ja voit kuunnella miksauksen.

            Esikatselu lukee alueiden paikat, vaimennukset, tasot, \
            häivytykset ja panoroinnin. Se ei aja taajuuskorjausta, \
            kompressointia eikä Hindenburgin ääniprofiileja, joten se ei \
            kuulosta Hindenburgin toistolta silloin kun niitä on käytetty.

            Kun istunnosta tarvitaan tiedosto, `nhsx-render` kirjoittaa \
            siitä WAVin ilman Hindenburgia.

            Tämän ikkunan saa sulkea. Esikatselu toimii niin kauan kuin \
            sovellus on Ohjelmat-kansiossa.
            """)
        text.font = .systemFont(ofSize: 13)

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 460, height: 300),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered, defer: false)
        window.title = "NHSX Quick Look"
        window.center()
        let padded = NSView()
        text.translatesAutoresizingMaskIntoConstraints = false
        padded.addSubview(text)
        NSLayoutConstraint.activate([
            text.leadingAnchor.constraint(equalTo: padded.leadingAnchor, constant: 24),
            text.trailingAnchor.constraint(equalTo: padded.trailingAnchor, constant: -24),
            text.topAnchor.constraint(equalTo: padded.topAnchor, constant: 24),
        ])
        window.contentView = padded
        window.makeKeyAndOrderFront(nil)
        self.window = window
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}
