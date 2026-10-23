import Foundation
import PDFKit

let args = CommandLine.arguments
let input = try Data(contentsOf: URL(fileURLWithPath: args[1]))
let rows = try JSONSerialization.jsonObject(with: input) as! [[String: String]]
FileManager.default.createFile(atPath: args[2], contents: nil)
let output = try FileHandle(forWritingTo: URL(fileURLWithPath: args[2]))
var total = 0
for row in rows {
    guard let pdf = PDFDocument(url: URL(fileURLWithPath: row["local_path"]!)) else {
        fputs("Unreadable PDF: \(row["bid_no"]!)\n", stderr)
        continue
    }
    for i in 0..<pdf.pageCount {
        let item: [String: Any] = ["bid_no": row["bid_no"]!, "revision": row["bid_order"]!,
            "filename": row["file_name"]!, "page": i + 1,
            "url": row["url"]!, "local_path": row["local_path"]!,
            "text": pdf.page(at: i)?.string ?? ""]
        let encoded = try JSONSerialization.data(withJSONObject: item, options: [.sortedKeys])
        try output.write(contentsOf: encoded)
        try output.write(contentsOf: Data("\n".utf8))
        total += 1
    }
    print("\(row["bid_no"]!): \(pdf.pageCount) pages")
}
try output.close()
print("Total pages: \(total)")
