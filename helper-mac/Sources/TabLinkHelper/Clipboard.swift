import AppKit
import Foundation

final class ClipboardService {
    private let queue = DispatchQueue(label: "tablink.clipboard")

    func changeCount() -> Int {
        queue.sync { NSPasteboard.general.changeCount }
    }

    func get() -> String? {
        queue.sync { NSPasteboard.general.string(forType: .string) }
    }

    @discardableResult
    func set(_ text: String) -> Bool {
        queue.sync {
            let pasteboard = NSPasteboard.general
            pasteboard.clearContents()
            return pasteboard.setString(text, forType: .string)
        }
    }
}
