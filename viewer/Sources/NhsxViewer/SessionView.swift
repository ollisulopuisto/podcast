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
    private let clockLabel = NSTextField(labelWithString: "")

    private var player: MixPlayer?
    private var mix: Mix?

    /// Piirtää osoittimen uudestaan soiton aikana. Ei kelloa toistolle —
    /// aika luetaan `MixPlayer.currentTime`istä eli äänimoottorilta.
    /// Tämä vain päättää kuinka usein katsotaan.
    private var ticker: Timer?

    /// Tosi raahauksen ajan. Kello ei saa siirtää osoitinta takaisin
    /// äänen kohdalle sen alta, jota käyttäjä juuri raahaa.
    private var isScrubbing = false

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

        clockLabel.font = .monospacedDigitSystemFont(ofSize: 11, weight: .regular)
        clockLabel.textColor = .secondaryLabelColor

        // Aikajanaa klikkaamalla ja raahaamalla kelataan. Näkymä ei tiedä
        // soittimesta mitään; se kertoo ajan, ja kelaus tehdään täällä.
        // Raahatessa liikkuu vain osoitin; ääni kelataan kun nappi nousee.
        timeline.onScrubPreview = { [weak self] time in self?.previewScrub(to: time) }
        timeline.onScrub = { [weak self] time in self?.seek(to: time) }

        let transport = NSStackView(views: [playButton, clockLabel])
        transport.orientation = .horizontal
        transport.spacing = 10
        transport.alignment = .centerY

        let stack = NSStackView(views: [summary, timeline, note, transport])
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
        showClock(0)
    }

    /// Virhe näkyy samassa paikassa kuin muukin: esikatselupaneelissa ei ole
    /// mihin avata valintaikkuna, ja tyhjä paneeli ei kerro mitään.
    public func show(error: Error) {
        stop()
        mix = nil
        summary.stringValue = "Istuntoa ei voi lukea"
        note.stringValue = "\(error)"
        playButton.isEnabled = false
        clockLabel.stringValue = ""
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

    /// Soitin syntyy vasta kun sitä tarvitaan, ja **säilyy** sen jälkeen.
    ///
    /// Aiemmin jokainen painallus loi uuden ja `stop()` heitti sen pois,
    /// mikä riitti kun säätimiä oli yksi. Tauko ja kelaus tarvitsevat
    /// saman soittimen: kohta on sen tiedossa, ja graafin purkaminen
    /// välissä avaisi tiedostot uudestaan joka kelauksella.
    private func ensurePlayer() -> MixPlayer? {
        if let player { return player }
        guard let mix else { return nil }
        let fresh = MixPlayer(mix: mix)
        do {
            try fresh.prepare()
        } catch {
            note.stringValue = "\(error)"
            return nil
        }
        player = fresh
        return fresh
    }

    @objc private func togglePlay() {
        guard let player = ensurePlayer() else { return }
        if player.isPlaying {
            player.pause()
            stopTicking()
            showTransport()
            return
        }
        if player.isPaused {
            player.resume()
        } else {
            player.play()
        }
        // Lähde, joka ei auennut, kerrotaan heti eikä jätetä
        // hiljaisuudeksi jolle ei ole selitystä.
        if !player.unreadable.isEmpty {
            note.stringValue = "ei auennut: " + player.unreadable.map(\.described).joined(separator: ", ")
        }
        startTicking()
        showTransport()
    }

    /// Raahauksen aikana: vain osoitin ja kello, ei ääntä.
    private func previewScrub(to time: Double) {
        isScrubbing = true
        timeline.playhead = time
        showClock(time)
    }

    /// Kelaus aikajanalta, kun nappi nousee. Toimii myös ennen ensimmäistä
    /// soittoa: osoitin siirtyy, ja soitto alkaa siitä mihin osoitettiin.
    private func seek(to time: Double) {
        isScrubbing = false
        guard let player = ensurePlayer() else {
            timeline.playhead = time
            showClock(time)
            return
        }
        player.seek(to: time)
        if player.isPlaying { startTicking() } else { stopTicking() }
        showTransport()
    }

    private func startTicking() {
        stopTicking()
        // 30 kertaa sekunnissa: osoitin liikkuu tasaisesti, eikä
        // uudelleenpiirto ole muuta kuin osoittimen kohta.
        let timer = Timer(timeInterval: 1.0 / 30.0, repeats: true) { [weak self] _ in
            self?.tick()
        }
        // `.common`: ilman tätä osoitin pysähtyisi valikon tai vierityksen
        // ajaksi, vaikka ääni jatkaa.
        RunLoop.main.add(timer, forMode: .common)
        ticker = timer
    }

    private func stopTicking() {
        ticker?.invalidate()
        ticker = nil
    }

    private func tick() {
        guard let player, !isScrubbing else { return }
        if player.hasReachedEnd {
            player.stop()
            stopTicking()
            timeline.playhead = 0
            showTransport()
            return
        }
        showTransport()
    }

    private func showTransport() {
        let at = player?.currentTime ?? 0
        timeline.playhead = at
        showClock(at)
        set(title: player?.isPlaying == true ? "Tauko" : "Soita")
    }

    /// Kello ja napin teksti kirjoitetaan vain kun ne muuttuvat.
    ///
    /// Tätä kutsutaan 30 kertaa sekunnissa. Saman arvon sijoittaminen
    /// `NSTextField`iin ei ole ilmaista — se pyytää asettelun joka kerta —
    /// ja kello vaihtuu kerran sekunnissa, nappi harvemmin.
    private func showClock(_ at: Double) {
        guard let mix else {
            if !clockLabel.stringValue.isEmpty { clockLabel.stringValue = "" }
            return
        }
        let text = "\(Self.clock(at)) / \(Self.clock(mix.duration))"
        if clockLabel.stringValue != text { clockLabel.stringValue = text }
    }

    private func set(title: String) {
        if playButton.title != title { playButton.title = title }
    }

    /// Pysäyttää toiston. Ikkunan sulkeminen ja esikatselun vaihtuminen
    /// kutsuvat tätä — muuten ääni jatkuisi näkymän jälkeen.
    public func stop() {
        stopTicking()
        player?.stop()
        player = nil
        playButton.title = "Soita"
        timeline.playhead = 0
    }

    deinit {
        ticker?.invalidate()
        player?.stop()
    }
}
