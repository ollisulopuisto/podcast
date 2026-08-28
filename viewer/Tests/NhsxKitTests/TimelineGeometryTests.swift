import XCTest
@testable import NhsxKit

/// Kelauksen geometria on ainoa osa toistosäätimiä jonka voi testata:
/// `NhsxViewer` on AppKitiä, eikä sitä aja mikään testi. Siksi kaava on
/// `NhsxKit`issä ja siksi se testataan täällä.
final class TimelineGeometryTests: XCTestCase {

    private let width: Double = 890   // 90 nimisaraketta + 792 kuvaa + 8 marginaali
    private let duration: Double = 100

    private var geometry: TimelineGeometry {
        TimelineGeometry(viewWidth: width, duration: duration)
    }

    func testTheStartOfTheSessionSitsAtTheStartOfThePlot() {
        XCTAssertEqual(geometry.x(forTime: 0), TimelineGeometry.labelWidth, accuracy: 1e-9)
    }

    func testTheEndOfTheSessionSitsAtTheEndOfThePlot() {
        let g = geometry
        XCTAssertEqual(g.x(forTime: duration), g.plotStart + g.plotWidth, accuracy: 1e-9)
    }

    func testTheMiddleIsInTheMiddle() {
        let g = geometry
        XCTAssertEqual(g.x(forTime: 50), g.plotStart + g.plotWidth / 2, accuracy: 1e-9)
    }

    /// Se, mitä varten koko rakenne on: piirto ja osumatesti ovat sama kaava.
    func testTimeSurvivesTheRoundTrip() {
        let g = geometry
        for time in [0.0, 0.5, 1.0, 33.3, 50.0, 99.5, 100.0] {
            XCTAssertEqual(g.time(atX: g.x(forTime: time)), time, accuracy: 1e-9,
                           "aika \(time) ei selvinnyt edestakaisin")
        }
    }

    func testAClickOnTheNameColumnIsTheStartNotBeforeIt() {
        // Nimisarake on kuvan vasemmalla puolella: siellä klikkaus on 0,
        // ei negatiivinen aika, jota `play(from:)` ei osaisi.
        XCTAssertEqual(geometry.time(atX: 0), 0, accuracy: 1e-9)
        XCTAssertEqual(geometry.time(atX: 45), 0, accuracy: 1e-9)
    }

    func testAClickPastTheRightEdgeIsTheDurationNotBeyondIt() {
        XCTAssertEqual(geometry.time(atX: width + 500), duration, accuracy: 1e-9)
    }

    func testTheLabelColumnIsNotCountedTwice() {
        // Suora regressio: jos `time(atX:)` unohtaisi vähentää
        // nimisarakkeen, kuvan alku osuisi noin 11 sekuntiin sadan
        // sekunnin istunnossa — palkit näyttäisivät oikeilta ja toisto
        // alkaisi väärästä kohdasta.
        let g = geometry
        XCTAssertEqual(g.time(atX: g.plotStart), 0, accuracy: 1e-9)
    }

    func testAZeroLengthSessionDoesNotDivideByZero() {
        let g = TimelineGeometry(viewWidth: width, duration: 0)
        XCTAssertTrue(g.x(forTime: 0).isFinite)
        XCTAssertTrue(g.time(atX: 500).isFinite)
    }

    func testANarrowViewStillHasAPlot() {
        // Esikatselupaneeli voi olla kapeampi kuin nimisarake.
        let g = TimelineGeometry(viewWidth: 20, duration: duration)
        XCTAssertGreaterThanOrEqual(g.plotWidth, 1)
        XCTAssertTrue(g.time(atX: 10).isFinite)
    }
}
