// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "TabLinkHelper",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "TabLinkHelper", targets: ["TabLinkHelper"])
    ],
    targets: [
        .executableTarget(
            name: "TabLinkHelper",
            path: "Sources/TabLinkHelper",
            swiftSettings: [
                .unsafeFlags(["-gnone"], .when(configuration: .release))
            ]
        )
    ]
)
