// swift-tools-version: 5.9
import PackageDescription

// `NhsxKit` on tarkoituksella **SwiftPM-kirjasto eikä Xcode-kohde**.
//
// Se osa esikatselusta, jonka on oltava samaa mieltä Pythonin kanssa — .nhsx:n
// jäsennys ja miksauksen päättely — kääntyy ja testautuu `swift test`illä
// ilman Xcodea. Vain laajennus ja sitä kantava sovellus tarvitsevat
// Xcode-projektin, koska macOS-laajennus on paketti eikä kirjasto.
//
// Jako on tämä siksi, että CI voi ajaa yhdenmukaisuustestin ilman
// Xcode-ajuria ja koko sovelluskehystä.
let package = Package(
    name: "NhsxKit",
    platforms: [.macOS(.v12)],
    products: [
        .library(name: "NhsxKit", targets: ["NhsxKit"]),
    ],
    targets: [
        .target(name: "NhsxKit"),
        .testTarget(name: "NhsxKitTests", dependencies: ["NhsxKit"]),
    ]
)
