import Foundation
import Darwin

private final class WeakBox<T: AnyObject> {
    weak var value: T?
}

private final class SignalCoordinator {
    static let shared = SignalCoordinator()
    private let lock = NSLock()
    private var cleanup: (() -> Void)?

    func install(_ action: @escaping () -> Void) {
        lock.lock(); cleanup = action; lock.unlock()
        signal(SIGTERM, tablinkSignalHandler)
        signal(SIGINT, tablinkSignalHandler)
    }

    func runCleanup() {
        lock.lock(); let action = cleanup; cleanup = nil; lock.unlock()
        action?()
    }
}

private func tablinkSignalHandler(_ signalNumber: Int32) {
    SignalCoordinator.shared.runCleanup()
    _exit(0)
}

private final class HelperRuntime {
    private let sink = EventSink()
    private let registry = ProcessRegistry()
    private let clipboard = ClipboardService()
    private let commandQueue = DispatchQueue(label: "tablink.commands")
    private let finished = DispatchSemaphore(value: 0)
    private let stateLock = NSLock()

    private let hook: InputHook
    private let multiControl: MultiControl
    private let audio: AudioProcess
    private var control: ScrcpyControl?
    private var poller: InfoPoller?
    private var serial: String?
    private var shuttingDown = false

    init() {
        let box = WeakBox<MultiControl>()
        let inputHook = InputHook(sink: sink)
        let mc = MultiControl(hook: inputHook, sink: sink, clipboardService: clipboard)
        box.value = mc
        inputHook.onMouse = { [box] type, event in box.value?.mouse(type: type, event: event) ?? false }
        inputHook.onKey = { [box] type, event in box.value?.key(type: type, event: event) ?? false }
        inputHook.onDisplayChange = { [box] in box.value?.refreshMonitors() }
        hook = inputHook
        multiControl = mc
        audio = AudioProcess(registry: registry, sink: sink)
    }

    func start() {
        SignalCoordinator.shared.install { [weak self] in self?.shutdown() }
        MonitorService.start { [weak self] in self?.multiControl.refreshMonitors() }
        multiControl.start()
        sink.ready()
        multiControl.refreshMonitors()
        let stdinThread = Thread { [weak self] in self?.readCommands() }
        stdinThread.name = "TabLink stdin"
        stdinThread.start()
        _ = finished.wait(timeout: .distantFuture)
    }

    private func readCommands() {
        while let line = readLine(strippingNewline: true) {
            if line.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { continue }
            guard let data = line.data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: data, options: []),
                  let command = object as? [String: Any] else {
                sink.log("Malformed command line")
                continue
            }
            handle(command)
            stateLock.lock(); let done = shuttingDown; stateLock.unlock()
            if done { return }
        }
        shutdown()
    }

    private func handle(_ command: [String: Any]) {
        guard let name = command["cmd"] as? String else {
            sink.log("Malformed command: missing cmd")
            return
        }
        switch name {
        case "config":
            multiControl.configure(command)
        case "monitors":
            multiControl.refreshMonitors()
        case "toggle":
            multiControl.toggle()
        case "detach":
            commandQueue.async { [weak self] in self?.detach(emit: true) }
        case "attach":
            guard let serial = command["serial"] as? String,
                  let adb = command["adb"] as? String,
                  let server = command["server"] as? String,
                  let version = command["version"] as? String,
                  !serial.isEmpty, !adb.isEmpty, !server.isEmpty, !version.isEmpty else {
                sink.ctrl("error", message: "attach requires serial, adb, server, and version")
                return
            }
            commandQueue.async { [weak self] in self?.attach(serial: serial, adb: adb, server: server, version: version) }
        case "audio":
            let serial = command["serial"] as? String
            let executable = command["scrcpy"] as? String
            let source = (command["source"] as? String) ?? "playback"
            let duplicate = (command["dup"] as? NSNumber)?.boolValue ?? false
            let buffer = (command["buffer"] as? NSNumber)?.intValue ?? 50
            let adb = command["adb"] as? String
            commandQueue.async { [weak self] in
                self?.audio.start(serial: serial, executable: executable, adb: adb, source: source, dup: duplicate, buffer: buffer)
            }
        case "quit":
            shutdown()
        default:
            sink.log("Unknown command: \(name)")
        }
    }

    private func attach(serial: String, adb: String, server: String, version: String) {
        detach(emit: false)
        self.serial = serial
        sink.ctrl("starting", serial: serial)
        let box = WeakBox<ScrcpyControl>()
        let candidate = ScrcpyControl(
            registry: registry,
            adb: adb,
            serial: serial,
            server: server,
            version: version,
            onClipboard: { [weak self] text in self?.multiControl.deviceClipboard(text) },
            onDead: { [weak self, box] in
                guard let self else { return }
                self.commandQueue.async {
                    guard let candidate = box.value, self.control === candidate else { return }
                    self.multiControl.setControl(nil)
                    self.sink.ctrl("dead", serial: serial)
                }
            }
        )
        box.value = candidate
        control = candidate
        do {
            try candidate.start()
            guard candidate.alive else { throw helperError("Control connection closed") }
            multiControl.setControl(candidate)
            sink.ctrl("alive", serial: serial)
            Thread.sleep(forTimeInterval: 0.3)
            poller = InfoPoller(registry: registry, adb: adb, serial: serial) { [weak self] info in
                self?.multiControl.updateInfo(info)
            }
        } catch {
            multiControl.setControl(nil)
            candidate.stop()
            control = nil
            sink.ctrl("error", serial: serial, message: error.localizedDescription)
        }
    }

    private func detach(emit: Bool) {
        let oldSerial = serial
        multiControl.setControl(nil)
        poller?.stop()
        poller = nil
        control?.stop()
        control = nil
        serial = nil
        if emit { sink.ctrl("off", serial: oldSerial) }
    }

    private func shutdown() {
        stateLock.lock()
        if shuttingDown { stateLock.unlock(); return }
        shuttingDown = true
        stateLock.unlock()

        commandQueue.sync { [weak self] in
            guard let self else { return }
            self.detach(emit: true)
            self.audio.stop()
        }
        multiControl.stop()
        MonitorService.stop()
        registry.stopAll()
        sink.flush()
        finished.signal()
    }
}

private let runtime = HelperRuntime()
runtime.start()
