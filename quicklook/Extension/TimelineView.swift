import AppKit
import NhsxKit

/// Istunnon aikajana: raita riviksi, alue palkiksi.
///
/// Vaimennetut alueet piirretään ääriviivalla eikä täytettynä. Ne ovat
/// vaimennuksen jälkeen suurin osa istunnosta, ja piilotettuina aikajana
/// näyttäisi tyhjältä siitä mitä tiedostossa oikeasti on.
final class TimelineView: NSView {

    private struct Bar {
        let row: Int
        let start: Double
        let length: Double
        let muted: Bool
    }

    private var bars: [Bar] = []
    private var rows: [String] = []
    private var duration: Double = 0

    override var isFlipped: Bool { true }

    func show(session: Session, mix: Mix) {
        rows = session.tracks.map { $0.name.isEmpty ? "(nimetön)" : $0.name }
        duration = max(mix.duration, 0.001)
        bars = []
        for (row, track) in session.tracks.enumerated() {
            for region in track.regions where region.length > 0 {
                bars.append(Bar(row: row, start: region.start, length: region.length,
                                muted: track.muted || region.muted))
            }
        }
        needsDisplay = true
    }

    override func draw(_ dirty: NSRect) {
        NSColor.textBackgroundColor.setFill()
        bounds.fill()
        guard !rows.isEmpty else { return }

        let labelWidth: CGFloat = 90
        let rowHeight = min(34, max(18, (bounds.height - 8) / CGFloat(rows.count)))
        let plot = NSRect(x: labelWidth, y: 0,
                          width: max(1, bounds.width - labelWidth - 8), height: bounds.height)
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 11),
            .foregroundColor: NSColor.secondaryLabelColor,
        ]

        for (index, name) in rows.enumerated() {
            let y = 4 + CGFloat(index) * rowHeight
            name.draw(at: NSPoint(x: 6, y: y + rowHeight / 2 - 7), withAttributes: attributes)
            NSColor.separatorColor.withAlphaComponent(0.4).setFill()
            NSRect(x: plot.minX, y: y + rowHeight / 2, width: plot.width, height: 1).fill()
        }

        for bar in bars {
            let x = plot.minX + plot.width * CGFloat(bar.start / duration)
            let width = max(1.5, plot.width * CGFloat(bar.length / duration))
            let y = 4 + CGFloat(bar.row) * rowHeight + rowHeight * 0.18
            let rect = NSRect(x: x, y: y, width: width, height: rowHeight * 0.64)
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
    }
}
