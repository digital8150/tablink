import CoreGraphics
import Foundation

final class MultiControl {
    private let lock = NSLock()
    private let hook: InputHook
    private let sink: EventSink
    private let clipboardService: ClipboardService

    private var control: ScrcpyControl?
    private var info = TabletInfo()
    private var monitors: [MonitorInfo] = []
    private var monitorObject: MonitorInfo?

    private var enabled = true
    private var clipboardEnabled = true
    private var side = "right"
    private var hangul = "shift_space"
    private var monitorIndex = -1
    private var speed = 1.0

    private var active = false
    private var cursorCaptured = false
    private var exitX = 0.0
    private var exitY = 0.0
    private var tx = 0.0
    private var ty = 0.0
    private var rx = 0.0
    private var ry = 0.0
    private var buttons = 0
    private var pcButtons = 0
    private var edgeHits = 0
    private var wheel = 0
    private var horizontalWheel = 0
    private var mods = 0
    private var keys: [Int] = []
    private var tabletKeyCodes = Set<Int>()
    private var pcKeyCodes = Set<Int>()
    private var swallowUp = Set<Int>()
    private var heldControl = Set<Int>()
    private var heldOption = Set<Int>()
    private var hotkeyHeld = false
    private var clipboardSequence: Int?

    init(hook: InputHook, sink: EventSink, clipboardService: ClipboardService) {
        self.hook = hook
        self.sink = sink
        self.clipboardService = clipboardService
    }

    func start() { hook.start() }

    func stop() {
        lock.lock()
        if active { leaveLocked(tabletPosition: nil) }
        lock.unlock()
        hook.stop()
        restoreCursor()
    }

    func configure(_ command: [String: Any]) {
        lock.lock()
        if let value = command["enabled"] as? Bool { enabled = value }
        if let value = command["side"] as? String, ["right", "left", "top", "bottom"].contains(value) { side = value }
        if let value = command["monitor"] as? NSNumber { monitorIndex = value.intValue }
        if let value = command["speed"] as? NSNumber, value.doubleValue.isFinite { speed = max(0.01, value.doubleValue) }
        if let value = command["hangul"] as? String, value == "shift_space" || value == "lang1" { hangul = value }
        if let value = command["clipboard"] as? Bool { clipboardEnabled = value }
        if !enabled && active { leaveLocked(tabletPosition: nil) }
        lock.unlock()
        refreshMonitors()
    }

    func refreshMonitors() {
        let list = MonitorService.list()
        lock.lock()
        monitors = list
        let target = MonitorService.target(list, index: monitorIndex, side: side)
        lock.unlock()
        MonitorService.emit(list, target: target, to: sink)
    }

    func setControl(_ value: ScrcpyControl?) {
        lock.lock()
        if value == nil && active { leaveLocked(tabletPosition: nil) }
        control = value
        lock.unlock()
    }

    func updateInfo(_ value: TabletInfo) {
        lock.lock()
        if active && (info.width != value.width || info.height != value.height) {
            let fx = tx / Double(max(info.width - 1, 1))
            let fy = ty / Double(max(info.height - 1, 1))
            info = value
            positionLocked(x: fx * Double(max(value.width - 1, 0)), y: fy * Double(max(value.height - 1, 0)))
        } else {
            info = value
        }
        lock.unlock()
        sink.info(value)
    }

    func toggle() {
        lock.lock()
        toggleLocked()
        lock.unlock()
    }

    func deviceClipboard(_ text: String) {
        lock.lock(); let use = clipboardEnabled; lock.unlock()
        guard use, !text.isEmpty, clipboardService.set(text) else { return }
        lock.lock(); clipboardSequence = clipboardService.changeCount(); lock.unlock()
    }

