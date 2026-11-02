import Foundation
import Darwin

final class AudioProcess {
    private let registry: ProcessRegistry
    private let sink: EventSink
    private let lock = NSLock()
    private var process: Process?

    init(registry: ProcessRegistry, sink: EventSink) {
        self.registry = registry
        self.sink = sink
    }

    func stop() {
        lock.lock()
        let old = process
        process = nil
        lock.unlock()
        if let old {
            if old.isRunning { old.terminate() }
            let deadline = Date().addingTimeInterval(0.5)
            while old.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.02) }
            if old.isRunning { Darwin.kill(old.processIdentifier, SIGKILL) }
            if old.isRunning { old.waitUntilExit() }
            registry.unregister(old)
        }
        sink.audio("off")
    }

    func start(serial: String?, executable: String?, adb: String?, source: String, dup: Bool, buffer: Int) {
        stop()
        guard let serial, !serial.isEmpty else { return }
        guard let executable, !executable.isEmpty else {
            sink.audio("error", message: "Missing scrcpy path")
            return
        }
        var arguments = [
            "-s", serial, "--no-video", "--no-control", "--no-window", "--no-power-on",
            "--audio-buffer=\(buffer)", "--audio-source=\(source)"
        ]
        if source == "playback" && dup { arguments.append("--audio-dup") }

        let child = Process()
        child.executableURL = URL(fileURLWithPath: executable)
        child.arguments = arguments
        child.standardInput = FileHandle.nullDevice
        // scrcpy starts `adb` itself; GUI-launched apps have no Homebrew PATH, so pass the absolute path.
        var environment = ProcessInfo.processInfo.environment
        if let adb, !adb.isEmpty { environment["ADB"] = adb }
        environment["PATH"] = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", environment["PATH"] ?? ""]
            .joined(separator: ":")
        child.environment = environment
        let stdout = Pipe(); let stderr = Pipe()
        child.standardOutput = stdout; child.standardError = stderr
        do {
            try child.run()
            registry.register(child)
        } catch {
            sink.audio("error", message: error.localizedDescription)
            return
        }
        lock.lock(); process = child; lock.unlock()
        sink.audio("running")

        let pump: (Pipe) -> Void = { [weak self] pipe in
            var pending = Data()
            while true {
                let data = pipe.fileHandleForReading.availableData
                if data.isEmpty { break }
                pending.append(data)
                while let newline = pending.firstIndex(of: 0x0A) {
                    let lineData = pending.prefix(upTo: newline)
                    pending.removeSubrange(...newline)
                    self?.forwardAudioLine(Data(lineData))
                }
            }
            if !pending.isEmpty { self?.forwardAudioLine(pending) }
        }
        Thread { pump(stdout) }.start()
        Thread { pump(stderr) }.start()
        Thread { [weak self] in
            child.waitUntilExit()
            guard let self else { return }
            self.lock.lock()
            let same = self.process === child
            if same { self.process = nil }
            self.lock.unlock()
            self.registry.unregister(child)
            if same { self.sink.audio("stopped", code: child.terminationStatus) }
        }.start()
    }

    private func forwardAudioLine(_ data: Data) {
        let value = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        if value.contains("ERROR") || value.contains("WARN") { sink.log("scrcpy: \(value)") }
    }
}
