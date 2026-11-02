import CoreGraphics
import Foundation

final class InputHook {
    typealias MouseHandler = (_ type: CGEventType, _ event: CGEvent) -> Bool
    typealias KeyHandler = (_ type: CGEventType, _ event: CGEvent) -> Bool

    var onMouse: MouseHandler?
    var onKey: KeyHandler?
    var onDisplayChange: (() -> Void)?

    private let sink: EventSink
    private let ready = DispatchSemaphore(value: 0)
    private var runLoop: CFRunLoop?
    private var tap: CFMachPort?
    private let stateLock = NSLock()
    private var stopped = false

    init(sink: EventSink) {
        self.sink = sink
    }

    func start() {
        let inputThread = Thread { [weak self] in self?.run() }
        inputThread.name = "TabLink input tap"
        inputThread.qualityOfService = .userInteractive
        inputThread.start()
        _ = ready.wait(timeout: .now() + 5.0)
    }

    func stop() {
        stateLock.lock()
        stopped = true
        let loop = runLoop
        stateLock.unlock()
        if let loop {
            CFRunLoopStop(loop)
        }
    }

    private static let callback: CGEventTapCallBack = { proxy, type, event, userInfo in
        guard let userInfo else { return Unmanaged.passUnretained(event) }
        let hook = Unmanaged<InputHook>.fromOpaque(userInfo).takeUnretainedValue()
        return hook.handle(proxy: proxy, type: type, event: event)
    }

    private func handle(proxy: CGEventTapProxy, type: CGEventType, event: CGEvent) -> Unmanaged<CGEvent>? {
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            if let tap {
                CGEvent.tapEnable(tap: tap, enable: true)
            }
            return Unmanaged.passUnretained(event)
        }
        if type == .keyDown || type == .keyUp || type == .flagsChanged {
            if onKey?(type, event) == true { return nil }
        } else if type == .mouseMoved || type == .leftMouseDragged || type == .rightMouseDragged ||
                    type == .otherMouseDragged || type == .leftMouseDown || type == .leftMouseUp ||
                    type == .rightMouseDown || type == .rightMouseUp || type == .otherMouseDown ||
                    type == .otherMouseUp || type == .scrollWheel {
            if onMouse?(type, event) == true { return nil }
        }
        return Unmanaged.passUnretained(event)
    }

    private func run() {
        let maskTypes: [CGEventType] = [
            .mouseMoved, .leftMouseDragged, .rightMouseDragged, .otherMouseDragged,
            .leftMouseDown, .leftMouseUp, .rightMouseDown, .rightMouseUp,
            .otherMouseDown, .otherMouseUp, .scrollWheel,
            .keyDown, .keyUp, .flagsChanged
        ]
        var mask: CGEventMask = 0
        for type in maskTypes { mask |= CGEventMask(1) << CGEventMask(type.rawValue) }

        let userInfo = Unmanaged.passUnretained(self).toOpaque()
        let created = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .defaultTap,
            eventsOfInterest: mask,
            callback: InputHook.callback,
            userInfo: userInfo
        )

        let currentLoop = CFRunLoopGetCurrent()
        stateLock.lock()
        runLoop = currentLoop
        tap = created
        stateLock.unlock()

        if let created {
            if let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, created, 0) {
                CFRunLoopAddSource(currentLoop, source, .commonModes)
            }
        } else {
            sink.log("Accessibility + Input Monitoring permission is required for the helper binary")
        }
        ready.signal()
        CFRunLoopRun()

        if let created { CFMachPortInvalidate(created) }
        stateLock.lock()
        tap = nil
        runLoop = nil
        stateLock.unlock()
    }
}