    func mouse(type: CGEventType, event: CGEvent) -> Bool {
        let location = event.location
        let x = Int(location.x.rounded())
        let y = Int(location.y.rounded())
        lock.lock()
        if active && !readyLocked { leaveLocked(tabletPosition: nil) }

        if type == .mouseMoved || type == .leftMouseDragged || type == .rightMouseDragged || type == .otherMouseDragged {
            if !active {
                if readyLocked && pcButtons == 0 && atEdgeLocked(x: x, y: y) {
                    edgeHits += 1
                    if edgeHits >= 2 {
                        edgeHits = 0
                        enterLocked(x: Double(x), y: Double(y), center: false)
                        lock.unlock()
                        return true
                    }
                } else {
                    edgeHits = 0
                }
                lock.unlock()
                return false
            }
            let dx = Int(event.getIntegerValueField(.mouseEventDeltaX))
            let dy = Int(event.getIntegerValueField(.mouseEventDeltaY))
            if dx != 0 || dy != 0 { moveLocked(dx: dx, dy: dy) }
            lock.unlock()
            return true
        }

        if type == .leftMouseDown || type == .leftMouseUp || type == .rightMouseDown || type == .rightMouseUp ||
            type == .otherMouseDown || type == .otherMouseUp {
            let down = type == .leftMouseDown || type == .rightMouseDown || type == .otherMouseDown
            let bit = mouseButtonBit(type: type, event: event)
            if !active {
                if bit != 0 { pcButtons = down ? pcButtons | bit : pcButtons & ~bit }
                lock.unlock()
                return false
            }
            if bit != 0 { buttons = down ? buttons | bit : buttons & ~bit }
            control?.mouse(buttons: buttons, barrier: true)
            lock.unlock()
            return true
        }

        if type == .scrollWheel {
            if !active { lock.unlock(); return false }
            wheel += Int(event.getIntegerValueField(.scrollWheelEventDeltaAxis1))
            horizontalWheel += Int(event.getIntegerValueField(.scrollWheelEventDeltaAxis2))
            let vertical = wheel / 120
            let horizontal = horizontalWheel / 120
            wheel -= vertical * 120
            horizontalWheel -= horizontal * 120
            if vertical != 0 { control?.mouse(buttons: buttons, wheel: vertical) }
            if horizontal != 0 { control?.mouse(buttons: buttons, hwheel: horizontal) }
            lock.unlock()
            return true
        }
        lock.unlock()
        return false
    }

    func key(type: CGEventType, event: CGEvent) -> Bool {
        let keyCode = Int(event.getIntegerValueField(.keyboardEventKeycode))
        let down: Bool
        if type == .keyDown { down = true }
        else if type == .keyUp { down = false }
        else { down = modifierIsDown(keyCode: keyCode, flags: event.flags) }

        lock.lock()
        let isModifier = MacKeyMap.modifierUsage(for: keyCode) != nil
        let heldSet: Set<Int>?
        if MacKeyMap.isControl(keyCode) { heldSet = heldControl }
        else if MacKeyMap.isOption(keyCode) { heldSet = heldOption }
        else { heldSet = nil }
        if heldSet != nil {
            if MacKeyMap.isControl(keyCode) {
                if down { heldControl.insert(keyCode) } else { heldControl.remove(keyCode) }
            } else {
                if down { heldOption.insert(keyCode) } else { heldOption.remove(keyCode) }
            }
        }

        if keyCode == 0x2E && !isModifier && !heldControl.isEmpty && !heldOption.isEmpty && readyLocked {
            if down {
                if !hotkeyHeld { hotkeyHeld = true; toggleLocked() }
                swallowUp.insert(keyCode)
            } else {
                hotkeyHeld = false
                swallowUp.remove(keyCode)
            }
            lock.unlock()
            return true
        }
        if keyCode == 0x2E && !down { hotkeyHeld = false }

        if !active {
            if down {
                pcKeyCodes.insert(keyCode)
                lock.unlock()
                return false
            }
            if swallowUp.remove(keyCode) != nil {
                lock.unlock()
                return true
            }
            pcKeyCodes.remove(keyCode)
            lock.unlock()
            return false
        }

        if !down && pcKeyCodes.contains(keyCode) && !tabletKeyCodes.contains(keyCode) {
            pcKeyCodes.remove(keyCode)
            lock.unlock()
            return false
        }
        if down && pcKeyCodes.contains(keyCode) {
            lock.unlock()
            return true
        }
        if MacKeyMap.isHangul(keyCode) && hangul == "shift_space" {
            if down && !tabletKeyCodes.contains(keyCode) {
                tabletKeyCodes.insert(keyCode)
                control?.keyboard(modifiers: mods | 0x02, keys: keys + [0x2C])
                control?.keyboard(modifiers: mods, keys: keys)
            } else if !down {
                tabletKeyCodes.remove(keyCode)
            }
            lock.unlock()
            return true
        }

        guard let usage = MacKeyMap.usage(for: keyCode) else {
            lock.unlock()
            return true
        }
        if down { tabletKeyCodes.insert(keyCode) } else { tabletKeyCodes.remove(keyCode) }
        if usage >= 0xE0 && usage <= 0xE7 {
            let bit = 1 << (usage - 0xE0)
            let next = down ? mods | bit : mods & ~bit
            if next == mods { lock.unlock(); return true }
            mods = next
        } else if down {
            if !keys.contains(usage) { keys.append(usage); if keys.count > 6 { keys.removeFirst() } }
            else { lock.unlock(); return true }
        } else if let index = keys.firstIndex(of: usage) {
            keys.remove(at: index)
        } else {
            lock.unlock()
            return true
        }
        control?.keyboard(modifiers: mods, keys: keys)
        lock.unlock()
        return true
    }

