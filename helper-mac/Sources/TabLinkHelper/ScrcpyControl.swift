import Darwin
import Foundation

private let mouseDescriptor: [UInt8] = [
    0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x09, 0x01, 0xA1, 0x00,
    0x05, 0x09, 0x19, 0x01, 0x29, 0x05, 0x15, 0x00, 0x25, 0x01,
    0x95, 0x05, 0x75, 0x01, 0x81, 0x02, 0x95, 0x01, 0x75, 0x03,
    0x81, 0x01, 0x05, 0x01, 0x09, 0x30, 0x09, 0x31, 0x16, 0x01,
    0x80, 0x26, 0xFF, 0x7F, 0x75, 0x10, 0x95, 0x02, 0x81, 0x06,
    0x09, 0x38, 0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x01,
    0x81, 0x06, 0x05, 0x0C, 0x0A, 0x38, 0x02, 0x15, 0x81, 0x25,
    0x7F, 0x75, 0x08, 0x95, 0x01, 0x81, 0x06, 0xC0, 0xC0
]

private let keyboardDescriptor: [UInt8] = [
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x05, 0x07, 0x19, 0xE0,
    0x29, 0xE7, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x08,
    0x81, 0x02, 0x75, 0x08, 0x95, 0x01, 0x81, 0x01, 0x05, 0x08,
    0x19, 0x01, 0x29, 0x05, 0x75, 0x01, 0x95, 0x05, 0x91, 0x02,
    0x75, 0x03, 0x95, 0x01, 0x91, 0x01, 0x05, 0x07, 0x19, 0x00,
    0x29, 0xE7, 0x15, 0x00, 0x26, 0xE7, 0x00, 0x75, 0x08, 0x95,
    0x06, 0x81, 0x00, 0xC0
]

final class ScrcpyControl {
    private struct Packet {
        var data: [UInt8]
        let mouse: Bool
        let buttons: Int
        let x: Int
        let y: Int
        let merge: Bool
    }

    private let registry: ProcessRegistry
    private let adb: String
    let serial: String
    private let server: String
    private let version: String
    private let onClipboard: (String) -> Void
    private let onDead: () -> Void

    private let queueLock = NSLock()
    private var queue: [Packet] = []
    private let queueSignal = DispatchSemaphore(value: 0)
    private var queueClosed = false
    private var lastButtons = 0

    private let socketLock = NSLock()
    private var socketFD: Int32 = -1
    private var process: Process?
    private var port: Int32 = 0
    private var sequence: UInt64 = 1
    private var sender: Thread?
    private var reader: Thread?
    private var stopping = false
    private var deadReported = false
    private let lifecycleLock = NSLock()
    private var aliveValue = false

    var alive: Bool {
        lifecycleLock.lock()
        let value = aliveValue
        lifecycleLock.unlock()
        return value
    }

    init(registry: ProcessRegistry, adb: String, serial: String, server: String, version: String,
         onClipboard: @escaping (String) -> Void, onDead: @escaping () -> Void) {
        self.registry = registry
        self.adb = adb
        self.serial = serial
        self.server = server
        self.version = version
        self.onClipboard = onClipboard
        self.onDead = onDead
    }

