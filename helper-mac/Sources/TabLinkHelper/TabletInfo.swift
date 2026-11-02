import Foundation

struct TabletInfo: Equatable {
    var width: Int = 2960
    var height: Int = 1848
    var gainX: Double = 1.786
    var gainY: Double = 1.786
    var linear: Bool = true
}

enum TabletInfoQuery {
    static func query(registry: ProcessRegistry, adb: String, serial: String) throws -> TabletInfo {
        let result = try registry.run(adb, arguments: ["-s", serial, "shell", "dumpsys", "input"], timeout: 10)
        guard result.code == 0 else {
            let detail = String(data: result.stderr.isEmpty ? result.stdout : result.stderr, encoding: .utf8) ?? "adb failed"
            throw helperError(detail.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        let output = String(decoding: result.stdout, as: UTF8.self)
        var info = TabletInfo()
        if let groups = match(output, pattern: #"displayId=0,.*?logicalFrame=\[(-?\d+), (-?\d+), (\d+), (\d+)\]"#) {
            if let left = Int(groups[1]), let top = Int(groups[2]), let right = Int(groups[3]), let bottom = Int(groups[4]) {
                info.width = right - left
                info.height = bottom - top
            }
        }

        let inputStart = output.range(of: "Input Reader State")?.lowerBound ?? output.startIndex
        let rest = String(output[inputStart...])
        guard let mouseStart = rest.range(of: ": Multi Control Mouse\n") else { return info }
        let section = String(rest[mouseStart.lowerBound...].prefix(4000))
        let sx = match(section, pattern: #"XScale: ([\d.]+)"#)?[1]
        let sy = match(section, pattern: #"YScale: ([\d.]+)"#)?[1]
        let curveGroups = allMatches(section, pattern: #"\{([^,]+), ([\d.]+), ([-\d.]+)\}"#)
        var gain = 1.0
        if let first = curveGroups.first, let value = Double(first[2]) { gain = value }
        if !curveGroups.isEmpty { info.linear = curveGroups.count == 1 }
        if let sx, let sy, let x = Double(sx), let y = Double(sy) {
            info.gainX = x * gain
            info.gainY = y * gain
        }
        return info
    }
}

private func match(_ string: String, pattern: String) -> [String]? {
    guard let expression = try? NSRegularExpression(pattern: pattern, options: [.dotMatchesLineSeparators]) else { return nil }
    let range = NSRange(string.startIndex..<string.endIndex, in: string)
    guard let result = expression.firstMatch(in: string, options: [], range: range) else { return nil }
    return (0..<result.numberOfRanges).compactMap { index in
        let group = result.range(at: index)
        guard group.location != NSNotFound, let swiftRange = Range(group, in: string) else { return nil }
        return String(string[swiftRange])
    }
}

private func allMatches(_ string: String, pattern: String) -> [[String]] {
    guard let expression = try? NSRegularExpression(pattern: pattern, options: []) else { return [] }
    let range = NSRange(string.startIndex..<string.endIndex, in: string)
    return expression.matches(in: string, options: [], range: range).map { result in
        (0..<result.numberOfRanges).compactMap { index in
            let group = result.range(at: index)
            guard group.location != NSNotFound, let swiftRange = Range(group, in: string) else { return nil }
            return String(string[swiftRange])
        }
    }
}

final class InfoPoller {
    private let registry: ProcessRegistry
    private let adb: String
    private let serial: String
    private let changed: (TabletInfo) -> Void
    private let stopSignal = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var stopped = false
    private var thread: Thread?

    init(registry: ProcessRegistry, adb: String, serial: String, changed: @escaping (TabletInfo) -> Void) {
        self.registry = registry
        self.adb = adb
        self.serial = serial
        self.changed = changed
        thread = Thread { [weak self] in self?.run() }
        if let thread {
            thread.name = "TabLink tablet info"
            thread.start()
        }
    }

    func stop() {
        lock.lock(); stopped = true; lock.unlock()
        stopSignal.signal()
        guard let thread else { return }
        while thread.isExecuting || thread.isFinished == false {
            if thread.isFinished { break }
            Thread.sleep(forTimeInterval: 0.01)
        }
    }

    private func run() {
        var previous: TabletInfo?
        while true {
            lock.lock(); let shouldStop = stopped; lock.unlock()
            if shouldStop { break }
            do {
                let info = try TabletInfoQuery.query(registry: registry, adb: adb, serial: serial)
                lock.lock(); let stillRunning = !stopped; lock.unlock()
                if stillRunning && info != previous {
                    previous = info
                    changed(info)
                }
            } catch {
                // A transient adb failure is retried on the next poll.
            }
            if stopSignal.wait(timeout: .now() + 3.0) == .success { break }
        }
    }
}
