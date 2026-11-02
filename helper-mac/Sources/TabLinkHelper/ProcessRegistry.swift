import Foundation
import Darwin

/// Holds pipe output produced on a background thread.
private final class DataBox {
    var data = Data()
}

final class ProcessRegistry {
    private let lock = NSLock()
    private var processes: [ObjectIdentifier: Process] = [:]

    func register(_ process: Process) {
        lock.lock()
        processes[ObjectIdentifier(process)] = process
        lock.unlock()
    }

    func unregister(_ process: Process) {
        lock.lock()
        processes.removeValue(forKey: ObjectIdentifier(process))
        lock.unlock()
    }

    @discardableResult
    func run(_ path: String, arguments: [String], timeout: TimeInterval) throws -> (stdout: Data, stderr: Data, code: Int32) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: path)
        process.arguments = arguments
        process.standardInput = FileHandle.nullDevice
        let output = Pipe()
        let error = Pipe()
        process.standardOutput = output
        process.standardError = error
        try process.run()
        register(process)

        // Drain both pipes while the child runs. Reading only after exit deadlocks
        // once the child fills the ~64 KB pipe buffer (e.g. `dumpsys input` is ~130 KB).
        let stdoutBox = DataBox(), stderrBox = DataBox()
        let drained = DispatchGroup()
        drained.enter()
        DispatchQueue.global().async {
            stdoutBox.data = output.fileHandleForReading.readDataToEndOfFile()
            drained.leave()
        }
        drained.enter()
        DispatchQueue.global().async {
            stderrBox.data = error.fileHandleForReading.readDataToEndOfFile()
            drained.leave()
        }

        let deadline = Date().addingTimeInterval(timeout)
        while process.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.02)
        }
        if process.isRunning {
            process.terminate()
            let killDeadline = Date().addingTimeInterval(0.5)
            while process.isRunning && Date() < killDeadline {
                Thread.sleep(forTimeInterval: 0.02)
            }
            if process.isRunning {
                Darwin.kill(process.processIdentifier, SIGKILL)
            }
            process.waitUntilExit()
            drained.wait()
            unregister(process)
            throw NSError(domain: "TabLinkHelper", code: 1, userInfo: [NSLocalizedDescriptionKey: "Process timed out: \(path)"])
        }

        drained.wait()
        let code = process.terminationStatus
        unregister(process)
        return (stdoutBox.data, stderrBox.data, code)
    }

    func stopAll() {
        lock.lock()
        let current = Array(processes.values)
        lock.unlock()

        for process in current where process.isRunning {
            process.terminate()
        }
        let deadline = Date().addingTimeInterval(0.75)
        while Date() < deadline {
            if current.allSatisfy({ !$0.isRunning }) { break }
            Thread.sleep(forTimeInterval: 0.02)
        }
        for process in current where process.isRunning {
            Darwin.kill(process.processIdentifier, SIGKILL)
        }
        for process in current where process.isRunning {
            process.waitUntilExit()
        }
        lock.lock()
        processes.removeAll()
        lock.unlock()
    }
}
