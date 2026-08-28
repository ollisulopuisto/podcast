import AppKit
import NhsxKit
import Quartz

/// `.nhsx`-istunnon esikatselu Finderin välilyönnillä.
///
/// Näyttää aikajanan — raidat, alueet, vaimennetut kohdat — ja soittaa
/// miksauksen. Ääntä ei renderöidä: `MixPlayer` sijoittaa lähteet
/// aikajanalle ja antaa järjestelmän summata ne. Siksi tämä avautuu yhtä
/// nopeasti tunnin istunnosta kuin minuutin.
///
/// Laajennus on hiekkalaatikossa eikä voi käynnistää `nhsx-render`iä — se
/// on koko syy siihen, että `NhsxKit` jäsentää `.nhsx`:n uudestaan Swiftillä
/// eikä kutsu Pythonia. Kahden jäsentimen pitäminen samaa mieltä on
/// `Conformance/`in tehtävä.
public final class PreviewViewController: NSViewController, QLPreviewingController {

    private var player: MixPlayer?
    private var mix: Mix?
    private let timeline = TimelineView()
    private let summary = NSTextField(labelWithString: "")
    private let note = NSTextField(labelWithString: "")
    private let playButton = NSButton()

    public override func loadView() {
        let root = NSView(frame: NSRect(x: 0, y: 0, width: 720, height: 420))

        summary.font = .systemFont(ofSize: 13, weight: .medium)
        note.font = .systemFont(ofSize: 11)
        note.textColor = .secondaryLabelColor
        note.maximumNumberOfLines = 3

        playButton.bezelStyle = .rounded
        playButton.title = "Soita"
        playButton.target = self
        playButton.action = #selector(togglePlay)

        let stack = NSStackView(views: [summary, timeline, note, playButton])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 10
        stack.edgeInsets = NSEdgeInsets(top: 16, left: 16, bottom: 16, right: 16)
        stack.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            stack.topAnchor.constraint(equalTo: root.topAnchor),
            stack.bottomAnchor.constraint(lessThanOrEqualTo: root.bottomAnchor),
            timeline.heightAnchor.constraint(greaterThanOrEqualToConstant: 220),
            timeline.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -32),
        ])
        view = root
    }

    public func preparePreviewOfFile(at url: URL) async throws {
        let session = try readSession(at: url.path)
        let plan = NhsxKit.plan(session)
        mix = plan
        timeline.show(session: session, mix: plan)
        summary.stringValue = Self.headline(session: session, mix: plan)
        note.stringValue = Self.footnote(mix: plan)
        playButton.isEnabled = !plan.clips.isEmpty
    }

    static func headline(session: Session, mix: Mix) -> String {
        let speakers = mix.speakers.isEmpty ? "ei raitoja" : mix.speakers.joined(separator: ", ")
        return "\(session.name) — \(clock(mix.duration)) — \(speakers)"
    }

    /// Se, mitä esikatselu **ei** tiennyt, sanotaan tässä.
    ///
    /// Miksaus joka ohitti faderin näyttää kelvolliselta ja on väärällä
    /// tasolla. Sama sääntö kuin `nhsx-render`in varoituksessa.
    static func footnote(mix: Mix) -> String {
        var parts: [String] = []
        if mix.muted > 0 { parts.append("\(mix.muted) vaimennettua aluetta") }
        if !mix.missing.isEmpty {
            parts.append("ääntä ei löytynyt: \(mix.missing.joined(separator: ", "))")
        }
        if !mix.unknown.isEmpty {
            let names = mix.unknown.keys.sorted().joined(separator: ", ")
            parts.append("lukematta jäi: \(names) — jos joukossa on taso tai panorointi, "
                         + "esikatselu on niiltä osin väärä")
        }
        return parts.joined(separator: " · ")
    }

    static func clock(_ seconds: Double) -> String {
        let whole = Int(seconds.rounded())
        let (h, m, s) = (whole / 3600, (whole % 3600) / 60, whole % 60)
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%d:%02d", m, s)
    }

    @objc private func togglePlay() {
        if let player, player.isPlaying {
            player.stop()
            self.player = nil
            playButton.title = "Soita"
            return
        }
        guard let mix else { return }
        let fresh = MixPlayer(mix: mix)
        do {
            try fresh.prepare()
            fresh.play()
            player = fresh
            playButton.title = "Seis"
        } catch {
            note.stringValue = "\(error)"
        }
    }

    public override func viewWillDisappear() {
        super.viewWillDisappear()
        player?.stop()
        player = nil
    }
}
