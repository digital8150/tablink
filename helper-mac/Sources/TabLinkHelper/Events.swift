import Foundation

final class EventSink {
    private let queue = DispatchQueue(label: "tablink.events")
    private let output: FileHandle

    init() {
        output = FileHandle.standardOutput
    }

    func emit(_ object: [String: Any]) {
        queue.async { [output] in
            do {
                let data = try JSONSerialization.data(withJSONObject: object, options: [])
                var line = data
                line.append(0x0A)
                try output.write(contentsOf: line)
            } catch {
                // stdout failures are terminal for the parent protocol; keep diagnostics off stdout.
                FileHandle.standardError.write(Data(("event output failed: \(error)\n").utf8))
            }
        }
    }

    func log(_ message: String) {
        emit(["ev": "log", "msg": message])
    }

    func flush() {
        queue.sync { }
    }
}

extension EventSink {
    func ready() { emit(["ev": "ready"]) }

    func active(_ value: Bool) { emit(["ev": "active", "value": value]) }

    func ctrl(_ state: String, serial: String? = nil, message: String? = nil) {
        var object: [String: Any] = ["ev": "ctrl", "state": state]
        if let serial { object["serial"] = serial }
        if let message { object["message"] = message }
        emit(object)
    }

    func audio(_ state: String, code: Int32? = nil, message: String? = nil) {
        var object: [String: Any] = ["ev": "audio", "state": state]
        if let code { object["code"] = Int(code) }
        if let message { object["message"] = message }
        emit(object)
    }

    func info(_ info: TabletInfo) {
        emit([
            "ev": "info",
            "width": info.width,
            "height": info.height,
            "gainX": info.gainX,
            "gainY": info.gainY,
            "linear": info.linear
        ])
    }
}
