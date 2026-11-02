import CoreGraphics
import Foundation

struct MonitorInfo {
    let left: Int
    let top: Int
    let right: Int
    let bottom: Int
    let primary: Bool
    let name: String

    var width: Int { right - left }
    var height: Int { bottom - top }
}

final class MonitorService {
    private static var callback: (() -> Void)?
    private static var registered = false

    private static let reconfiguration: CGDisplayReconfigurationCallBack = { _, _, _ in
        callback?()
    }

    static func start(_ changed: @escaping () -> Void) {
        callback = changed
        if !registered {
            CGDisplayRegisterReconfigurationCallback(reconfiguration, nil)
            registered = true
        }
    }

    static func stop() {
        if registered {
            CGDisplayRemoveReconfigurationCallback(reconfiguration, nil)
            registered = false
        }
        callback = nil
    }

    static func list() -> [MonitorInfo] {
        var count: UInt32 = 0
        guard CGGetActiveDisplayList(0, nil, &count) == .success, count > 0 else { return [] }
        var displays = Array(repeating: CGDirectDisplayID(0), count: Int(count))
        guard CGGetActiveDisplayList(count, &displays, &count) == .success else { return [] }
        let primary = CGMainDisplayID()
        let result = displays.map { display -> MonitorInfo in
            let bounds = CGDisplayBounds(display)
            return MonitorInfo(
                left: Int(bounds.minX.rounded()),
                top: Int(bounds.minY.rounded()),
                right: Int(bounds.maxX.rounded()),
                bottom: Int(bounds.maxY.rounded()),
                primary: display == primary,
                name: "Display \(display)"
            )
        }
        return result.sorted {
            if $0.primary != $1.primary { return $0.primary && !$1.primary }
            if $0.left != $1.left { return $0.left < $1.left }
            return $0.top < $1.top
        }
    }

    static func target(_ monitors: [MonitorInfo], index: Int, side: String) -> Int {
        if index >= 0 && index < monitors.count { return index }
        guard !monitors.isEmpty else { return -1 }
        var best = 0
        for i in 1..<monitors.count {
            let better: Bool
            switch side {
            case "left": better = monitors[i].left < monitors[best].left
            case "top": better = monitors[i].top < monitors[best].top
            case "bottom": better = monitors[i].bottom > monitors[best].bottom
            default: better = monitors[i].right > monitors[best].right
            }
            if better { best = i }
        }
        return best
    }

    static func emit(_ monitors: [MonitorInfo], target: Int, to sink: EventSink) {
        let list: [[String: Any]] = monitors.map {
            [
                "left": $0.left,
                "top": $0.top,
                "right": $0.right,
                "bottom": $0.bottom,
                "primary": $0.primary,
                "name": $0.name
            ]
        }
        sink.emit(["ev": "monitors", "list": list, "target": target])
    }
}
