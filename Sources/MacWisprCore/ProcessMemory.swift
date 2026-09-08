import Darwin
import Foundation

public enum ProcessMemory {
    /// Coarse free+inactive+purgeable RAM. `nil` if the host probe failed.
    /// `os_proc_available_memory` is iOS-only.
    public static func availableBytes() -> UInt64? {
        var stats = vm_statistics64()
        var count = mach_msg_type_number_t(
            MemoryLayout<vm_statistics64_data_t>.size / MemoryLayout<integer_t>.size
        )
        let kr = withUnsafeMutablePointer(to: &stats) { ptr in
            ptr.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                host_statistics64(mach_host_self(), HOST_VM_INFO64, $0, &count)
            }
        }
        guard kr == KERN_SUCCESS else { return nil }
        let page = UInt64(vm_kernel_page_size)
        let pages = UInt64(stats.free_count)
            + UInt64(stats.inactive_count)
            + UInt64(stats.purgeable_count)
        let bytes = pages * page
        return bytes > 0 ? bytes : nil
    }
}
