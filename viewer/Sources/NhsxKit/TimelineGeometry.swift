import Foundation

/// Aikajanan vaakageometria: sekunnit pisteiksi ja pisteet sekunneiksi.
///
/// **Yksi rakenne kahdelle kutsujalle**, piirrolle ja hiirelle. Sama syy
/// kuin `fitFades`illa: sääntö, joka on kerrottava jokaiselle kutsujalle
/// erikseen, on sääntö jota joku kutsuja ei noudata.
///
/// Jos piirto ja osumatesti laskisivat x:n eri kaavalla, palkit näkyisivät
/// oikeilla paikoilla ja klikkaus osuisi väärään kohtaan. Kumpikaan puoli
/// ei näyttäisi yksinään väärältä — vika olisi vain siinä, että toisto
/// alkaa eri kohdasta kuin mihin osoitettiin, ja sen huomaa vasta
/// kuuntelemalla. Siksi kaava on täällä eikä näkymässä, ja siksi sillä on
/// testit: `NhsxViewer` on AppKitiä eikä sitä aja mikään testi.
public struct TimelineGeometry: Equatable {

    /// Raidan nimen sarake vasemmalla. Piirto varaa saman.
    public static let labelWidth: Double = 90

    /// Oikea marginaali, jottei viimeinen palkki liimaudu reunaan.
    public static let rightInset: Double = 8

    public let plotStart: Double
    public let plotWidth: Double
    public let duration: Double

    public init(viewWidth: Double, duration: Double) {
        plotStart = TimelineGeometry.labelWidth
        // Vähintään yksi piste: nollalla jaettaisiin `time(atX:)`ssä.
        plotWidth = max(1, viewWidth - TimelineGeometry.labelWidth - TimelineGeometry.rightInset)
        // Sama alaraja kuin `TimelineView`in piirrossa: tyhjä istunto ei
        // saa tuottaa nollajakoa.
        self.duration = max(duration, 0.001)
    }

    /// Ohjelma-aika vaakapisteeksi näkymän koordinaateissa.
    public func x(forTime time: Double) -> Double {
        plotStart + plotWidth * (clamped(time) / duration)
    }

    /// Vaakapiste ohjelma-ajaksi.
    ///
    /// Nimisarakkeen kohdalta klikkaus on nolla eikä negatiivinen, ja
    /// oikean reunan takaa kesto eikä sen yli: kelaus ei saa viedä
    /// jakson ulkopuolelle.
    public func time(atX x: Double) -> Double {
        clamped(x / plotWidth * duration)   // MUTAATIO: nimisarake unohdettu
    }

    private func clamped(_ time: Double) -> Double {
        min(max(time, 0), duration)
    }
}