    func start() throws {
        _ = try runADB(["push", server, "/data/local/tmp/scrcpy-server-tablink.jar"], timeout: 30)
        let scid = UInt32.random(in: 0...0x7FFF_FFFF)
        let id = String(format: "%08x", scid)
        let forward = try runADB(["forward", "tcp:0", "localabstract:scrcpy_\(id)"], timeout: 15)
        guard let forwardText = String(data: forward.stdout, encoding: .utf8),
              let parsedPort = Int32(forwardText.trimmingCharacters(in: .whitespacesAndNewlines)),
              parsedPort > 0 else {
            throw helperError("adb forward returned an invalid port")
        }
        port = parsedPort

        let child = Process()
        child.executableURL = URL(fileURLWithPath: adb)
        child.arguments = [
            "-s", serial, "shell", "CLASSPATH=/data/local/tmp/scrcpy-server-tablink.jar",
            "app_process", "/", "com.genymobile.scrcpy.Server", version,
            "scid=\(id)", "log_level=warn", "video=false", "audio=false", "control=true",
            "tunnel_forward=true", "clipboard_autosync=true", "power_on=false", "cleanup=false"
        ]
        child.standardInput = FileHandle.nullDevice
        child.standardOutput = FileHandle.nullDevice
        child.standardError = FileHandle.nullDevice
        try child.run()
        process = child
        registry.register(child)

        let deadline = Date().addingTimeInterval(10)
        var fd: Int32 = -1
        while Date() < deadline {
            if !child.isRunning { break }
            if let candidate = try? connectSocket(port: parsedPort), candidate >= 0 {
                fd = candidate
                if setReceiveTimeout(fd, seconds: 2), let dummy = readSocketExact(fd, count: 1), dummy.first == 0,
                   let _ = readSocketExact(fd, count: 64) {
                    break
                }
                close(candidate)
                fd = -1
            }
            Thread.sleep(forTimeInterval: 0.2)
        }
        guard fd >= 0 else {
            stop()
            throw helperError("scrcpy server failed to start")
        }

        socketLock.lock()
        socketFD = fd
        socketLock.unlock()
        _ = setReceiveTimeout(fd, seconds: 0)
        _ = setNoDelay(fd)
        setAlive(true)
        lifecycleLock.lock()
        stopping = false
        deadReported = false
        lifecycleLock.unlock()
        queueLock.lock()
        queueClosed = false
        queue.removeAll(keepingCapacity: true)
        queueLock.unlock()

        let sendThread = Thread { [weak self] in self?.sendLoop() }
        sendThread.name = "TabLink control sender"
        sender = sendThread
        sendThread.start()
        let readThread = Thread { [weak self] in self?.readLoop() }
        readThread.name = "TabLink control reader"
        reader = readThread
        readThread.start()
        create(id: 2, name: "Multi Control Mouse", descriptor: mouseDescriptor)
        create(id: 1, name: "Multi Control Keyboard", descriptor: keyboardDescriptor)
    }

    func mouse(x: Int = 0, y: Int = 0, buttons: Int = 0, wheel: Int = 0, hwheel: Int = 0, barrier: Bool = false) {
        let cx = max(-32767, min(32767, x))
        let cy = max(-32767, min(32767, y))
        let cw = max(-127, min(127, wheel))
        let ch = max(-127, min(127, hwheel))
        queueLock.lock()
        let merge = !barrier && buttons == lastButtons && cw == 0 && ch == 0
        lastButtons = buttons
        let packet = makeMouse(x: cx, y: cy, buttons: buttons, wheel: cw, hwheel: ch, merge: merge)
        enqueueLocked(packet)
        queueLock.unlock()
    }

    func keyboard(modifiers: Int, keys: [Int]) {
        var data = header(type: 13, id: 1, size: 8)
        data.append(UInt8(truncatingIfNeeded: modifiers))
        data.append(0)
        for key in keys.prefix(6) { data.append(UInt8(truncatingIfNeeded: key)) }
        while data.count < 13 { data.append(0) }
        enqueue(Packet(data: data, mouse: false, buttons: 0, x: 0, y: 0, merge: false))
    }

    func setClipboard(_ text: String) {
        let raw = Array(text.utf8.prefix((1 << 18) - 14))
        sequence &+= 1
        var data: [UInt8] = [9]
        data.append(contentsOf: bigEndian(sequence))
        data.append(0)
        data.append(contentsOf: bigEndian(UInt32(raw.count)))
        data.append(contentsOf: raw)
        enqueue(Packet(data: data, mouse: false, buttons: 0, x: 0, y: 0, merge: false))
    }

