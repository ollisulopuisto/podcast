import AppKit
import NhsxKit

/// Istunnon aikajana: raita riviksi, alue palkiksi, toiston kohta viivaksi.
///
/// Vaimennetut alueet piirretään ääriviivalla eikä täytettynä. Ne ovat
/// vaimennuksen jälkeen suurin osa istunnosta, ja piilotettuina aikajana
/// näyttäisi tyhjältä siitä mitä tiedostossa oikeasti on.
public final class TimelineView: NSView {

    private struct Bar {
        let row: Int
        let start: Double
        let length: Double
        let muted: Bool
    }

    private var bars: [Bar] = []
    private var rows: [String] = []
    private var duration: Double = 0

    /// Kelaus on **kaksivaiheinen**, ja siihen on syy.
    ///
    /// Raahaus tuottaa kymmeniä tapahtumia sekunnissa. Jos jokainen niistä
    /// kelaisi oikeasti, jokainen myös ajastaisi koko miksauksen uudestaan
    /// — ja häivytetyt leikkeet luetaan puskuriin, eli se on levyluku.
    /// Raahaus muuttuisi nykimiseksi juuri siinä kohtaa jossa käyttäjä
    /// katsoo tarkkaan.
    ///
    /// Siksi raahatessa liikkuu vain osoitin (`onScrubPreview`), ja ääni
    /// kelataan vasta kun nappi nousee (`onScrub`).
    public var onScrubPreview: ((Double) -> Void)?
    public var onScrub: ((Double) -> Void)?

    /// Toiston kohta ohjelma-aikana.
    ///
    /// Asetus mitätöi **vain osoittimen kohdat**, ei koko näkymää. Kolmen
    /// tunnin istunnossa on satoja palkkeja, ja 30 kertaa sekunnissa
    /// piirretty koko aikajana olisi juuri sitä hitautta jonka takia
    /// esikatselu ei renderöi.
    public var playhead: Double = 0 {
        didSet {
            guard playhead != oldValue else { return }
            setNeedsDisplay(playheadRect(at: oldValue))
            setNeedsDisplay(playheadRect(at: playhead))
        }
    }

    public override var isFlipped: Bool { true }

    private var geometry: TimelineGeometry {
        TimelineGeometry(viewWidth: Double(bounds.width), duration: duration)
    }

    private func playheadRect(at time: Double) -> NSRect {
        let x = CGFloat(geometry.x(forTime: time))
        return NSRect(x: x - 2, y: 0, width: 5, height: bounds.height)
    }

    public func show(session: Session, mix: Mix) {
        rows = session.tracks.map { $0.name.isEmpty ? "(nimetön)" : $0.name }
        duration = max(mix.duration, 0.001)
        bars = []
        for (row, track) in session.tracks.enumerated() {
            for region in track.regions where region.length > 0 {
                bars.append(Bar(row: row, start: region.start, length: region.length,
                                muted: track.muted || region.muted))
            }
        }
        playhead = 0
        needsDisplay = true
    }

    // MARK: - Kelaus

    public override func mouseDown(with event: NSEvent) { report(event, onScrubPreview) }
    public override func mouseDragged(with event: NSEvent) { report(event, onScrubPreview) }
    public override func mouseUp(with event: NSEvent) { report(event, onScrub) }

    private func report(_ event: NSEvent, _ to: ((Double) -> Void)?) {
        guard !rows.isEmpty, let to else { return }
        let point = convert(event.locationInWindow, from: nil)
        to(geometry.time(atX: Double(point.x)))
    }

    // MARK: - Piirto

    public override func draw(_ dirty: NSRect) {
        // Vain likainen alue: osoittimen liikkuessa se on muutama piste.
        NSColor.textBackgroundColor.setFill()
        dirty.fill()
        guard !rows.isEmpty else { return }

        let g = geometry
        let plotStart = CGFloat(g.plotStart)
        let plotWidth = CGFloat(g.plotWidth)
        let rowHeight = min(34, max(18, (bounds.height - 8) / CGFloat(rows.count)))
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 11),
            .foregroundColor: NSColor.secondaryLabelColor,
        ]

        for (index, name) in rows.enumerated() {
            let y = 4 + CGFloat(index) * rowHeight
            name.draw(at: NSPoint(x: 6, y: y + rowHeight / 2 - 7), withAttributes: attributes)
            NSColor.separatorColor.withAlphaComponent(0.4).setFill()
            NSRect(x: plotStart, y: y + rowHeight / 2, width: plotWidth, height: 1).fill()
        }

        for bar in bars {
            let x = CGFloat(g.x(forTime: bar.start))
            let width = max(1.5, plotWidth * CGFloat(bar.length / g.duration))
            let y = 4 + CGFloat(bar.row) * rowHeight + rowHeight * 0.18
            let rect = NSRect(x: x, y: y, width: width, height: rowHeight * 0.64)
            // Likaisen alueen ulkopuolinen palkki on jo ruudulla.
            guard rect.intersects(dirty) else { continue }
            let path = NSBezierPath(roundedRect: rect, xRadius: 2, yRadius: 2)
            if bar.muted {
                NSColor.tertiaryLabelColor.setStroke()
                path.lineWidth = 1
                path.stroke()
            } else {
                NSColor.controlAccentColor.setFill()
                path.fill()
            }
        }

        // Osoitin viimeisenä, jotta se on palkkien päällä.
        let head = NSRect(x: CGFloat(g.x(forTime: playhead)), y: 0, width: 1, height: bounds.height)
        if head.intersects(dirty) {
            NSColor.labelColor.setFill()
            head.fill()
        }
    }
}
