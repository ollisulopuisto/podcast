import AppKit
import NhsxKit

/// Istunnon katselu: aikajana, tiedot ja toisto.
///
/// **Tämä on se näkymä, ja sitä on vain yksi.** Sekä `NHSX Viewer.app` että
/// Quick Look -laajennus näyttävät tämän — sovellus ikkunassaan, laajennus
/// Finderin esikatselupaneelissa. Kaksi näkymää samasta istunnosta ajautuisi
/// erilleen täsmälleen kuten kaksi jäsennintä, ja tämä on halvempi estää:
/// jäsentimet eivät voi jakaa koodia, näkymät voivat.
///
/// Siksi tämä on `NhsxViewer`-kirjastossa eikä kummankaan kohteen sisällä.
/// Laajennus on ohut kuori (`PreviewViewController`), sovellus on toinen
/// (`ViewerWindowController`), ja kumpikin vain antaa tälle istunnon.
public final class SessionView: NSView {

    private let summary = NSTextField(labelWithString: "")
    private let note = NSTextField(labelWithString: "")
    private let timeline = TimelineView()
    private let playButton = NSButton()

    private var player: MixPlayer?
    private var mix: Mix?

    public override init(frame: NSRect) {
        super.init(frame: frame)
        build()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("ei storyboardeja") }

    private func build() {
        summary.font = .systemFont(ofSize: 13, weight: .medium)
        summary.lineBreakMode = .byTruncatingTail

        note.font = .systemFont(ofSize: 11)
        note.textColor = .secondaryLabelColor
        note.maximumNumberOfLines = 3
        note.lineBreakMode = .byWordWrapping

        playButton.bezelStyle = .rounded
        playButton.title = "Soita"
        playButton.target = self
        playButton.action = #selector(togglePlay)
        playButton.isEnabled = false

        let stack = NSStackView(views: [summary, timeline, note, playButton])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 10
        stack.edgeInsets = NSEdgeInsets(top: 16, left: 16, bottom: 16, right: 16)
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: trailingAnchor),
            stack.topAnchor.constraint(equalTo: topAnchor),
            stack.bottomAnchor.constraint(lessThanOrEqualTo: bottomAnchor),
            timeline.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -32),
            timeline.heightAnchor.constraint(greaterThanOrEqualToConstant: 200),
        ])
    }

    // MARK: - Sisältö

    /// Näyttää istunnon polusta. Palauttaa virheen, jos tiedosto ei kelpaa.
    public func show(sessionAt path: String) throws {
        let session = try readSession(at: path)
        show(session: session, mix: plan(session))
    }

    public func show(session: Session, mix mixdown: Mix) {
        stop()
        mix = mixdown
        timeline.show(session: session, mix: mixdown)
        summary.stringValue = Self.headline(session: session, mix: mixdown)
        note.stringValue = Self.footnote(mix: mixdown)
        playButton.isEnabled = !mixdown.clips.isEmpty
    }

    /// Virhe näkyy samassa paikassa kuin muukin: esikatselupaneelissa ei ole
    /// mihin avata valintaikkuna, ja tyhjä paneeli ei kerro mitään.
    public func show(error: Error) {
        stop()
        mix = nil
        summary.stringValue = "Istuntoa ei voi lukea"
        note.stringValue = "\(error)"
        playButton.isEnabled = false
    }

    static func headline(session: Session, mix: Mix) -> String {
        let speakers = mix.speakers.isEmpty ? "ei raitoja" : mix.speakers.joined(separator: ", ")
        return "\(session.name) — \(clock(mix.duration)) — \(speakers)"
    }

    /// Se, mitä katselu **ei** tiennyt, sanotaan tässä.
    ///
    /// Miksaus joka ohitti faderin näyttää kelvolliselta ja on väärällä
    /// tasolla; ääni jota ei löytynyt levyltä on hiljaisuutta jolle on syy.
    /// Sama sääntö kuin `nhsx-render`in varoituksessa.
    static func footnote(mix: Mix) -> String {
        var parts: [String] = []
        if mix.muted > 0 { parts.append("\(mix.muted) vaimennettua aluetta") }
        if !mix.missing.isEmpty {
            parts.append("ääntä ei löytynyt: \(mix.missing.joined(separator: ", "))")
        }
        if !mix.unknown.isEmpty {
            let names = mix.unknown.keys.sorted().joined(separator: ", ")
            parts.append("lukematta jäi: \(names) — jos joukossa on taso tai "
                         + "panorointi, tämä näkymä on niiltä osin väärä")
        }
        return parts.joined(separator: " · ")
    }

    static func clock(_ seconds: Double) -> String {
        let whole = Int(seconds.rounded())
        let (h, m, s) = (whole / 3600, (whole % 3600) / 60, whole % 60)
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%d:%02d", m, s)
    }

    // MARK: - Toisto

    @objc private func togglePlay() {
        if player?.isPlaying == true {
            stop()
            return
        }
        guard let mix else { return }
        let fresh = MixPlayer(mix: mix)
        do {
            try fresh.prepare()
            fresh.play()
            player = fresh
            playButton.title = "Seis"
            // Lähde, joka ei auennut, kerrotaan heti eikä jätetä
            // hiljaisuudeksi jolle ei ole selitystä.
            if !fresh.unreadable.isEmpty {
                note.stringValue = "ei auennut: " + fresh.unreadable.joined(separator: ", ")
            }
        } catch {
            note.stringValue = "\(error)"
        }
    }

    /// Pysäyttää toiston. Ikkunan sulkeminen ja esikatselun vaihtuminen
    /// kutsuvat tätä — muuten ääni jatkuisi näkymän jälkeen.
    public func stop() {
        player?.stop()
        player = nil
        playButton.title = "Soita"
    }

    deinit { player?.stop() }
}