    func stop() {
        socketLock.lock()
        let fd = socketFD
        socketLock.unlock()
        lifecycleLock.lock(); stopping = true; lifecycleLock.unlock()
        setAlive(false)

        if fd >= 0 {
            keyboard(modifiers: 0, keys: [])
            mouse(barrier: true)
            enqueue(Packet(data: [14, 0, 2], mouse: false, buttons: 0, x: 0, y: 0, merge: false))
            enqueue(Packet(data: [14, 0, 1], mouse: false, buttons: 0, x: 0, y: 0, merge: false))
            queueLock.lock()
            queueClosed = true
            queueLock.unlock()
            queueSignal.signal()
            waitForThread(sender, timeout: 1.0)
            Darwin.shutdown(fd, SHUT_RDWR)
            close(fd)
            socketLock.lock()
            socketFD = -1
            socketLock.unlock()
        } else {
            queueLock.lock()
            queueClosed = true
            queue.removeAll()
            queueLock.unlock()
        }

        waitForThread(reader, timeout: 0.5)
        if let process {
            if process.isRunning { process.terminate() }
            let deadline = Date().addingTimeInterval(0.5)
            while process.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.02) }
            if process.isRunning { Darwin.kill(process.processIdentifier, SIGKILL) }
            if process.isRunning { process.waitUntilExit() }
            registry.unregister(process)
            self.process = nil
        }
        if port > 0 {
            _ = try? runADB(["forward", "--remove", "tcp:\(port)"], timeout: 15)
            port = 0
        }
        sender = nil
        reader = nil
    }

    private func runADB(_ arguments: [String], timeout: TimeInterval) throws -> (stdout: Data, stderr: Data, code: Int32) {
        let result = try registry.run(adb, arguments: ["-s", serial] + arguments, timeout: timeout)
        guard result.code == 0 else {
            let detail = String(data: result.stderr.isEmpty ? result.stdout : result.stderr, encoding: .utf8) ?? "adb failed"
            throw helperError("adb \(arguments.joined(separator: " ")): \(detail.trimmingCharacters(in: .whitespacesAndNewlines))")
        }
        return result
    }

    private func enqueue(_ packet: Packet) {
        queueLock.lock()
        enqueueLocked(packet)
        queueLock.unlock()
    }

    private func enqueueLocked(_ packet: Packet) {
        guard !queueClosed else { return }
        queue.append(packet)
        queueSignal.signal()
    }

    private func sendLoop() {
        while true {
            _ = queueSignal.wait(timeout: .distantFuture)
            var current: Packet?
            queueLock.lock()
            if !queue.isEmpty { current = queue.removeFirst() }
            let done = current == nil && queueClosed
            queueLock.unlock()
            if done { break }
            guard var packet = current else { continue }

            if packet.mouse && packet.merge {
                var x = packet.x
                var y = packet.y
                while true {
                    queueLock.lock()
                    guard let next = queue.first else {
                        queueLock.unlock()
                        break
                    }
                    guard next.mouse && next.merge && next.buttons == packet.buttons else {
                        queueLock.unlock()
                        break
                    }
                    queue.removeFirst()
                    queueLock.unlock()
                    x = max(-32767, min(32767, x + next.x))
                    y = max(-32767, min(32767, y + next.y))
                }
                packet = makeMouse(x: x, y: y, buttons: packet.buttons, wheel: 0, hwheel: 0, merge: true)
            }
            if let fd = currentSocket() { _ = sendAll(fd, data: packet.data) }
        }
    }

    private func readLoop() {
        do {
            while !isStopping() {
                guard let type = readByte() else { break }
                switch type {
                case 0:
                    guard let lengthData = readExact(count: 4) else { throw helperError("control clipboard length missing") }
                    let length = Int(readUInt32BE(lengthData))
                    guard length <= 16 * 1024 * 1024, let data = readExact(count: length) else {
                        throw helperError("invalid control clipboard message")
                    }
                    onClipboard(String(decoding: data, as: UTF8.self))
                case 1:
                    guard readExact(count: 8) != nil else { throw helperError("clipboard ack missing") }
                case 2:
                    guard let header = readExact(count: 4) else { throw helperError("UHID output header missing") }
                    let length = Int(UInt16(header[2]) << 8 | UInt16(header[3]))
                    guard readExact(count: length) != nil else { throw helperError("UHID output missing") }
                default:
                    throw helperError("unknown scrcpy device message")
                }
            }
        } catch {
            // Socket shutdown during a normal stop is expected.
        }
        setAlive(false)
        if !isStopping() && markDeadReported() {
            onDead()
        }
    }

    private func setAlive(_ value: Bool) {
        lifecycleLock.lock(); aliveValue = value; lifecycleLock.unlock()
    }

    private func isStopping() -> Bool {
        lifecycleLock.lock(); let value = stopping; lifecycleLock.unlock(); return value
    }

    private func markDeadReported() -> Bool {
        lifecycleLock.lock()
        let shouldReport = !deadReported
        deadReported = true
        lifecycleLock.unlock()
        return shouldReport
    }

    private func create(id: Int, name: String, descriptor: [UInt8]) {
        let nameBytes = Array(name.utf8)
        var data: [UInt8] = [12]
        data.append(contentsOf: bigEndian(UInt16(id)))
        data.append(contentsOf: [0, 0, 0, 0])
        data.append(UInt8(truncatingIfNeeded: nameBytes.count))
        data.append(contentsOf: nameBytes)
        data.append(contentsOf: bigEndian(UInt16(descriptor.count)))
        data.append(contentsOf: descriptor)
        enqueue(Packet(data: data, mouse: false, buttons: 0, x: 0, y: 0, merge: false))
    }

    private func header(type: UInt8, id: UInt16, size: UInt16) -> [UInt8] {
        [type, UInt8(id >> 8), UInt8(id & 0xFF), UInt8(size >> 8), UInt8(size & 0xFF)]
    }

    private func makeMouse(x: Int, y: Int, buttons: Int, wheel: Int, hwheel: Int, merge: Bool) -> Packet {
        var data = header(type: 13, id: 2, size: 7)
        data.append(UInt8(truncatingIfNeeded: buttons & 0x1F))
        data.append(contentsOf: littleEndian(Int16(max(-32767, min(32767, x)))))
        data.append(contentsOf: littleEndian(Int16(max(-32767, min(32767, y)))))
        data.append(UInt8(bitPattern: Int8(max(-127, min(127, wheel)))))
        data.append(UInt8(bitPattern: Int8(max(-127, min(127, hwheel)))))
        return Packet(data: data, mouse: true, buttons: buttons, x: x, y: y, merge: merge)
    }

    private func currentSocket() -> Int32? {
        socketLock.lock()
        let fd = socketFD
        socketLock.unlock()
        return fd >= 0 ? fd : nil
    }

    private func readByte() -> UInt8? {
        guard let data = readExact(count: 1) else { return nil }
        return data[0]
    }

    private func readExact(count: Int) -> [UInt8]? {
        guard count >= 0 else { return nil }
        var data = [UInt8](); data.reserveCapacity(count)
        while data.count < count {
            guard let fd = currentSocket() else { return nil }
            var buffer = [UInt8](repeating: 0, count: count - data.count)
            let result = buffer.withUnsafeMutableBytes { ptr in recv(fd, ptr.baseAddress, ptr.count, 0) }
            if result <= 0 { return nil }
            data.append(contentsOf: buffer.prefix(result))
        }
        return data
    }

}