    private var readyLocked: Bool { enabled && control != nil && control?.alive == true }

    private func targetLocked() -> MonitorInfo? {
        let index = MonitorService.target(monitors, index: monitorIndex, side: side)
        guard index >= 0 && index < monitors.count else { return nil }
        return monitors[index]
    }

    private func coveredLocked(x: Int, y: Int) -> Bool {
        monitors.contains { $0.left <= x && x < $0.right && $0.top <= y && y < $0.bottom }
    }

    private func atEdgeLocked(x: Int, y: Int) -> Bool {
        guard let monitor = targetLocked() else { return false }
        monitorObject = monitor
        switch side {
        case "right": return x >= monitor.right - 1 && monitor.top <= y && y < monitor.bottom && !coveredLocked(x: monitor.right, y: y)
        case "left": return x <= monitor.left && monitor.top <= y && y < monitor.bottom && !coveredLocked(x: monitor.left - 1, y: y)
        case "top": return y <= monitor.top && monitor.left <= x && x < monitor.right && !coveredLocked(x: x, y: monitor.top - 1)
        default: return y >= monitor.bottom - 1 && monitor.left <= x && x < monitor.right && !coveredLocked(x: x, y: monitor.bottom)
        }
    }

    private func enterLocked(x: Double, y: Double, center: Bool) {
        guard let monitor = monitorObject ?? targetLocked(), let control, control.alive else { return }
        monitorObject = monitor
        let fx = min(max((x - Double(monitor.left)) / Double(max(monitor.width, 1)), 0), 1)
        let fy = min(max((y - Double(monitor.top)) / Double(max(monitor.height, 1)), 0), 1)
        var targetX: Double; var targetY: Double
        var px = x; var py = y
        if center {
            targetX = Double(info.width) / 2; targetY = Double(info.height) / 2
        } else if side == "right" {
            targetX = 0; targetY = fy * Double(max(info.height - 1, 0)); px = Double(monitor.right - 1)
        } else if side == "left" {
            targetX = Double(max(info.width - 1, 0)); targetY = fy * Double(max(info.height - 1, 0)); px = Double(monitor.left)
        } else if side == "top" {
            targetX = fx * Double(max(info.width - 1, 0)); targetY = Double(max(info.height - 1, 0)); py = Double(monitor.top)
        } else {
            targetX = fx * Double(max(info.width - 1, 0)); targetY = 0; py = Double(monitor.bottom - 1)
        }
        buttons = 0; wheel = 0; horizontalWheel = 0
        positionLocked(x: targetX, y: targetY)
        exitX = px; exitY = py
        active = true
        cursorCaptured = true
        CGAssociateMouseAndMouseCursorPosition(0)
        CGDisplayHideCursor(CGMainDisplayID())
        sink.active(true)
        if clipboardEnabled {
            let expectedControl = control
            DispatchQueue.global(qos: .utility).async { [weak self] in
                guard let self else { return }
                let sequence = self.clipboardService.changeCount()
                self.lock.lock()
                let shouldPush = self.clipboardEnabled && self.clipboardSequence != sequence && self.control === expectedControl
                if shouldPush { self.clipboardSequence = sequence }
                self.lock.unlock()
                if shouldPush, let text = self.clipboardService.get(), !text.isEmpty { expectedControl.setClipboard(text) }
            }
        }
    }

    private func positionLocked(x: Double, y: Double) {
        guard let control else { return }
        control.mouse(x: -32767, y: -32767, buttons: buttons, barrier: true)
        control.mouse(x: -32767, y: -32767, buttons: buttons, barrier: true)
        let ix = Int((x / max(info.gainX, 0.001)).rounded())
        let iy = Int((y / max(info.gainY, 0.001)).rounded())
        control.mouse(x: ix, y: iy, buttons: buttons, barrier: true)
        tx = min(max(Double(ix) * info.gainX, 0), Double(max(info.width - 1, 0)))
        ty = min(max(Double(iy) * info.gainY, 0), Double(max(info.height - 1, 0)))
        rx = 0; ry = 0
    }

