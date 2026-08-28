import AppKit
import NhsxViewer
import Quartz

/// `.nhsx`-istunnon esikatselu Finderin välilyönnillä.
///
/// Tässä ei ole näkymää: se on `NhsxViewer.SessionView`, sama jonka
/// `NHSX Viewer.app` näyttää ikkunassaan. Tämä on vain kuori, joka antaa
/// sille tiedoston.
///
/// Laajennus on hiekkalaatikossa eikä voi käynnistää `nhsx-render`iä — siksi
/// `NhsxKit` jäsentää `.nhsx`:n uudestaan Swiftillä, ja siksi
/// `Conformance/` on olemassa pitämässä kaksi jäsennintä samaa mieltä.
public final class PreviewViewController: NSViewController, QLPreviewingController {

    private let session = SessionView(frame: NSRect(x: 0, y: 0, width: 720, height: 420))

    public override func loadView() {
        view = session
    }

    public func preparePreviewOfFile(at url: URL) async throws {
        try session.show(sessionAt: url.path)
    }

    /// Esikatselun vaihtuessa toisto loppuu. Ilman tätä ääni jatkuisi
    /// seuraavan tiedoston päällä.
    public override func viewWillDisappear() {
        super.viewWillDisappear()
        session.stop()
    }
}