private func waitForThread(_ thread: Thread?, timeout: TimeInterval) {
    guard let thread else { return }
    let deadline = Date().addingTimeInterval(timeout)
    while !thread.isFinished && Date() < deadline { Thread.sleep(forTimeInterval: 0.01) }
}

func helperError(_ message: String) -> NSError {
    NSError(domain: "TabLinkHelper", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
}

private func bigEndian<T: FixedWidthInteger>(_ value: T) -> [UInt8] {
    withUnsafeBytes(of: value.bigEndian) { Array($0) }
}

private func littleEndian<T: FixedWidthInteger>(_ value: T) -> [UInt8] {
    withUnsafeBytes(of: value.littleEndian) { Array($0) }
}

private func readUInt32BE(_ bytes: [UInt8]) -> UInt32 {
    guard bytes.count >= 4 else { return 0 }
    return UInt32(bytes[0]) << 24 | UInt32(bytes[1]) << 16 | UInt32(bytes[2]) << 8 | UInt32(bytes[3])
}

private func setNoDelay(_ fd: Int32) -> Bool {
    var value: Int32 = 1
    return withUnsafePointer(to: &value) {
        setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, $0, socklen_t(MemoryLayout<Int32>.size)) == 0
    }
}

private func setReceiveTimeout(_ fd: Int32, seconds: Int32) -> Bool {
    var timeout = timeval(tv_sec: Int(seconds), tv_usec: 0)
    return withUnsafePointer(to: &timeout) {
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, $0, socklen_t(MemoryLayout<timeval>.size)) == 0
    }
}

private func readSocketExact(_ fd: Int32, count: Int) -> [UInt8]? {
    guard count >= 0 else { return nil }
    var data = [UInt8](); data.reserveCapacity(count)
    while data.count < count {
        var buffer = [UInt8](repeating: 0, count: count - data.count)
        let result = buffer.withUnsafeMutableBytes { ptr in recv(fd, ptr.baseAddress, ptr.count, 0) }
        if result <= 0 { return nil }
        data.append(contentsOf: buffer.prefix(result))
    }
    return data
}

private func sendAll(_ fd: Int32, data: [UInt8]) -> Bool {
    var sent = 0
    while sent < data.count {
        let count = data.withUnsafeBytes { ptr in
            Darwin.send(fd, ptr.baseAddress?.advanced(by: sent), data.count - sent, 0)
        }
        if count <= 0 { return false }
        sent += count
    }
    return true
}

private func connectSocket(port: Int32) throws -> Int32 {
    let fd = socket(AF_INET, SOCK_STREAM, 0)
    guard fd >= 0 else { throw helperError("could not create control socket") }
    var address = sockaddr_in()
    address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
    address.sin_family = sa_family_t(AF_INET)
    address.sin_port = UInt16(truncatingIfNeeded: port).bigEndian
    _ = "127.0.0.1".withCString { inet_pton(AF_INET, $0, &address.sin_addr) }
    let result = withUnsafePointer(to: &address) { pointer in
        pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
    }
    guard result == 0 else {
        close(fd)
        throw helperError("control socket connect failed")
    }
    _ = setNoDelay(fd)
    return fd
}