    private func moveLocked(dx: Int, dy: Int) {
        let nx = tx + Double(dx) * speed
        let ny = ty + Double(dy) * speed
        if (side == "right" && nx < 0) || (side == "left" && nx > Double(info.width - 1)) ||
            (side == "top" && ny > Double(info.height - 1)) || (side == "bottom" && ny < 0) {
            leaveLocked(tabletPosition: (nx, ny))
            return
        }
        // Deliberately do not clamp nx/ny before calculating counts. This is required to
        // keep sending edgeward motion until the Android pointer reaches its own clamp.
        let cx = (nx - tx) / max(info.gainX, 0.001) + rx
        let cy = (ny - ty) / max(info.gainY, 0.001) + ry
        let ix = Int(cx.rounded()); let iy = Int(cy.rounded())
        rx = cx - Double(ix); ry = cy - Double(iy)
        if ix != 0 || iy != 0 { control?.mouse(x: ix, y: iy, buttons: buttons) }
        tx += Double(ix) * info.gainX; ty += Double(iy) * info.gainY
        if tx < 0 || tx > Double(info.width - 1) { tx = min(max(tx, 0), Double(max(info.width - 1, 0))); rx = 0 }
        if ty < 0 || ty > Double(info.height - 1) { ty = min(max(ty, 0), Double(max(info.height - 1, 0))); ry = 0 }
    }

    private func leaveLocked(tabletPosition: (Double, Double)?) {
        active = false
        if let control, control.alive {
            control.keyboard(modifiers: 0, keys: [])
            control.mouse(buttons: 0, barrier: true)
        }
        swallowUp.formUnion(tabletKeyCodes)
        tabletKeyCodes.removeAll(); keys.removeAll(); mods = 0; buttons = 0; edgeHits = 0
        let monitor = monitorObject ?? targetLocked()
        var x = exitX; var y = exitY
        if let tabletPosition, let monitor {
            let fx = min(max(tabletPosition.0 / Double(max(info.width - 1, 1)), 0), 1)
            let fy = min(max(tabletPosition.1 / Double(max(info.height - 1, 1)), 0), 1)
            if side == "right" { x = Double(monitor.right - 3); y = Double(monitor.top) + fy * Double(max(monitor.height - 1, 0)) }
            else if side == "left" { x = Double(monitor.left + 2); y = Double(monitor.top) + fy * Double(max(monitor.height - 1, 0)) }
            else if side == "top" { x = Double(monitor.left) + fx * Double(max(monitor.width - 1, 0)); y = Double(monitor.top + 2) }
            else { x = Double(monitor.left) + fx * Double(max(monitor.width - 1, 0)); y = Double(monitor.bottom - 3) }
        } else if atEdgeLocked(x: Int(exitX.rounded()), y: Int(exitY.rounded())) {
            if side == "right" { x -= 3 }
            else if side == "left" { x += 2 }
            else if side == "top" { y += 2 }
            else { y -= 3 }
        }
        exitX = x; exitY = y
        restoreCursor()
        sink.active(false)
    }

    private func toggleLocked() {
        guard readyLocked else { return }
        if active { leaveLocked(tabletPosition: nil) }
        else {
            let location = CGEvent(source: nil)?.location ?? CGPoint(x: 0, y: 0)
            monitorObject = targetLocked()
            enterLocked(x: location.x, y: location.y, center: true)
        }
    }

    private func restoreCursor() {
        if cursorCaptured {
            CGWarpMouseCursorPosition(CGPoint(x: exitX, y: exitY))
            CGAssociateMouseAndMouseCursorPosition(1)
            CGDisplayShowCursor(CGMainDisplayID())
            cursorCaptured = false
        }
    }

    private func modifierIsDown(keyCode: Int, flags: CGEventFlags) -> Bool {
        switch keyCode {
        case 0x3B, 0x3E: return flags.contains(.maskControl)
        case 0x3A, 0x3D: return flags.contains(.maskAlternate)
        case 0x38, 0x3C: return flags.contains(.maskShift)
        case 0x36, 0x37: return flags.contains(.maskCommand)
        default: return false
        }
    }

    private func mouseButtonBit(type: CGEventType, event: CGEvent) -> Int {
        if type == .leftMouseDown || type == .leftMouseUp { return 1 }
        if type == .rightMouseDown || type == .rightMouseUp { return 2 }
        let number = Int(event.getIntegerValueField(.mouseEventButtonNumber))
        if number == 2 { return 4 }
        if number == 3 { return 8 }
        return 16
    }
}
